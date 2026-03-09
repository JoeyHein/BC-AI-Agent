"""
PO Generation Agent Service
Reads demand signals, builds PO drafts, handles approval workflow.
30-day draft-only period before auto-approve is possible.
"""

import logging
import uuid
from datetime import datetime
from typing import Dict, List, Optional
from collections import defaultdict

from sqlalchemy.orm import Session

from app.db.models import (
    DemandSignal, POAgentLog, Part, AppSettings,
)
from app.integrations.bc.client import bc_client

logger = logging.getLogger(__name__)


class POAgentService:
    """Generates PO drafts from demand signals."""

    def run_po_generation(self, db: Session) -> dict:
        """
        Run PO generation:
        1. Query unresolved demand signals (acknowledged but no PO yet)
        2. Group by vendor
        3. Calculate quantities
        4. Create po_agent_log entries as DRAFTs
        """
        run_id = uuid.uuid4().hex[:12]
        logger.info(f"[POAgent] Starting PO generation run {run_id}")

        stats = {
            "run_id": run_id,
            "signals_processed": 0,
            "drafts_created": 0,
            "vendors": 0,
            "mode": self._get_mode(db),
            "errors": [],
        }

        # Get acknowledged but unlinked demand signals
        signals = db.query(DemandSignal).filter(
            DemandSignal.is_acknowledged == True,
            DemandSignal.linked_po_id == None,
        ).all()

        if not signals:
            logger.info("[POAgent] No unlinked demand signals to process")
            return stats

        stats["signals_processed"] = len(signals)

        # Group by vendor
        vendor_groups: Dict[str, List[DemandSignal]] = defaultdict(list)
        for signal in signals:
            vendor = signal.recommended_vendor or "Unknown Vendor"
            vendor_groups[vendor].append(signal)

        stats["vendors"] = len(vendor_groups)

        # Create PO drafts per vendor
        for vendor_name, vendor_signals in vendor_groups.items():
            line_items = []
            total = 0.0
            signal_ids = []

            for s in vendor_signals:
                # Look up part for unit cost
                unit_cost = 0
                part = db.query(Part).filter(Part.bc_item_number == s.bc_item_number).first()
                if part and part.unit_cost:
                    unit_cost = float(part.unit_cost)

                qty = s.recommended_qty or 1
                line_total = unit_cost * qty

                line_items.append({
                    "bc_item_number": s.bc_item_number,
                    "description": part.bc_description if part else s.bc_item_number,
                    "quantity": qty,
                    "unit_cost": unit_cost,
                    "line_total": round(line_total, 2),
                })
                total += line_total
                signal_ids.append(s.id)

            # Look up vendor_id from BC if available
            vendor_id = None
            if part and part.vendor_id:
                vendor_id = part.vendor_id

            po_draft = POAgentLog(
                vendor_id=vendor_id,
                vendor_name=vendor_name,
                status="draft",
                total_amount=round(total, 2),
                currency="CAD",
                line_items=line_items,
                demand_signal_ids=signal_ids,
                po_run_id=run_id,
                created_at=datetime.utcnow(),
            )
            db.add(po_draft)
            db.flush()

            # Link signals to this PO draft
            for s in vendor_signals:
                s.linked_po_id = po_draft.id

            stats["drafts_created"] += 1

        db.flush()
        logger.info(f"[POAgent] Run {run_id} complete: {stats}")
        return stats

    def approve_po(self, db: Session, po_id: int, user_id: int) -> POAgentLog:
        """Approve a PO draft and optionally submit to BC."""
        po = db.query(POAgentLog).get(po_id)
        if not po:
            raise ValueError(f"PO draft {po_id} not found")
        if po.status != "draft":
            raise ValueError(f"PO {po_id} is not in draft status (current: {po.status})")

        po.status = "approved"
        po.approved_by = user_id
        po.approved_at = datetime.utcnow()

        # Try to create in BC
        try:
            bc_po = self._create_bc_purchase_order(po)
            if bc_po:
                po.bc_po_id = bc_po.get("id")
                po.bc_po_number = bc_po.get("number")
                po.status = "submitted"
                po.submitted_at = datetime.utcnow()
                logger.info(f"[POAgent] PO {po_id} submitted to BC as {po.bc_po_number}")
        except Exception as e:
            logger.error(f"[POAgent] Failed to submit PO {po_id} to BC: {e}")
            po.status = "approved"  # Keep as approved even if BC submission fails

        db.flush()
        return po

    def reject_po(self, db: Session, po_id: int, user_id: int, reason: str = None) -> POAgentLog:
        """Reject a PO draft."""
        po = db.query(POAgentLog).get(po_id)
        if not po:
            raise ValueError(f"PO draft {po_id} not found")

        po.status = "rejected"
        po.rejected_by = user_id
        po.rejected_at = datetime.utcnow()
        po.rejection_reason = reason

        # Unlink signals so they can be picked up again
        if po.demand_signal_ids:
            for signal_id in po.demand_signal_ids:
                signal = db.query(DemandSignal).get(signal_id)
                if signal:
                    signal.linked_po_id = None

        db.flush()
        return po

    def _create_bc_purchase_order(self, po: POAgentLog) -> Optional[dict]:
        """Create a purchase order in BC."""
        try:
            po_data = {
                "vendorNumber": po.vendor_id or "",
                "vendorName": po.vendor_name,
            }
            bc_po = bc_client.create_purchase_order(po_data)

            # Add line items
            if bc_po and bc_po.get("id"):
                for line in po.line_items:
                    line_data = {
                        "lineType": "Item",
                        "lineObjectNumber": line["bc_item_number"],
                        "description": line.get("description", ""),
                        "quantity": line["quantity"],
                        "directUnitCost": line["unit_cost"],
                    }
                    bc_client.add_purchase_order_line(bc_po["id"], line_data)

            return bc_po
        except Exception as e:
            logger.error(f"[POAgent] BC PO creation failed: {e}")
            raise

    def _get_mode(self, db: Session) -> str:
        """Get current PO agent mode from settings."""
        setting = db.query(AppSettings).filter(
            AppSettings.setting_key == "po_agent_mode"
        ).first()
        if setting and setting.setting_value:
            return str(setting.setting_value)
        return "draft_only"

    # ─── QUERY HELPERS ─────────────────────────────────────────

    def get_drafts(self, db: Session, status_filter: Optional[str] = None,
                   skip: int = 0, limit: int = 50) -> List[POAgentLog]:
        """List PO drafts."""
        q = db.query(POAgentLog)
        if status_filter:
            q = q.filter(POAgentLog.status == status_filter)
        return q.order_by(POAgentLog.created_at.desc()).offset(skip).limit(limit).all()

    def get_stats(self, db: Session) -> dict:
        """Approval rate history and stats."""
        total = db.query(POAgentLog).count()
        approved = db.query(POAgentLog).filter(POAgentLog.status.in_(["approved", "submitted"])).count()
        rejected = db.query(POAgentLog).filter(POAgentLog.status == "rejected").count()
        drafts = db.query(POAgentLog).filter(POAgentLog.status == "draft").count()

        approval_rate = (approved / (approved + rejected) * 100) if (approved + rejected) > 0 else 0

        # Check draft-only period
        draft_only_setting = db.query(AppSettings).filter(
            AppSettings.setting_key == "po_agent_draft_only_until"
        ).first()
        draft_only_until = None
        if draft_only_setting and draft_only_setting.setting_value:
            draft_only_until = str(draft_only_setting.setting_value)

        return {
            "total_pos": total,
            "drafts": drafts,
            "approved": approved,
            "rejected": rejected,
            "approval_rate": round(approval_rate, 1),
            "mode": self._get_mode(db),
            "draft_only_until": draft_only_until,
        }


# Global instance
po_agent_service = POAgentService()
