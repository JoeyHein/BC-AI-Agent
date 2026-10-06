"""Edit lines on a Business Central Draft purchase order.

Staff can change quantity, description (BC's 100-character limit), unit
cost, and item number; delete a line; add an Item or Comment line; and
reorder. Reorder has no BC line-renumber API, so the lines are snapshotted,
deleted, and re-added in the target order. After the rewrite the fresh
lines are checked against the snapshot. A mismatch, or a failure part way
through, deletes whatever is on the PO and writes the snapshot back.
Released / Open purchase orders are refused. This service does not reopen
them — un-releasing a PO that has already gone to the vendor is a separate
decision and is not done from a line edit.

api/v2.0 ``purchaseOrderLines`` stores item, quantity, unit of measure,
direct unit cost, description, description2, and locationId. Drop shipment,
special order, and the linked sales order are not on that entity. When a
line payload already carries those keys they are sent back on the re-added
line. If Business Central rejects them the rewrite fails and the snapshot
is restored, so a linkage flag is not silently dropped.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, Sequence

import requests

from app.integrations.bc.client import bc_client
from app.services.po_line_order import (
    BC_DESCRIPTION_MAX,
    classify_line,
    is_comment_line,
    order_po_lines,
    same_line_order,
)

logger = logging.getLogger(__name__)

# Linkage keys are not on api/v2.0 purchaseOrderLines. They are written back
# only when the snapshot line already has them. A BC rejection fails the
# rewrite and restores the snapshot, so a flag is not silently dropped.
_LINKAGE_FIELDS = (
    "dropShipment",
    "specialOrder",
    "salesOrderId",
    "salesOrderLineId",
    "specialOrderSalesNo",
    "specialOrderSalesLineNo",
)


class DraftPoEditError(Exception):
    """Mapped to an HTTP error by the purchasing route."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _f(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _close(left: Any, right: Any, tol: float = 0.0001) -> bool:
    return abs(_f(left) - _f(right)) <= tol


def _sorted_lines(lines: Sequence[dict]) -> List[dict]:
    return sorted(
        list(lines or []),
        key=lambda ln: (ln.get("sequence") is None, ln.get("sequence") or 0),
    )


def _public_line(ln: dict) -> dict:
    item = (ln.get("lineObjectNumber") or None) or None
    if item is not None:
        item = str(item).strip() or None
    line_type = ln.get("lineType")
    panel = classify_line({
        "lineType": line_type,
        "lineObjectNumber": item or "",
        "description": ln.get("description") or "",
    })
    return {
        "id": ln.get("id"),
        "sequence": ln.get("sequence"),
        "line_type": line_type,
        "item_number": item,
        "description": ln.get("description") or "",
        "quantity": _f(ln.get("quantity")),
        "unit_cost": _f(ln.get("directUnitCost")),
        "unit_of_measure": ln.get("unitOfMeasureCode") or None,
        "location_id": ln.get("locationId") or None,
        "received_quantity": _f(ln.get("receivedQuantity")),
        "description_2": ln.get("description2") or None,
        "drop_shipment": ln.get("dropShipment"),
        "special_order": ln.get("specialOrder"),
        "sales_order_id": ln.get("salesOrderId"),
        "sales_order_line_id": ln.get("salesOrderLineId"),
        "panel_class": panel,
    }


def _result(
    po: dict,
    lines: Sequence[dict],
    *,
    dry_run: bool = False,
    changed: bool = True,
    current_lines: Optional[Sequence[dict]] = None,
) -> dict:
    body = {
        "bc_po_number": po.get("number"),
        "bc_po_id": po.get("id"),
        "status": po.get("status"),
        "dry_run": dry_run,
        "changed": changed,
        "lines": [_public_line(ln) for ln in _sorted_lines(lines)],
    }
    if current_lines is not None:
        body["current_lines"] = [_public_line(ln) for ln in _sorted_lines(current_lines)]
    return body


def _snapshot_log(number: str, lines: Sequence[dict], phase: str) -> None:
    try:
        payload = json.dumps(list(lines), default=str)
    except TypeError:
        payload = repr(lines)
    if len(payload) > 12000:
        payload = payload[:12000] + "…(truncated)"
    logger.info("Draft PO %s line snapshot (%s, %d lines): %s", number, phase, len(list(lines)), payload)


