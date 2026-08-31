"""
Nightly auto-PO drafting.

Once a night the job looks at what has landed in open sales orders since the
last run and, for the material that a *preferred* vendor supplies, drafts a
purchase order straight into Business Central — in **Draft** status, never
emailed. A human reviews and releases each one in BC in the morning.

Scope is deliberately narrow:

  * Only NEW committed demand. A per-SO-line watermark (AutoPoSnapshot) means
    a line is drafted for once and not again unless its quantity grows.
  * Only PREFERRED vendors (UPW / LYNX / ELT). Expedite vendors are never
    auto-selected; unassigned and non-preferred items fall through to the
    digest for manual buying.
  * Only PURCHASED items. Anything BC marks Replenishment_System = "Prod.
    Order" (built in-house) is skipped — the auto path must not buy a panel
    we manufacture.
  * Every part number comes verbatim off a sales-order line, so there is no
    SKU guessing. Stock / reorder-point replenishment is out of scope here.

Each drafted PO carries comment lines naming the sales orders it is
allocated to, and the same allocation is stored on POAgentLog.so_allocations
so the production schedule can show "this SO has a PO" (po_so_link_service).

The demand-engine net_need is used as a ceiling on every line, so on-hand
stock and POs already open in BC are still netted out — the watermark only
decides *which* demand is new, never how much to buy past the real shortfall.
"""

import logging
from collections import defaultdict
from datetime import date, datetime
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import AutoPoSnapshot, POAgentLog
from app.integrations.bc.client import bc_client
from app.services.bc_production_service import bc_production_service
from app.services.purchasing_demand_service import (
    purchasing_demand_service,
    NON_STOCK_ITEMS,
)
from app.services.vendor_map_service import vendor_map_service
from app.services.vendor_policy import is_preferred, is_expedite

logger = logging.getLogger(__name__)

# PO statuses that still consume demand (an allocation on one of these already
# covers the sales order line, so don't draft against it again).
_LIVE_PO_STATUSES = {"submitted", "approved", "draft", "auto_draft"}

# Skip reasons surfaced to the digest so a human knows what still needs a
# manual PO.
SKIP_MANUFACTURED = "manufactured"      # built in-house — needs a production order
SKIP_UNASSIGNED = "unassigned_vendor"   # no vendor mapped
SKIP_EXPEDITE = "expedite_vendor"       # DEK / UPAM — never auto-ordered
SKIP_NON_PREFERRED = "non_preferred_vendor"
SKIP_COVERED = "already_covered"        # stock / existing PO already covers it
SKIP_NO_COST = "no_unit_cost"           # can't price the line


