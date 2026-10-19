"""Release one unreleased Business Central purchase order.

The purchase order page calls an unreleased order Open. The api/v2.0
purchaseOrders resource calls that same order Draft, and a released order
Open. This service releases API status Draft only.

The standard resource does not document Microsoft.NAV.release. The client
tries that bound action, then the custom page in bc-extension/po-receive.
Reopen, invoice, and delete are not implemented.

dry_run defaults to true. A preview reads the order and writes nothing in
Business Central. A real release names one PO and posts that action once.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Optional

import requests
from sqlalchemy.orm import Session

from app.db.models import PurchaseReleaseAudit
from app.integrations.bc.client import bc_client

logger = logging.getLogger(__name__)

_GUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
_DRAFT = {"draft"}
_ALREADY_RELEASED = {"open", "released"}
_IN_REVIEW = {"in review", "pending approval", "pending prepayment"}

# API status → the status name on the purchase order page.
_PAGE_STATUS = {
    "draft": "Open",
    "open": "Released",
    "released": "Released",
    "in review": "Pending Approval",
    "pending approval": "Pending Approval",
    "pending prepayment": "Pending Prepayment",
}

BC_RELEASE_SETUP = (
    "Business Central needs Microsoft.NAV.release before this order can be "
    "released. The standard purchaseOrders API does not document that action "
    "(its documented purchase action is receiveAndInvoice, which this portal "
    "does not call). Publish page 70912 from bc-extension/po-receive "
    "(API opendc/purchasing/v1.0, entity purchaseOrderReleases, action release) "
    "and assign permission set OPENDC PO Release. Confirm object IDs 70912 and "
    "70913 are free. Do not publish a reopen action. "
    "Details are in docs/STAFF_PO_RECEIVING.md."
)


class PoReleaseError(Exception):
    """Mapped to an HTTP error by the purchasing route."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _status(value: Any) -> str:
    return str(value or "").strip().lower()