def _not_draft_message(number: str, status: str) -> str:
    shown = status or "unknown"
    return (
        f"{number} is status {shown!r}, not Draft. "
        "The portal only edits Draft purchase orders (open, not released). "
        "A Released or Open PO has already gone to the vendor and is not reopened here."
    )


class DraftPoLinesService:
    def get_lines(self, kind: str, value: str) -> dict:
        po = self._load_editable(kind, value)
        return _result(po, po.get("purchaseOrderLines") or [], dry_run=False, changed=False)

    def update_line(self, kind: str, value: str, line_id: str, changes: dict, *, actor: str = "") -> dict:
        po = self._load_editable(kind, value)
        line = self._find_line(po, line_id)
        patch = self._patch_from_changes(line, changes)
        if not patch:
            raise DraftPoEditError(400, "No line changes were provided")
        logger.info(
            "Admin %s updating Draft PO %s line %s: %s",
            actor or "?", po.get("number"), line_id, patch,
        )
        try:
            bc_client.update_purchase_order_line(po["id"], line_id, patch)
        except requests.HTTPError as exc:
            raise DraftPoEditError(502, f"Business Central rejected the line update: {exc}") from exc
        fresh = self._reload(po)
        return _result(fresh, fresh.get("purchaseOrderLines") or [], changed=True)

    def delete_line(self, kind: str, value: str, line_id: str, *, actor: str = "") -> dict:
        po = self._load_editable(kind, value)
        self._find_line(po, line_id)
        logger.info("Admin %s deleting Draft PO %s line %s", actor or "?", po.get("number"), line_id)
        try:
            bc_client.delete_purchase_order_line(po["id"], line_id)
        except requests.HTTPError as exc:
            raise DraftPoEditError(502, f"Business Central rejected the line delete: {exc}") from exc
        fresh = self._reload(po)
        return _result(fresh, fresh.get("purchaseOrderLines") or [], changed=True)

    def add_line(self, kind: str, value: str, body: dict, *, actor: str = "") -> dict:
        po = self._load_editable(kind, value)
        payload = self._create_payload(po, body)
        logger.info(
            "Admin %s adding %s line on Draft PO %s: %s",
            actor or "?", payload.get("lineType"), po.get("number"), payload,
        )
        try:
            bc_client.add_purchase_order_line(po["id"], payload)
        except requests.HTTPError as exc:
            raise DraftPoEditError(502, f"Business Central rejected the new line: {exc}") from exc
        fresh = self._reload(po)
        return _result(fresh, fresh.get("purchaseOrderLines") or [], changed=True)

    def reorder_lines(self, kind: str, value: str, line_ids: Sequence[str], *, actor: str = "") -> dict:
        po = self._load_editable(kind, value)
        current = _sorted_lines(po.get("purchaseOrderLines") or [])
        by_id = {str(ln.get("id")): ln for ln in current}
        wanted = [str(line_id) for line_id in line_ids]
        if len(wanted) != len(set(wanted)) or set(wanted) != set(by_id):
            raise DraftPoEditError(
                400,
                "line_ids must list every current line id on the purchase order exactly once",
            )
        ordered = [by_id[line_id] for line_id in wanted]
        if same_line_order(current, ordered):
            return _result(po, current, changed=False)
        logger.info(
            "Admin %s reordering Draft PO %s (%d lines)",
            actor or "?", po.get("number"), len(ordered),
        )
        fresh_lines = self._rewrite(po, ordered, reason="reorder")
        fresh = self._reload(po)
        return _result(fresh, fresh_lines, changed=True)

    def normalize_order(self, kind: str, value: str, *, dry_run: bool = True, actor: str = "") -> dict:
        """Panels-first order. ``dry_run`` returns the proposal and does not write."""
        po = self._load_editable(kind, value)
        current = _sorted_lines(po.get("purchaseOrderLines") or [])
        # Stamp a new sequence so the response lists the proposal in the new
        # order. The copies still carry the original ids; nothing is written
        # until dry_run is false.
        proposed = []
        for index, line in enumerate(order_po_lines(current)):
            stamped = dict(line)
            stamped["sequence"] = (index + 1) * 10000
            proposed.append(stamped)
        changed = not same_line_order(current, proposed)
        if dry_run or not changed:
            return _result(
                po,
                proposed,
                dry_run=dry_run,
                changed=changed,
                current_lines=current,
            )
        logger.info(
            "Admin %s normalizing Draft PO %s to panels-first order (%d lines)",
            actor or "?", po.get("number"), len(proposed),
        )
        fresh_lines = self._rewrite(po, proposed, reason="normalize-order")
        fresh = self._reload(po)
        return _result(fresh, fresh_lines, dry_run=False, changed=True, current_lines=current)

    # ── load / validate ────────────────────────────────────────

    def _load_editable(self, kind: str, value: str) -> dict:
        try:
            if kind == "guid":
                po = bc_client.get_purchase_order_with_lines(value)
            else:
                po = bc_client.get_purchase_order_by_number(value)
        except requests.HTTPError as exc:
            bc_status = getattr(getattr(exc, "response", None), "status_code", None)
            if bc_status == 404:
                raise DraftPoEditError(404, f"Purchase order {value} not found in Business Central") from exc
            raise DraftPoEditError(
                502, f"Failed to look up purchase order {value} in Business Central: {exc}",
            ) from exc
        if not po:
            raise DraftPoEditError(404, f"Purchase order {value} not found in Business Central")
        number = po.get("number") or value
        status = po.get("status") or ""
        if status.lower() != "draft":
            raise DraftPoEditError(422, _not_draft_message(number, status))
        received = sum(
            _f(ln.get("receivedQuantity"))
            for ln in (po.get("purchaseOrderLines") or [])
        )
        if received > 0:
            raise DraftPoEditError(
                422,
                f"{number} already has received quantity ({received:g}). "
                "Draft line edits are refused once anything has been received.",
            )
        if not po.get("id"):
            raise DraftPoEditError(502, f"Business Central returned {number} without an id")
        return po

    def _reload(self, po: dict) -> dict:
        fresh = bc_client.get_purchase_order_with_lines(po["id"])
        if not fresh:
            raise DraftPoEditError(502, f"Business Central did not return {po.get('number')} after the edit")
        return fresh

    @staticmethod
    def _find_line(po: dict, line_id: str) -> dict:
        for ln in po.get("purchaseOrderLines") or []:
            if str(ln.get("id")) == str(line_id):
                return ln
        number = po.get("number") or po.get("id")
        raise DraftPoEditError(404, f"Line {line_id} is not on {number}")

    def _patch_from_changes(self, line: dict, changes: dict) -> dict:
        if not changes:
            raise DraftPoEditError(400, "No line changes were provided")
        comment = (line.get("lineType") or "").lower() == "comment"
        patch: Dict[str, Any] = {}
        if "description" in changes and changes["description"] is not None:
            patch["description"] = self._description(changes["description"], required=comment)
        if "quantity" in changes and changes["quantity"] is not None:
            qty = self._quantity(changes["quantity"], comment=comment)
            if not comment:
                patch["quantity"] = qty
        if "unit_cost" in changes and changes["unit_cost"] is not None:
            if comment:
                raise DraftPoEditError(400, "Comment lines do not have a unit cost")
            patch["directUnitCost"] = self._cost(changes["unit_cost"])
        if "item_no" in changes and changes["item_no"] is not None:
            if comment:
                raise DraftPoEditError(400, "Comment lines do not have an item number")
            item = str(changes["item_no"]).strip()
            if not item:
                raise DraftPoEditError(400, "Item number is required")
            patch["lineObjectNumber"] = item
        return patch

    def _create_payload(self, po: dict, body: dict) -> dict:
        raw_type = body.get("line_type", body.get("lineType", "Item"))
        comment = str(raw_type if raw_type is not None else "Item").strip().lower() in ("", "comment", "blank")
        lines = po.get("purchaseOrderLines") or []
        seqs = [int(_f(ln.get("sequence"))) for ln in lines]
        sequence = (max(seqs) if seqs else 0) + 10000
        if comment:
            return {
                "sequence": sequence,
                "lineType": "Comment",
                "description": self._description(body.get("description"), required=True),
            }
        item = str(body.get("item_no") or body.get("lineObjectNumber") or "").strip()
        if not item:
            raise DraftPoEditError(400, "Item lines need an item number")
        payload: Dict[str, Any] = {
            "sequence": sequence,
            "lineType": "Item",
            "lineObjectNumber": item,
            "quantity": self._quantity(body.get("quantity"), comment=False),
            "directUnitCost": self._cost(body.get("unit_cost", 0)),
        }
        description = body.get("description")
        if description:
            payload["description"] = self._description(description, required=False)
        uom = body.get("unit_of_measure") or body.get("unitOfMeasureCode")
        if uom:
            payload["unitOfMeasureCode"] = str(uom).strip()
        return payload

    @staticmethod
    def _description(value: Any, *, required: bool) -> str:
        text = str(value or "").strip()
        if required and not text:
            raise DraftPoEditError(400, "Comment lines need a description")
        if len(text) > BC_DESCRIPTION_MAX:
            raise DraftPoEditError(
                400,
                f"Description is {len(text)} characters. Business Central allows {BC_DESCRIPTION_MAX}.",
            )
        return text

    @staticmethod
    def _quantity(value: Any, *, comment: bool) -> float:
        if comment:
            return 0.0
        qty = _f(value)
        if qty <= 0:
            raise DraftPoEditError(400, "Item quantity must be greater than zero")
        return qty

    @staticmethod
    def _cost(value: Any) -> float:
        cost = _f(value)
        if cost < 0:
            raise DraftPoEditError(400, "Unit cost cannot be negative")
        return cost

    # ── rebuild ────────────────────────────────────────────────

    def _rewrite(self, po: dict, ordered: Sequence[dict], *, reason: str) -> List[dict]:
        """Delete every line and re-add ``ordered``. Roll back to the snapshot on failure."""
        number = po.get("number") or po.get("id")
        po_id = po["id"]
        snapshot = _sorted_lines(po.get("purchaseOrderLines") or [])
        _snapshot_log(number, snapshot, f"before {reason}")
        deleted = 0
        added = 0
        try:
            for line in snapshot:
                bc_client.delete_purchase_order_line(po_id, line["id"])
                deleted += 1
            for index, src in enumerate(ordered):
                bc_client.add_purchase_order_line(po_id, _rebuild_payload(src, (index + 1) * 10000))
                added += 1
            fresh = self._reload(po)
            fresh_lines = fresh.get("purchaseOrderLines") or []
            problems = _verify(ordered, fresh_lines)
            if problems:
                raise RuntimeError("verification failed: " + "; ".join(problems))
            logger.info("Draft PO %s line %s verified (%d lines)", number, reason, len(fresh_lines))
            return fresh_lines
        except DraftPoEditError:
            raise
        except Exception as exc:
            logger.error(
                "Draft PO %s line %s failed after deleting %d and adding %d: %s",
                number, reason, deleted, added, exc,
                exc_info=True,
            )
            if deleted == 0 and added == 0:
                raise DraftPoEditError(
                    502, f"Business Central refused to rewrite lines on {number}: {exc}",
                ) from exc
            rollback_ok = False
            try:
                rollback_ok = self._rollback(po_id, snapshot)
            except Exception:
                logger.exception("Draft PO %s line rollback itself failed", number)
                rollback_ok = False
            _snapshot_log(number, snapshot, "rollback source" if rollback_ok else "ROLLBACK FAILED")
            if rollback_ok:
                detail = (
                    f"Rewriting lines on {number} failed ({exc}). "
                    "The previous lines were restored."
                )
            else:
                detail = (
                    f"Rewriting lines on {number} failed ({exc}), and restoring the "
                    "previous lines also failed. The line snapshot is in the server log. "
                    "Do not release this PO until the lines are checked."
                )
            raise DraftPoEditError(502, detail) from exc

    def _rollback(self, po_id: str, snapshot: Sequence[dict]) -> bool:
        """Replace whatever is on the PO now with ``snapshot``, in the original order."""
        current = bc_client.get_purchase_order_with_lines(po_id)
        for line in current.get("purchaseOrderLines") or []:
            bc_client.delete_purchase_order_line(po_id, line["id"])
        for index, src in enumerate(snapshot):
            bc_client.add_purchase_order_line(po_id, _rebuild_payload(src, (index + 1) * 10000))
        fresh = bc_client.get_purchase_order_with_lines(po_id)
        problems = _verify(snapshot, fresh.get("purchaseOrderLines") or [])
        if problems:
            logger.error("Draft PO %s rollback verification failed: %s", po_id, "; ".join(problems))
            return False
        logger.warning("Draft PO %s lines restored from snapshot (%d lines)", po_id, len(snapshot))
        return True