class AutoPoService:
    def run(
        self,
        db: Session,
        *,
        dry_run: bool = False,
        created_by: Optional[int] = None,
        horizon_weeks: Optional[int] = None,
    ) -> dict:
        """Draft POs for new preferred-vendor demand. Returns a summary dict.

        dry_run=True computes everything and touches neither BC nor the
        snapshot — used by the preview endpoint and tests.
        """
        run_id = f"AUTO-{datetime.utcnow():%Y%m%dT%H%M%S}"
        horizon_weeks = horizon_weeks or settings.AUTO_PO_HORIZON_WEEKS

        # 1. Authoritative shortfall picture (nets on-hand + open BC POs).
        req = purchasing_demand_service.compute_requirements(
            db, include_met=False, horizon_weeks=horizon_weeks
        )
        net_need: Dict[str, float] = {
            r["item_no"]: r["net_need"] for r in req["items"] if r["net_need"] > 0
        }
        row_by_item: Dict[str, dict] = {r["item_no"]: r for r in req["items"]}

        # 2. Diff live open-SO lines against the watermark → new demand per line.
        live_lines = self._live_so_lines(horizon_weeks)
        snap: Dict[Tuple[str, int], AutoPoSnapshot] = {
            (s.so_number, s.sequence): s for s in db.query(AutoPoSnapshot).all()
        }
        seen_keys: set = set()
        # item_no -> list of (so_number, sequence, new_qty)
        new_by_item: Dict[str, List[Tuple[str, int, float]]] = defaultdict(list)
        for so_no, seq, item_no, outstanding, _rdd in live_lines:
            seen_keys.add((so_no, seq))
            prev = snap.get((so_no, seq))
            covered = prev.covered_qty if prev else 0.0
            new_qty = round(outstanding - covered, 4)
            if new_qty > 0 and item_no:
                new_by_item[item_no].append((so_no, seq, new_qty))

        # 3. What our own earlier drafts already allocated (second guard, and
        #    covers snapshot loss / manual tool POs).
        prior_alloc = self._prior_allocation_by_item(db)

        replen = self._replenishment_map()
        vendor_map = vendor_map_service.load_map(db)

        # 4. Decide per item how much to draft and for which SOs.
        vendor_lines: Dict[str, dict] = {}   # vendor_no -> {name, lines[], sos:set}
        skips: Dict[str, List[dict]] = defaultdict(list)
        pending_cover: Dict[Tuple[str, int], float] = defaultdict(float)

        for item_no, contribs in new_by_item.items():
            total_new = round(sum(c[2] for c in contribs), 4)
            if item_no.upper() in NON_STOCK_ITEMS:
                continue

            meta_row = row_by_item.get(item_no, {})
            desc = meta_row.get("description") or ""

            # ceiling: real shortfall minus what our earlier drafts already took
            ceiling = round(net_need.get(item_no, 0.0) - prior_alloc.get(item_no, 0.0), 4)
            grant = min(total_new, max(0.0, ceiling))
            if grant <= 0:
                skips[SKIP_COVERED].append({"item_no": item_no, "description": desc,
                                            "new_demand": total_new})
                continue

            if str(replen.get(item_no) or "").lower().startswith("prod"):
                skips[SKIP_MANUFACTURED].append({"item_no": item_no, "description": desc,
                                                 "new_demand": total_new})
                continue

            vinfo = vendor_map.get(item_no, {})
            vno = (vinfo.get("vendor_no") or "").upper()
            vname = vinfo.get("vendor_name") or ""
            if not vno:
                skips[SKIP_UNASSIGNED].append({"item_no": item_no, "description": desc,
                                               "new_demand": total_new})
                continue
            if is_expedite(vno):
                skips[SKIP_EXPEDITE].append({"item_no": item_no, "description": desc,
                                             "new_demand": total_new, "vendor_no": vno})
                continue
            if not is_preferred(vno):
                skips[SKIP_NON_PREFERRED].append({"item_no": item_no, "description": desc,
                                                  "new_demand": total_new, "vendor_no": vno})
                continue

            unit_cost = self._unit_cost(meta_row)
            if unit_cost <= 0:
                skips[SKIP_NO_COST].append({"item_no": item_no, "description": desc,
                                            "new_demand": total_new, "vendor_no": vno})
                continue

            # distribute the granted qty across the contributing SO lines
            remaining = grant
            per_so: Dict[str, float] = defaultdict(float)
            for so_no, seq, qty in sorted(contribs, key=lambda c: (c[0], c[1])):
                take = round(min(remaining, qty), 4)
                if take <= 0:
                    break
                remaining -= take
                per_so[so_no] += take
                pending_cover[(so_no, seq)] += take

            bucket = vendor_lines.setdefault(vno, {"vendor_name": vname, "lines": [], "sos": set()})
            bucket["lines"].append({
                "item_no": item_no,
                "description": desc,
                "quantity": round(grant, 2),
                "unit_cost": round(unit_cost, 4),
                "unit_of_measure": meta_row.get("unit_of_measure") or "EA",
                "per_so": {k: round(v, 2) for k, v in per_so.items()},
            })
            bucket["sos"].update(per_so.keys())

        # 5. Create the draft POs (or, on dry-run, just describe them).
        drafted: List[dict] = []
        errors: List[dict] = []
        for vno, bucket in sorted(vendor_lines.items()):
            plan = {
                "vendor_no": vno,
                "vendor_name": bucket["vendor_name"],
                "sales_orders": sorted(bucket["sos"]),
                "lines": bucket["lines"],
                "estimated_cost": round(
                    sum(l["quantity"] * l["unit_cost"] for l in bucket["lines"]), 2
                ),
            }
            if dry_run:
                drafted.append({**plan, "dry_run": True})
                continue
            try:
                created = self._create_bc_draft_po(db, plan, run_id, created_by)
                drafted.append(created)
            except Exception as e:  # one vendor failing must not sink the rest
                logger.error(f"[AutoPO] draft failed for {vno}: {e}", exc_info=True)
                errors.append({"vendor_no": vno, "error": str(e)})

        # 6. Advance the watermark (real runs only).
        if not dry_run:
            self._update_snapshot(db, live_lines, seen_keys, pending_cover, run_id)
            db.flush()

        summary = {
            "run_id": run_id,
            "dry_run": dry_run,
            "horizon_weeks": horizon_weeks,
            "generated_at": datetime.utcnow().isoformat(),
            "drafted_po_count": len([d for d in drafted if not d.get("dry_run")]) if not dry_run else len(drafted),
            "drafted_line_count": sum(len(d["lines"]) for d in drafted),
            "drafted_est_cost": round(sum(d.get("estimated_cost", 0) for d in drafted), 2),
            "vendors": [d.get("vendor_name") or d.get("vendor_no") for d in drafted],
            "skipped": {reason: rows for reason, rows in skips.items()},
            "skipped_counts": {reason: len(rows) for reason, rows in skips.items()},
            "errors": errors,
            "drafts": drafted,
        }
        logger.info(
            f"[AutoPO] {run_id} dry_run={dry_run}: {summary['drafted_po_count']} PO(s), "
            f"{summary['drafted_line_count']} line(s), ~${summary['drafted_est_cost']:,.0f}; "
            f"skipped {summary['skipped_counts']}"
        )
        return summary

    def seed_snapshot(self, db: Session, horizon_weeks: Optional[int] = None) -> dict:
        """Mark every currently-open SO line as already covered WITHOUT
        drafting anything. Run once before enabling the nightly job so the
        first live run only acts on orders that land afterwards, not the
        whole current backlog."""
        horizon_weeks = horizon_weeks or settings.AUTO_PO_HORIZON_WEEKS
        run_id = f"SEED-{datetime.utcnow():%Y%m%dT%H%M%S}"
        now = datetime.utcnow()
        live_lines = self._live_so_lines(horizon_weeks)
        existing = {(s.so_number, s.sequence): s for s in db.query(AutoPoSnapshot).all()}
        for so_no, seq, item_no, outstanding, _rdd in live_lines:
            row = existing.get((so_no, seq))
            if row is None:
                db.add(AutoPoSnapshot(
                    so_number=so_no, sequence=seq, item_no=item_no,
                    outstanding_seen=outstanding, covered_qty=outstanding,
                    first_seen_at=now, last_seen_at=now, last_run_id=run_id,
                ))
            else:  # bring covered up to the current outstanding, never down
                row.outstanding_seen = outstanding
                row.covered_qty = max(row.covered_qty, outstanding)
                row.last_seen_at = now
                row.last_run_id = run_id
        db.flush()
        return {"run_id": run_id, "lines_seeded": len(live_lines)}

    # ─── helpers ──────────────────────────────────────────────────────────

    def _live_so_lines(
        self, horizon_weeks: Optional[int]
    ) -> List[Tuple[str, int, str, float, str]]:
        """(so_number, sequence, item_no, outstanding_qty, requested_delivery)
        for every item line on an open SO within the delivery horizon. Mirrors
        the demand engine's horizon / non-stock filtering so the watermark and
        the shortfall picture agree on what counts."""
        from datetime import timedelta

        cutoff = (
            (date.today() + timedelta(weeks=horizon_weeks)).isoformat()
            if horizon_weeks else None
        )
        out: List[Tuple[str, int, str, float, str]] = []
        try:
            orders = bc_client.get_open_sales_orders_with_lines()
        except Exception as e:
            logger.error(f"[AutoPO] could not read open sales orders: {e}")
            return out
        for so in orders:
            so_no = so.get("number") or "?"
            rdd = (so.get("requestedDeliveryDate") or "")[:10]
            if cutoff and rdd and rdd > cutoff and rdd > "0001-01-01":
                continue
            for ln in so.get("salesOrderLines", []):
                if ln.get("lineType") != "Item":
                    continue
                item = ln.get("lineObjectNumber")
                if not item or item.upper() in NON_STOCK_ITEMS:
                    continue
                qty = float(ln.get("quantity") or 0)
                shipped = float(ln.get("shippedQuantity") or 0)
                outstanding = max(0.0, qty - shipped)
                if outstanding <= 0:
                    continue
                seq = int(ln.get("sequence") or ln.get("lineNumber") or 0)
                out.append((so_no, seq, item, outstanding, rdd))
        return out

    def _prior_allocation_by_item(self, db: Session) -> Dict[str, float]:
        """{item_no: qty} already allocated on our still-live PO drafts —
        so a second nightly run before the first is received doesn't double up,
        and neither does a snapshot reset."""
        out: Dict[str, float] = defaultdict(float)
        rows = (
            db.query(POAgentLog)
            .filter(POAgentLog.so_allocations.isnot(None))
            .all()
        )
        for r in rows:
            if (r.status or "").lower() not in _LIVE_PO_STATUSES:
                continue
            for _so, items in (r.so_allocations or {}).items():
                for it in items:
                    out[it.get("item_no")] += float(it.get("qty") or 0)
        return out

    def _replenishment_map(self) -> Dict[str, str]:
        try:
            return bc_production_service.get_replenishment_map()
        except Exception as e:
            logger.warning(f"[AutoPO] replenishment map unavailable ({e}); "
                           "not filtering manufactured items this run")
            return {}

    @staticmethod
    def _unit_cost(row: dict) -> float:
        """Price a line the way a buyer does: last price actually paid, then
        the item-card cost."""
        for key in ("last_purchase_cost", "unit_cost"):
            v = row.get(key)
            if v:
                return float(v)
        return 0.0

    def _create_bc_draft_po(
        self, db: Session, plan: dict, run_id: str, created_by: Optional[int]
    ) -> dict:
        today = date.today().isoformat()
        bc_po = bc_client.create_purchase_order({
            "vendorNumber": plan["vendor_no"],
            "vendorName": plan["vendor_name"],
        })
        bc_po_id = bc_po.get("id")
        bc_po_number = bc_po.get("number")
        bc_status = bc_po.get("status") or "Draft"
        if not bc_po_id:
            raise RuntimeError(f"BC returned no PO id: {bc_po}")

        # Header comment: which sales orders this PO is for.
        self._add_comment(
            bc_po_id,
            f"AUTO-PO {today} - allocated to: {', '.join(plan['sales_orders'])}",
        )
        self._add_comment(bc_po_id, f"Drafted by OPENDC purchasing ({run_id}). Review + release.")

        for ln in plan["lines"]:
            line_body = {
                "lineType": "Item",
                "lineObjectNumber": ln["item_no"],
                "quantity": ln["quantity"],
                "directUnitCost": ln["unit_cost"],
            }
            if ln.get("description"):
                line_body["description"] = str(ln["description"])[:100]
            bc_client.add_purchase_order_line(bc_po_id, line_body)
            alloc = ", ".join(f"{so} x{q:g}" for so, q in sorted(ln["per_so"].items()))
            self._add_comment(bc_po_id, f"  -> {ln['item_no']}: {alloc}")

        # so_allocations: {so_number: [{item_no, qty}]}
        so_alloc: Dict[str, List[dict]] = defaultdict(list)
        for ln in plan["lines"]:
            for so, q in ln["per_so"].items():
                so_alloc[so].append({"item_no": ln["item_no"], "qty": q})

        log = POAgentLog(
            vendor_id=plan["vendor_no"],
            vendor_name=plan["vendor_name"],
            status="submitted",
            bc_status=bc_status,
            is_auto=True,
            total_amount=plan["estimated_cost"],
            currency="CAD",
            line_items=[{
                "bc_item_number": ln["item_no"],
                "description": ln.get("description", ""),
                "quantity": ln["quantity"],
                "unit_cost": ln["unit_cost"],
                "line_total": round(ln["quantity"] * ln["unit_cost"], 2),
            } for ln in plan["lines"]],
            so_allocations=dict(so_alloc),
            demand_signal_ids=plan["sales_orders"],
            bc_po_id=bc_po_id,
            bc_po_number=bc_po_number,
            po_run_id=run_id,
            approved_by=created_by,
            submitted_at=datetime.utcnow(),
        )
        db.add(log)
        db.flush()

        return {
            "po_agent_log_id": log.id,
            "bc_po_id": bc_po_id,
            "bc_po_number": bc_po_number,
            "bc_status": bc_status,
            "vendor_no": plan["vendor_no"],
            "vendor_name": plan["vendor_name"],
            "sales_orders": plan["sales_orders"],
            "lines": plan["lines"],
            "estimated_cost": plan["estimated_cost"],
        }

    @staticmethod
    def _add_comment(bc_po_id: str, text: str) -> None:
        """Comment lines are how buyers already annotate POs here. Best-effort:
        if this BC tenant rejects Comment-type lines the PO + the stored
        allocation still stand."""
        try:
            bc_client.add_purchase_order_line(
                bc_po_id, {"lineType": "Comment", "description": text[:100]}
            )
        except Exception as e:
            logger.warning(f"[AutoPO] comment line rejected ({e}): {text!r}")

    def _update_snapshot(
        self,
        db: Session,
        live_lines: List[Tuple[str, int, str, float, str]],
        seen_keys: set,
        pending_cover: Dict[Tuple[str, int], float],
        run_id: str,
    ) -> None:
        now = datetime.utcnow()
        existing = {(s.so_number, s.sequence): s for s in db.query(AutoPoSnapshot).all()}
        for so_no, seq, item_no, outstanding, _rdd in live_lines:
            key = (so_no, seq)
            row = existing.get(key)
            add_cover = pending_cover.get(key, 0.0)
            if row is None:
                db.add(AutoPoSnapshot(
                    so_number=so_no, sequence=seq, item_no=item_no,
                    outstanding_seen=outstanding, covered_qty=add_cover,
                    first_seen_at=now, last_seen_at=now, last_run_id=run_id,
                ))
            else:
                row.item_no = item_no
                row.outstanding_seen = outstanding
                row.covered_qty = round(row.covered_qty + add_cover, 4)
                row.last_seen_at = now
                row.last_run_id = run_id
        # prune lines that fell off every open SO
        for key, row in existing.items():
            if key not in seen_keys:
                db.delete(row)


auto_po_service = AutoPoService()
