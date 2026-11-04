"""Release one Business Central purchase order, only when asked.

Nothing in draft creation, line edits, review drafts, or the nightly job
calls this. The staff route is the only caller, and it requires
``confirm: true`` plus ``approved_by`` before Business Central is touched.

Status words:

* API ``Draft`` is Business Central document status Open (not released).
  That is the only status this service will release.
* API ``Open`` is Business Central document status Released. So is a
  literal ``Released``. Both are a no-op (HTTP 409), not a second release.

Customer text uses the same allow-list as PR #61
(``vendor_may_see_customer_info`` in ``po_customer_disclosure``): Elton,
Upwardor, and Nice/Micanan. That module is copied here so release works
before #61 merges. Keep the two copies the same.

Vendor acknowledgements do not store a quoted unit price, so this does
not compare an ack price to the PO line. Draft-review price warnings
(missing vendor price list, line cost vs item card) are reported and do
not block.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any, List, Optional, Sequence

import requests
from sqlalchemy.orm import Session

from app.db.models import AuditTrail
from app.integrations.bc.client import (
    PURCHASE_ORDER_RELEASE_ACTION,
    PurchaseOrderReleaseNotPublished,
    bc_client,
)
from app.services.draft_po_review_service import validate_po
from app.services.po_customer_disclosure import (
    CustomerDisclosureError,
    find_customer_leaks,
    load_customer_identities,
    lookup_sales_order,
    sales_order_numbers_from_texts,
    vendor_may_see_customer_info,
)

logger = logging.getLogger(__name__)

_RELEASED_API_STATUSES = frozenset({"open", "released"})
_SHIP_TO_FIELDS = (
    "shipToName",
    "shipToContact",
    "shipToAddressLine1",
    "shipToAddressLine2",
    "shipToCity",
    "shipToPostCode",
)
_VENDOR_QUOTE_PRICE_CHECK = {
    "applied": False,
    "reason": (
        "Vendor acknowledgements store the vendor order number, status, "
        "and completion date. They do not store a quoted unit price, so "
        "release does not compare an acknowledgement price to the PO line."
    ),
}
_PUBLISH_HINT = (
    "Business Central's api/v2.0 purchaseOrders entity cannot release a "
    "purchase order (its only bound action is receiveAndInvoice). Publish "
    "page 70150 \"OPENDC API PO Release\" from bc-extension/purchase-order-release "
    "(API publisher opendc, group purchasing, version v1.0) and assign "
    "permission set \"OPENDC PO Release\" to the integration user, on top of "
    "the permissions that user already uses to edit purchase orders. "
    "See docs/STAFF_PO_RELEASE.md."
)


class PurchaseOrderReleaseError(Exception):
    """Mapped to HTTP by the purchasing route. ``detail`` is a string or a dict."""

    def __init__(self, status_code: int, detail: Any):
        self.status_code = status_code
        self.detail = detail
        message = detail.get("message") if isinstance(detail, dict) else str(detail)
        super().__init__(message)


def _qty(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _has_positive_item_qty(po: dict) -> bool:
    for line in po.get("purchaseOrderLines") or []:
        if (line.get("lineType") or "").lower() != "item":
            continue
        if _qty(line.get("quantity")) > 0:
            return True
    return False


def _customer_leaks(po: dict) -> List[dict]:
    """Customer name, customer PO, job, or ship-to on a vendor who must not see it.

    Same matcher as PR #61. Allowlisted vendors return nothing. Comment
    lines and the external document are checked, and so are the ship-to
    header fields, because those print on the purchase order.
    """
    vendor_no = po.get("vendorNumber") or ""
    vendor_name = po.get("vendorName") or po.get("payToVendorName") or ""
    if vendor_may_see_customer_info(vendor_no, vendor_name):
        return []

    chunks: List[str] = [str(po.get("externalDocumentNumber") or "")]
    for line in po.get("purchaseOrderLines") or []:
        chunks.append(str(line.get("description") or ""))
    for field in _SHIP_TO_FIELDS:
        chunks.append(str(po.get(field) or ""))
    identities = load_customer_identities(
        sales_order_numbers_from_texts(chunks),
        lambda number: lookup_sales_order(bc_client, number),
    )

    texts: List[tuple] = []
    header = str(po.get("externalDocumentNumber") or "").strip()
    if header and not re.fullmatch(r"SO-\d+", header, re.IGNORECASE):
        texts.append(("header", header))
    for line in po.get("purchaseOrderLines") or []:
        if (line.get("lineType") or "").lower() != "comment":
            continue
        description = str(line.get("description") or "").strip()
        if description:
            texts.append(("comment", description))
    for field in _SHIP_TO_FIELDS:
        value = str(po.get(field) or "").strip()
        if value:
            texts.append(("ship_to", value))

    issues: List[dict] = []
    for where, text in texts:
        kinds = find_customer_leaks(text, identities)
        if not kinds:
            continue
        issues.append({
            "code": "customer_info_on_vendor_po",
            "severity": "error",
            "where": where,
            "description": text[:100],
            "message": str(CustomerDisclosureError(kinds)),
        })
    return issues


def _split_review_issues(review: dict) -> tuple:
    blocking: List[dict] = []
    warnings: List[dict] = []
    for issue in review.get("issues") or []:
        if not isinstance(issue, dict):
            continue
        if (issue.get("severity") or "warning") == "error":
            blocking.append(issue)
        else:
            warnings.append(issue)
    return blocking, warnings


def assess_purchase_order(po: dict) -> dict:
    """Release checks for one PO payload. Does not call the release action."""
    blocking: List[dict] = []
    if not _has_positive_item_qty(po):
        blocking.append({
            "code": "no_item_quantity",
            "severity": "error",
            "message": (
                "This purchase order has no Item line with a quantity greater "
                "than zero. A comment-only PO cannot be released."
            ),
        })
    blocking.extend(_customer_leaks(po))

    warnings: List[dict] = []
    try:
        review = validate_po(po)
    except Exception:
        logger.exception("Draft PO validation failed for %s", po.get("number"))
        blocking.append({
            "code": "draft_validation_failed",
            "severity": "error",
            "message": (
                "The existing draft-PO checks could not be completed, "
                "so the order was not released."
            ),
        })
        review = {}
    else:
        extra_blocking, warnings = _split_review_issues(review if isinstance(review, dict) else {})
        blocking.extend(extra_blocking)

    return {
        "blocking": _dedupe_issues(blocking),
        "warnings": warnings,
        "draft_validation_ok": not blocking and not warnings and bool(review),
        "vendor_quote_price_check": dict(_VENDOR_QUOTE_PRICE_CHECK),
    }


def _dedupe_issues(issues: List[dict]) -> List[dict]:
    seen = set()
    out: List[dict] = []
    for issue in issues:
        key = (
            issue.get("code"),
            issue.get("message"),
            issue.get("where"),
            issue.get("description"),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(issue)
    return out


def _already_released(status: str) -> bool:
    return (status or "").strip().casefold() in _RELEASED_API_STATUSES


def _noop_detail(number: str, status: str) -> dict:
    shown = status or "Open"
    if shown.casefold() == "open":
        message = (
            f"{number} is already released. The API status is Open, which is "
            "Business Central status Released. Nothing was changed."
        )
    else:
        message = f"{number} is already released (status {shown}). Nothing was changed."
    return {
        "message": message,
        "number": number,
        "api_status": shown,
        "released": False,
        "noop": True,
    }


def _bc_says_already_released(message: str) -> bool:
    text = (message or "").lower()
    if "already released" in text:
        return True
    return "status must be" in text and "released" in text


def _document_status(api_status: str, action_body: Optional[dict]) -> str:
    action_status = str((action_body or {}).get("status") or "")
    if action_status.casefold() == "released" or (api_status or "").casefold() in _RELEASED_API_STATUSES:
        return "Released"
    return action_status or api_status or ""


class PurchaseOrderReleaseService:
    def release(
        self,
        kind: str,
        value: str,
        *,
        confirm: bool,
        approved_by: str,
        dry_run: bool,
        actor: str,
        db: Session,
    ) -> dict:
        po = self._load(kind, value)
        number = po.get("number") or value
        status = str(po.get("status") or "")
        approver = (approved_by or "").strip()[:200]
        who = (actor or "").strip() or "staff"

        if _already_released(status):
            detail = _noop_detail(number, status)
            detail["audit_logged"] = self._audit(
                db,
                actor=who,
                approved_by=approver,
                confirm=confirm,
                dry_run=dry_run,
                po=po,
                outcome="noop",
                reasons=[],
                warnings=[],
            )
            raise PurchaseOrderReleaseError(409, detail)

        if status.casefold() != "draft":
            shown = status or "(blank)"
            message = (
                f"{number} is status {shown!r}, not Draft. Only a Draft "
                "purchase order can be released here. In the API, Draft means "
                "Business Central status Open (not yet released)."
            )
            detail = {
                "message": message,
                "number": number,
                "api_status": status,
                "released": False,
                "reasons": [{"code": "not_draft", "severity": "error", "message": message}],
            }
            detail["audit_logged"] = self._audit(
                db, actor=who, approved_by=approver, confirm=confirm, dry_run=dry_run,
                po=po, outcome="refused", reasons=detail["reasons"], warnings=[],
            )
            raise PurchaseOrderReleaseError(422, detail)

        assessment = assess_purchase_order(po)
        blocking = assessment["blocking"]
        warnings = assessment["warnings"]

        if dry_run:
            logged = self._audit(
                db, actor=who, approved_by=approver, confirm=confirm, dry_run=True,
                po=po, outcome="dry_run", reasons=blocking, warnings=warnings,
            )
            return {
                "dry_run": True,
                "released": False,
                "would_release": not blocking,
                "bc_called": False,
                "number": number,
                "api_status": status,
                "reasons": blocking,
                "warnings": warnings,
                "vendor_quote_price_check": assessment["vendor_quote_price_check"],
                "message": (
                    f"{number} would be released."
                    if not blocking
                    else f"{number} would not be released."
                ),
                "audit_logged": logged,
            }

        confirm_reasons = _confirm_reasons(confirm, approver)
        if confirm_reasons and not blocking:
            detail = {
                "message": confirm_reasons[0]["message"],
                "number": number,
                "api_status": status,
                "released": False,
                "reasons": confirm_reasons,
                "warnings": warnings,
                "vendor_quote_price_check": assessment["vendor_quote_price_check"],
            }
            detail["audit_logged"] = self._audit(
                db, actor=who, approved_by=approver, confirm=confirm, dry_run=False,
                po=po, outcome="refused", reasons=confirm_reasons, warnings=warnings,
            )
            raise PurchaseOrderReleaseError(422, detail)

        if blocking:
            detail = {
                "message": f"{number} cannot be released.",
                "number": number,
                "api_status": status,
                "released": False,
                "reasons": blocking,
                "warnings": warnings,
                "vendor_quote_price_check": assessment["vendor_quote_price_check"],
            }
            detail["audit_logged"] = self._audit(
                db, actor=who, approved_by=approver, confirm=confirm, dry_run=False,
                po=po, outcome="refused", reasons=blocking, warnings=warnings,
            )
            raise PurchaseOrderReleaseError(422, detail)

        po_id = po.get("id")
        if not po_id:
            raise PurchaseOrderReleaseError(
                502, f"{number} has no Business Central system id, so it cannot be released.",
            )

        logger.info(
            "Admin %s releasing %s approved_by=%s",
            who, number, approver,
        )
        try:
            action_body = bc_client.release_purchase_order(po_id)
        except PurchaseOrderReleaseNotPublished as exc:
            message = f"{_PUBLISH_HINT} Business Central said: {exc}"
            self._audit(
                db, actor=who, approved_by=approver, confirm=True, dry_run=False,
                po=po, outcome="bc_unavailable", reasons=[{
                    "code": "release_action_not_published",
                    "message": message,
                }], warnings=warnings,
            )
            raise PurchaseOrderReleaseError(502, message) from exc
        except requests.HTTPError as exc:
            message = str(exc)
            if _bc_says_already_released(message):
                detail = _noop_detail(number, "Released")
                detail["audit_logged"] = self._audit(
                    db, actor=who, approved_by=approver, confirm=True, dry_run=False,
                    po=po, outcome="noop", reasons=[], warnings=warnings,
                )
                raise PurchaseOrderReleaseError(409, detail) from exc
            self._audit(
                db, actor=who, approved_by=approver, confirm=True, dry_run=False,
                po=po, outcome="bc_error", reasons=[{
                    "code": "bc_rejected",
                    "message": message,
                }], warnings=warnings,
            )
            raise PurchaseOrderReleaseError(
                502, f"Business Central rejected the release of {number}: {message}",
            ) from exc

        api_status_after, reread_error = self._reread_status(po_id, action_body)
        action_status = str((action_body or {}).get("status") or "")
        bc_status = _document_status(api_status_after or "", action_body)
        confirmed = (
            (api_status_after or "").casefold() in _RELEASED_API_STATUSES
            or action_status.casefold() == "released"
        )
        still_draft = (api_status_after or "").casefold() == "draft"
        if not confirmed:
            if reread_error:
                message = (
                    f"Business Central accepted the release call for {number}, but "
                    f"the follow-up read failed ({reread_error}). Check the order "
                    "before trying again."
                )
            else:
                shown = api_status_after or "an unknown status"
                message = (
                    f"Business Central accepted the release call for {number}, but "
                    f"the order still shows {shown}. It was not marked released. "
                    "Check the order before trying again."
                )
            self._audit(
                db, actor=who, approved_by=approver, confirm=True, dry_run=False,
                po=po, outcome="unconfirmed", reasons=[{
                    "code": "release_unconfirmed",
                    "message": message,
                }], warnings=warnings, api_status_after=api_status_after,
            )
            raise PurchaseOrderReleaseError(502, {
                "message": message,
                "number": number,
                "released": False,
                "bc_called": True,
                "api_status_after": api_status_after,
                "reread_error": reread_error,
            })
        if still_draft:
            warnings = list(warnings) + [{
                "code": "status_still_draft",
                "severity": "warning",
                "message": (
                    f"The release action for {number} reported Released, but a "
                    "follow-up read of the purchaseOrders API still shows Draft. "
                    "Check the order in Business Central before releasing it again."
                ),
            }]
        message = (
            f"{number} is released. Business Central document status is Released. "
            "The purchaseOrders API reports that as Open."
        )

        logged = self._audit(
            db, actor=who, approved_by=approver, confirm=True, dry_run=False,
            po=po, outcome="released", reasons=[], warnings=warnings,
            api_status_after=api_status_after,
        )
        return {
            "dry_run": False,
            "released": True,
            "bc_called": True,
            "number": number,
            "id": po_id,
            "api_status_before": status,
            "api_status_after": api_status_after,
            "bc_document_status": bc_status,
            "bc_action": PURCHASE_ORDER_RELEASE_ACTION,
            "approved_by": approver,
            "warnings": warnings,
            "vendor_quote_price_check": assessment["vendor_quote_price_check"],
            "reread_error": reread_error,
            "message": message,
            "audit_logged": logged,
        }

    def _load(self, kind: str, value: str) -> dict:
        try:
            if kind == "guid":
                po = bc_client.get_purchase_order_with_lines(value)
            else:
                po = bc_client.get_purchase_order_by_number(value)
        except requests.HTTPError as exc:
            status_code = getattr(getattr(exc, "response", None), "status_code", None)
            if status_code == 404:
                raise PurchaseOrderReleaseError(
                    404, f"Purchase order {value} not found in Business Central",
                ) from exc
            raise PurchaseOrderReleaseError(
                502, f"Failed to look up purchase order {value} in Business Central: {exc}",
            ) from exc
        if not po:
            raise PurchaseOrderReleaseError(
                404, f"Purchase order {value} not found in Business Central",
            )
        return po

    @staticmethod
    def _reread_status(po_id: str, action_body: Optional[dict]) -> tuple:
        try:
            fresh = bc_client.get_purchase_order(po_id)
        except Exception as exc:
            logger.warning("Release of %s succeeded but the follow-up read failed", po_id, exc_info=True)
            fallback = str((action_body or {}).get("status") or "") or None
            return fallback, str(exc)
        if not isinstance(fresh, dict):
            return None, None
        return fresh.get("status"), None

    def _audit(
        self,
        db: Session,
        *,
        actor: str,
        approved_by: str,
        confirm: bool,
        dry_run: bool,
        po: dict,
        outcome: str,
        reasons: Sequence[dict],
        warnings: Sequence[dict],
        api_status_after: Optional[str] = None,
    ) -> bool:
        when = datetime.utcnow().replace(microsecond=0)
        number = str(po.get("number") or "")
        try:
            db.add(AuditTrail(
                user_id=(actor or "")[:50],
                action=f"purchase_order_release_{outcome}"[:100],
                entity_type="purchase_order",
                entity_id=number[:50],
                details={
                    "actor": actor,
                    "approved_by": approved_by or None,
                    "confirm": bool(confirm),
                    "dry_run": bool(dry_run),
                    "po_number": number,
                    "po_id": po.get("id"),
                    "vendor_number": po.get("vendorNumber"),
                    "vendor_name": po.get("vendorName"),
                    "api_status": po.get("status"),
                    "api_status_after": api_status_after,
                    "outcome": outcome,
                    "when": when.isoformat() + "Z",
                    "reasons": list(reasons),
                    "warnings": list(warnings),
                    "bc_action": PURCHASE_ORDER_RELEASE_ACTION if outcome == "released" else None,
                },
                timestamp=when,
            ))
            db.commit()
            return True
        except Exception:
            logger.exception("Purchase order release audit failed for %s", number)
            db.rollback()
            return False


def _confirm_reasons(confirm: bool, approved_by: str) -> List[dict]:
    reasons: List[dict] = []
    if confirm is not True:
        reasons.append({
            "code": "confirm_required",
            "severity": "error",
            "message": (
                "Set confirm to true to release this purchase order. "
                "Nothing was released."
            ),
        })
    if not approved_by:
        reasons.append({
            "code": "approved_by_required",
            "severity": "error",
            "message": (
                "approved_by is required. Use the name or email of the person "
                "who said to release this purchase order. Nothing was released."
            ),
        })
    return reasons


po_release_service = PurchaseOrderReleaseService()