def _rebuild_payload(src: dict, sequence: int) -> dict:
    """POST body that preserves the snapshot line's purchasable fields."""
    line_type = src.get("lineType") or "Item"
    if str(line_type).lower() == "comment" or is_comment_line(src):
        description = str(src.get("description") or "").strip()[:BC_DESCRIPTION_MAX]
        return {"sequence": sequence, "lineType": "Comment", "description": description}

    payload: Dict[str, Any] = {"sequence": sequence, "lineType": line_type or "Item"}
    item = src.get("lineObjectNumber")
    if item:
        payload["lineObjectNumber"] = item
    description = src.get("description")
    if description:
        payload["description"] = str(description).strip()[:BC_DESCRIPTION_MAX]
    description2 = src.get("description2")
    if description2:
        payload["description2"] = str(description2)
    uom = src.get("unitOfMeasureCode")
    if uom:
        payload["unitOfMeasureCode"] = uom
    if src.get("quantity") is not None:
        payload["quantity"] = _f(src.get("quantity"))
    if src.get("directUnitCost") is not None:
        payload["directUnitCost"] = _f(src.get("directUnitCost"))
    location = src.get("locationId")
    if location:
        payload["locationId"] = location
    for key in _LINKAGE_FIELDS:
        if key in src and src.get(key) is not None:
            payload[key] = src.get(key)
    return payload


