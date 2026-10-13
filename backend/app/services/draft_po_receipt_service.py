"""Set the requested receipt date on Draft purchase orders only.

Open and Released purchase orders are refused and not written. A single
Draft can take an explicit date or be recomputed from the lead-time rule.
The one-off backfill recomputes every Draft from today (America/Edmonton),
because existing drafts were left on BC's blank date 0001-01-01 and their
original order dates are not the clock the owner wants started.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any, Optional

import requests

from app.integrations.bc.client import bc_client
from app.services.draft_po_lines_service import DraftPoEditError
from app.services.vendor_receipt_lead_time import (
    ReceiptPlan,
    business_today,
    email_line,
    match_vendor_lead_time,
    parse_po_date,
    requested_receipt_on,
)

logger = logging.getLogger(__name__)


def _not_draft_message(number: str, status: str) -> str:
    shown = status or "unknown"
    return (
        f"{number} is status {shown!r}, not Draft. "
        "Requested receipt date can be set on Draft purchase orders only. "
        "Open and Released purchase orders are left unchanged."
    )


def _require_date(value: Any, field: str) -> date:
    parsed = parse_po_date(value)
    if parsed is None:
        raise DraftPoEditError(400, f"{field} must be a real date (YYYY-MM-DD)")
    return parsed


def _vendor_no(po: dict) -> str:
    return (po.get("vendorNumber") or "").strip()


def _vendor_name(po: dict) -> str:
    return (po.get("vendorName") or po.get("payToVendorName") or "").strip()


class DraftPoReceiptService:
    def set_or_recompute(
        self,
        kind: str,
        value: str,
        *,
        requested_receipt_date: Optional[str] = None,
        recompute: bool = False,
        as_of: Optional[str] = None,
        actor: str = "",
    ) -> dict:
        """Set an explicit date, or recompute one Draft from the lead-time rule.

        Recompute uses ``as_of`` when it is sent. Otherwise it uses the PO
        order date, and today when that order date is blank. Explicit date
        and recompute cannot be sent together.
        """
        explicit = (requested_receipt_date or "").strip() or None
        if explicit and recompute:
            raise DraftPoEditError(
                400,
                "Send requested_receipt_date or recompute, not both",
            )
        if not explicit and not recompute:
            raise DraftPoEditError(
                400,
                "Send requested_receipt_date (YYYY-MM-DD) or recompute: true",
            )
        if explicit and as_of:
            raise DraftPoEditError(400, "as_of is only used with recompute")

        po = self._load_draft(kind, value)
        number = po.get("number") or value
        previous = parse_po_date(po.get("requestedReceiptDate"))
        vendor_no = _vendor_no(po)
        vendor_name = _vendor_name(po)

        if explicit:
            target = _require_date(explicit, "requested_receipt_date")
            rule = match_vendor_lead_time(vendor_no, vendor_name)
            source = "set"
            base = None
        else:
            if as_of:
                base = _require_date(as_of, "as_of")
            else:
                base = parse_po_date(po.get("orderDate")) or business_today()
            plan = requested_receipt_on(vendor_no, vendor_name, base)
            target = plan.requested_receipt_date
            rule = plan.rule
            source = "recompute"

        changed = previous != target
        if changed:
            logger.info(
                "Admin %s setting Draft PO %s requested receipt %s (%s, was %s)",
                actor or "?",
                number,
                target.isoformat(),
                source,
                previous.isoformat() if previous else "blank",
            )
            self._write(po, target)
        return _public_row(
            po,
            target=target,
            previous=previous,
            rule_key=rule.key,
            lead_days=rule.days,
            ship_when_ready=rule.ship_when_ready,
            base=base,
            source=source,
            changed=changed,
            applied=changed,
            email=email_line(rule, None if rule.ship_when_ready else target),
        )

    def backfill(self, *, dry_run: bool = True, as_of: Optional[str] = None, actor: str = "") -> dict:
        """Recompute every Draft PO from today (or ``as_of``).

        ``dry_run`` defaults to true and does not write. Open and Released
        rows are skipped if Business Central's Draft filter lets one through.
        A failure on one PO is recorded on that row and the rest continue.
        """
        base = _require_date(as_of, "as_of") if as_of else business_today()
        try:
            rows = bc_client.get_draft_purchase_orders()
        except requests.HTTPError as exc:
            raise DraftPoEditError(
                502, f"Failed to list Draft purchase orders in Business Central: {exc}",
            ) from exc

        results = []
        updated = 0
        unchanged = 0
        would_update = 0
        skipped = 0
        failed = 0
        for po in rows or []:
            status = (po.get("status") or "")
            number = po.get("number") or po.get("id") or "?"
            if status.lower() != "draft":
                skipped += 1
                results.append({
                    "bc_po_number": po.get("number"),
                    "bc_po_id": po.get("id"),
                    "status": status or None,
                    "skipped": True,
                    "applied": False,
                    "changed": False,
                    "error": _not_draft_message(str(number), status),
                })
                continue

            vendor_no = _vendor_no(po)
            vendor_name = _vendor_name(po)
            plan: ReceiptPlan = requested_receipt_on(vendor_no, vendor_name, base)
            previous = parse_po_date(po.get("requestedReceiptDate"))
            changed = previous != plan.requested_receipt_date
            applied = False
            error = None
            if changed and not dry_run:
                if not po.get("id"):
                    error = f"{number} has no Business Central id"
                    failed += 1
                else:
                    try:
                        self._write(po, plan.requested_receipt_date)
                        applied = True
                        updated += 1
                    except DraftPoEditError as exc:
                        error = exc.detail
                        failed += 1
                    except requests.HTTPError as exc:
                        error = f"Business Central rejected the requested receipt date: {exc}"
                        failed += 1
            elif changed:
                would_update += 1
            else:
                unchanged += 1

            logger.info(
                "Draft PO receipt backfill %s %s -> %s dry_run=%s changed=%s applied=%s actor=%s",
                number,
                previous.isoformat() if previous else "blank",
                plan.requested_receipt_date.isoformat(),
                dry_run,
                changed,
                applied,
                actor or "?",
            )
            results.append(_public_row(
                po,
                target=plan.requested_receipt_date,
                previous=previous,
                rule_key=plan.rule.key,
                lead_days=plan.rule.days,
                ship_when_ready=plan.rule.ship_when_ready,
                base=base,
                source="backfill",
                changed=changed,
                applied=applied,
                email=plan.email_line(),
                error=error,
            ))

        return {
            "dry_run": dry_run,
            "as_of": base.isoformat(),
            "count": len(results),
            "updated": updated,
            "would_update": would_update,
            "unchanged": unchanged,
            "skipped": skipped,
            "failed": failed,
            "results": results,
        }

    def _load_draft(self, kind: str, value: str) -> dict:
        try:
            if kind == "guid":
                po = bc_client.get_purchase_order(value)
            else:
                po = bc_client.get_purchase_order_by_number(value)
        except requests.HTTPError as exc:
            bc_status = getattr(getattr(exc, "response", None), "status_code", None)
            if bc_status == 404:
                raise DraftPoEditError(
                    404, f"Purchase order {value} not found in Business Central",
                ) from exc
            raise DraftPoEditError(
                502, f"Failed to look up purchase order {value} in Business Central: {exc}",
            ) from exc
        if not po:
            raise DraftPoEditError(404, f"Purchase order {value} not found in Business Central")
        number = po.get("number") or value
        status = po.get("status") or ""
        if status.lower() != "draft":
            raise DraftPoEditError(422, _not_draft_message(number, status))
        if not po.get("id"):
            raise DraftPoEditError(502, f"Business Central returned {number} without an id")
        return po

    def _write(self, po: dict, target: date) -> None:
        number = po.get("number") or po.get("id")
        updated = bc_client.update_purchase_order(po["id"], {
            "requestedReceiptDate": target.isoformat(),
        })
        confirmed = parse_po_date(updated.get("requestedReceiptDate")) if isinstance(updated, dict) else None
        if confirmed != target:
            fresh = bc_client.get_purchase_order(po["id"])
            confirmed = parse_po_date((fresh or {}).get("requestedReceiptDate")) if isinstance(fresh, dict) else None
        if confirmed != target:
            raise DraftPoEditError(
                502,
                f"Business Central did not keep requested receipt date {target.isoformat()} on {number}",
            )


def _public_row(
    po: dict,
    *,
    target: date,
    previous: Optional[date],
    rule_key: str,
    lead_days: int,
    ship_when_ready: bool,
    base: Optional[date],
    source: str,
    changed: bool,
    applied: bool,
    email: str,
    error: Optional[str] = None,
) -> dict:
    return {
        "bc_po_number": po.get("number"),
        "bc_po_id": po.get("id"),
        "status": po.get("status"),
        "vendor_no": _vendor_no(po) or None,
        "vendor_name": _vendor_name(po) or None,
        "source": source,
        "receipt_rule": rule_key,
        "receipt_lead_days": lead_days,
        "ship_when_ready": ship_when_ready,
        "receipt_base_date": base.isoformat() if base else None,
        "previous_requested_receipt_date": previous.isoformat() if previous else None,
        "requested_receipt_date": target.isoformat(),
        "email_line": email,
        "changed": changed,
        "applied": applied,
        "error": error,
    }


draft_po_receipt_service = DraftPoReceiptService()