def _text(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _money(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _lines_of(po: dict) -> list:
    raw = po.get("purchaseOrderLines") or []
    if isinstance(raw, dict):
        raw = raw.get("value") or []
    return [ln for ln in raw if isinstance(ln, dict)]


def _item_number(line: dict) -> Optional[str]:
    item = line.get("lineObjectNumber")
    if item is None:
        return None
    text = str(item).strip()
    return text or None


def page_status(api_status: Any) -> Optional[str]:
    key = _status(api_status)
    if not key:
        return None
    return _PAGE_STATUS.get(key, str(api_status))


def ship_to_of(po: dict) -> dict:
    return {
        "name": _text(po.get("shipToName")),
        "contact": _text(po.get("shipToContact")),
        "address_line1": _text(po.get("shipToAddressLine1")),
        "address_line2": _text(po.get("shipToAddressLine2")),
        "city": _text(po.get("shipToCity")),
        "state": _text(po.get("shipToState")),
        "post_code": _text(po.get("shipToPostCode")),
        "country": _text(po.get("shipToCountry")),
    }


def totals_of(po: dict) -> dict:
    return {
        "total_amount_excluding_tax": _money(po.get("totalAmountExcludingTax")),
        "total_tax_amount": _money(po.get("totalTaxAmount")),
        "total_amount_including_tax": _money(po.get("totalAmountIncludingTax")),
    }


def preview_line(line: dict) -> dict:
    amount = line.get("amountExcludingTax")
    if amount is None:
        amount = line.get("netAmount")
    if amount is None:
        amount = line.get("amount")
    return {
        "id": line.get("id"),
        "sequence": line.get("sequence"),
        "line_type": line.get("lineType"),
        "item_number": _item_number(line),
        "description": line.get("description") or "",
        "quantity": _money(line.get("quantity")),
        "direct_unit_cost": _money(line.get("directUnitCost")),
        "amount": _money(amount),
    }


def parse_po_ref(raw: str) -> tuple[str, str]:
    """('guid', uuid) or ('number', 'PO-XXXXXX'). Same shapes as the route."""
    value = (raw or "").strip()
    if not value:
        raise PoReleaseError(400, "PO number is required")
    if _GUID_RE.fullmatch(value):
        return ("guid", value)
    upper = value.upper()
    if upper.startswith("PO-"):
        rest = upper[3:]
        if not rest or not rest.replace("-", "").isalnum():
            raise PoReleaseError(400, f"Invalid PO number '{raw}'")
        return ("number", upper)
    try:
        return ("number", f"PO-{int(value):06d}")
    except ValueError:
        raise PoReleaseError(400, f"Invalid PO number '{raw}'")


class PoReleaseService:
    def release(self, db: Session, kind: str, value: str, body: dict, actor: dict) -> dict:
        """Preview or release the one purchase order named by the path.

        ``dry_run`` defaults to true. Nothing is written to Business Central
        on a preview. ``po_number`` in the body, when sent, has to be that
        same order. There is no bulk release.
        """
        dry_run = bool(body.get("dry_run", True))
        confirm_raw = _text(body.get("po_number"))
        confirm = None
        if confirm_raw:
            try:
                confirm = parse_po_ref(confirm_raw)
            except PoReleaseError as exc:
                self._audit(
                    db,
                    po_number=value if kind == "number" else value,
                    po=None,
                    actor=actor,
                    dry_run=dry_run,
                    released=False,
                    outcome="rejected",
                    error=exc.detail,
                )
                raise
            self._reject_obvious_mismatch(kind, value, confirm, actor, db, dry_run)

        try:
            po = self._load(kind, value)
        except PoReleaseError as exc:
            self._audit(
                db,
                po_number=value if kind == "number" else value,
                po=None,
                actor=actor,
                dry_run=dry_run,
                released=False,
                outcome="rejected",
                error=exc.detail,
            )
            raise

        if confirm is not None:
            try:
                self._confirm_loaded(kind, value, confirm, po)
            except PoReleaseError as exc:
                self._audit(
                    db,
                    po_number=po.get("number") or value,
                    po=po,
                    actor=actor,
                    dry_run=dry_run,
                    released=False,
                    outcome="rejected",
                    error=exc.detail,
                )
                raise

        try:
            self._require_releasable(po)
        except PoReleaseError as exc:
            self._audit(
                db,
                po_number=po.get("number") or value,
                po=po,
                actor=actor,
                dry_run=dry_run,
                released=False,
                outcome="rejected",
                error=exc.detail,
            )
            raise

        if dry_run:
            preview = self._body(po, dry_run=True, released=False, status_after=None)
            audit_id = self._audit(
                db,
                po_number=preview["bc_po_number"] or value,
                po=po,
                actor=actor,
                dry_run=True,
                released=False,
                outcome="dry_run",
                status_after=None,
            )
            preview["audit_id"] = audit_id
            logger.info(
                "PO release preview actor=%s po=%s status=%s",
                actor.get("actor_name"), preview["bc_po_number"], preview["status"],
            )
            return preview

        number = po.get("number") or value
        audit_id = self._audit(
            db,
            po_number=number,
            po=po,
            actor=actor,
            dry_run=False,
            released=False,
            outcome="pending",
        )
        try:
            self._apply(po)
        except PoReleaseError as exc:
            self._finish(db, audit_id, outcome="bc_error", released=False, error=exc.detail)
            raise

        fresh = self._reload(po)
        if fresh is not None and _status(fresh.get("status")) not in _ALREADY_RELEASED:
            detail = (
                f"Business Central accepted the release call for {number} but the "
                f"order is still status {fresh.get('status')!r}. "
                "Check the purchase order before trying again. Nothing was retried."
            )
            self._finish(db, audit_id, outcome="bc_error", released=False, error=detail)
            raise PoReleaseError(502, detail)

        source = fresh or po
        status_after = (fresh or {}).get("status") or "Open"
        result = self._body(source, dry_run=False, released=True, status_after=status_after)
        result["audit_id"] = audit_id
        result["reloaded"] = fresh is not None
        try:
            self._finish(
                db,
                audit_id,
                outcome="released",
                released=True,
                status_after=str(status_after),
                error=None,
            )
        except Exception:
            logger.exception("Purchase order %s was released but the audit row could not be updated", number)
            result["audit_logged"] = False
        logger.info(
            "PO released actor=%s po=%s status_after=%s",
            actor.get("actor_name"), number, status_after,
        )
        return result

    def _reject_obvious_mismatch(self, kind, value, confirm, actor, db, dry_run) -> None:
        c_kind, c_value = confirm
        mismatch = None
        if kind == "number" and c_kind == "number" and c_value != value.upper():
            mismatch = (
                f"PO number {c_value} does not match {value}. "
                "Release names one purchase order. Nothing was released."
            )
        elif kind == "guid" and c_kind == "guid" and c_value.lower() != value.lower():
            mismatch = (
                "The purchase order id in the body does not match the purchase order "
                "in the path. Nothing was released."
            )
        if mismatch is None:
            return
        self._audit(
            db,
            po_number=value if kind == "number" else c_value,
            po=None,
            actor=actor,
            dry_run=dry_run,
            released=False,
            outcome="rejected",
            error=mismatch,
        )
        raise PoReleaseError(400, mismatch)

    def _confirm_loaded(self, kind, value, confirm, po: dict) -> None:
        c_kind, c_value = confirm
        number = str(po.get("number") or "").upper()
        po_id = str(po.get("id") or "").lower()
        if c_kind == "number":
            path_ok = kind != "number" or c_value == value.upper()
            if c_value == number and path_ok:
                return
            raise PoReleaseError(
                400,
                f"PO number {c_value} does not match {number or value}. "
                "Nothing was released.",
            )
        if c_value.lower() == po_id and (kind != "guid" or c_value.lower() == value.lower()):
            return
        raise PoReleaseError(
            400,
            "The purchase order id in the body does not match this purchase order. "
            "Nothing was released.",
        )

    def _require_releasable(self, po: dict) -> None:
        number = po.get("number") or "This purchase order"
        status = _status(po.get("status"))
        if status in _DRAFT:
            return
        if status in _ALREADY_RELEASED:
            raise PoReleaseError(
                422,
                f"{number} is already released (API status {po.get('status')!r}, "
                "which is Released on the purchase order page). Nothing was released.",
            )
        if status in _IN_REVIEW:
            raise PoReleaseError(
                422,
                f"{number} is status {po.get('status')!r} and cannot be released from "
                "the portal. Nothing was released.",
            )
        shown = po.get("status") or "unknown"
        raise PoReleaseError(
            422,
            f"{number} is status {shown!r}. Only an unreleased purchase order "
            "(API status Draft, Open on the purchase order page) can be released. "
            "Nothing was released.",
        )

    def _apply(self, po: dict) -> None:
        po_id = po.get("id")
        number = po.get("number") or po_id
        if not po_id:
            raise PoReleaseError(502, f"{number} has no Business Central id")
        try:
            bc_client.post_purchase_order_release(po_id)
        except RuntimeError as exc:
            raise PoReleaseError(502, f"{exc} {BC_RELEASE_SETUP}") from exc
        except requests.HTTPError as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status is None or status >= 500:
                raise PoReleaseError(
                    502,
                    f"Business Central may have released {number} but returned an error: {exc}. "
                    "Check the purchase order in Business Central before trying again. "
                    "This portal did not retry the release.",
                ) from exc
            raise PoReleaseError(
                502,
                f"Business Central did not release {number}: {exc}. {BC_RELEASE_SETUP}",
            ) from exc

    def _body(self, po: dict, *, dry_run: bool, released: bool, status_after: Any) -> dict:
        status = po.get("status")
        return {
            "bc_po_number": po.get("number"),
            "bc_po_id": po.get("id"),
            "vendor_number": _text(po.get("vendorNumber")),
            "vendor_name": _text(po.get("vendorName") or po.get("payToVendorName")),
            "status": status,
            "bc_page_status": page_status(status),
            "ship_to": ship_to_of(po),
            "totals": totals_of(po),
            "lines": [preview_line(line) for line in _lines_of(po)],
            "dry_run": dry_run,
            "released": released,
            "wrote": released,
            "status_after_release": "Open" if dry_run else status_after,
            "bc_page_status_after_release": "Released" if (dry_run or released) else page_status(status_after),
            "status_after": status_after,
        }

    def _load(self, kind: str, value: str) -> dict:
        try:
            if kind == "guid":
                po = bc_client.get_purchase_order_with_lines(value)
            else:
                po = bc_client.get_purchase_order_by_number(value)
        except requests.HTTPError as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status == 404:
                raise PoReleaseError(404, f"Purchase order {value} not found") from exc
            raise PoReleaseError(
                502, f"Failed to load purchase order {value} from Business Central: {exc}",
            ) from exc
        if not po:
            raise PoReleaseError(404, f"Purchase order {value} not found")
        return po

    def _reload(self, po: dict) -> Optional[dict]:
        po_id = po.get("id")
        if not po_id:
            return None
        try:
            return bc_client.get_purchase_order_with_lines(po_id)
        except requests.HTTPError:
            logger.warning("Could not reload purchase order %s after release", po.get("number"))
            return None

    def _audit(
        self,
        db: Session,
        *,
        po_number: str,
        po: Optional[dict],
        actor: dict,
        dry_run: bool,
        released: bool,
        outcome: str,
        error: Optional[str] = None,
        status_after: Optional[str] = None,
    ) -> Optional[int]:
        try:
            row = PurchaseReleaseAudit(
                user_id=actor.get("user_id"),
                actor_email=actor.get("actor_email"),
                actor_name=actor.get("actor_name"),
                service_key_id=actor.get("service_key_id"),
                service_key_name=actor.get("service_key_name"),
                po_number=(po or {}).get("number") or po_number or "",
                po_id=(po or {}).get("id"),
                vendor_number=_text((po or {}).get("vendorNumber")),
                vendor_name=_text((po or {}).get("vendorName") or (po or {}).get("payToVendorName")),
                status_before=_text((po or {}).get("status")),
                status_after=status_after,
                ship_to=ship_to_of(po) if po else None,
                totals=totals_of(po) if po else None,
                lines=[preview_line(line) for line in _lines_of(po)] if po else None,
                dry_run=dry_run,
                released=released,
                outcome=outcome,
                error=error,
            )
            db.add(row)
            db.commit()
            db.refresh(row)
            return row.id
        except Exception:
            logger.warning("Could not audit purchase release for %s", po_number, exc_info=True)
            db.rollback()
            if outcome in {"dry_run", "pending", "released"}:
                raise
            return None

    def _finish(self, db: Session, audit_id: Optional[int], **fields) -> None:
        if audit_id is None:
            return
        row = db.query(PurchaseReleaseAudit).filter(PurchaseReleaseAudit.id == audit_id).one()
        for key, value in fields.items():
            setattr(row, key, value)
        db.commit()


po_release_service = PoReleaseService()