def _verify(expected: Sequence[dict], fresh: Sequence[dict]) -> List[str]:
    """Differences between the lines we meant to write and what BC returned.

    Text and item numbers are compared case-insensitively. Quantity and cost
    use a small tolerance. Linkage fields are checked only when we sent them.
    """
    got = _sorted_lines(fresh)
    problems: List[str] = []
    if len(got) != len(expected):
        problems.append(f"expected {len(expected)} lines, Business Central has {len(got)}")
        return problems
    for index, (src, line) in enumerate(zip(expected, got), start=1):
        payload = _rebuild_payload(src, index * 10000)
        prefix = f"line {index}"
        if (line.get("lineType") or "").lower() != (payload.get("lineType") or "").lower():
            problems.append(f"{prefix} type {line.get('lineType')!r} != {payload.get('lineType')!r}")
            continue
        if (payload.get("lineType") or "").lower() == "comment":
            if (line.get("description") or "").strip().casefold() != (payload.get("description") or "").casefold():
                problems.append(f"{prefix} description mismatch")
            continue
        got_item = (line.get("lineObjectNumber") or "").strip().casefold()
        want_item = (payload.get("lineObjectNumber") or "").strip().casefold()
        if got_item != want_item:
            problems.append(f"{prefix} item {line.get('lineObjectNumber')!r} != {payload.get('lineObjectNumber')!r}")
        if "quantity" in payload and not _close(line.get("quantity"), payload["quantity"]):
            problems.append(f"{prefix} quantity {line.get('quantity')!r} != {payload['quantity']!r}")
        if "directUnitCost" in payload and not _close(line.get("directUnitCost"), payload["directUnitCost"]):
            problems.append(f"{prefix} unit cost {line.get('directUnitCost')!r} != {payload['directUnitCost']!r}")
        if payload.get("description"):
            if (line.get("description") or "").strip().casefold() != payload["description"].strip().casefold():
                problems.append(f"{prefix} description mismatch")
        if payload.get("unitOfMeasureCode"):
            if (line.get("unitOfMeasureCode") or "").strip().casefold() != str(payload["unitOfMeasureCode"]).strip().casefold():
                problems.append(f"{prefix} unit of measure mismatch")
        if payload.get("locationId") and (line.get("locationId") or "") != payload["locationId"]:
            problems.append(f"{prefix} location was not preserved")
        for key in _LINKAGE_FIELDS:
            if key in payload and line.get(key) != payload[key]:
                problems.append(f"{prefix} {key} was not preserved")
    return problems


draft_po_lines_service = DraftPoLinesService()
