"""
Inventory Review Agent Service
Analyzes stock positions, calculates sales velocity, generates demand signals.
7-day observation period before recommending actions.
"""

import logging
import uuid
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import (
    Part, DemandSignal, SalesOrderLineItem, AppSettings,
)
from app.integrations.bc.client import bc_client

logger = logging.getLogger(__name__)

# Severity thresholds
CRITICAL_DAYS_OF_STOCK = 3
REORDER_DAYS_OF_STOCK = 14


class InventoryReviewService:
    """Analyzes stock and generates demand signals."""

    def run_review(self, db: Session) -> dict:
        """
        Run inventory review:
        1. Check observation period
        2. Fetch active parts
        3. Get BC inventory levels
        4. Calculate sales velocity from SalesOrderLineItem data
        5. Generate demand signals
        """
        run_id = uuid.uuid4().hex[:12]
        logger.info(f"[InventoryReview] Starting review run {run_id}")

        stats = {
            "run_id": run_id,
            "parts_reviewed": 0,
            "signals_created": 0,
            "critical_stockouts": 0,
            "reorder_needed": 0,
            "demand_signals": 0,
            "observation_mode": False,
            "errors": [],
        }

        # Check observation period
        observe_until = self._get_observe_until(db)
        if observe_until and datetime.utcnow() < observe_until:
            stats["observation_mode"] = True
            logger.info(f"[InventoryReview] In observation mode until {observe_until}")

        # Fetch active parts
        active_parts = db.query(Part).filter(
            Part.catalog_status == "active",
            Part.bc_item_number != None,
        ).all()

        if not active_parts:
            logger.info("[InventoryReview] No active parts to review")
            return stats

        stats["parts_reviewed"] = len(active_parts)

        # Get BC inventory levels for these items
        item_numbers = [p.bc_item_number for p in active_parts]
        bc_inventory = self._fetch_bc_inventory(item_numbers)

        # Calculate sales velocity
        velocity_map = self._calculate_sales_velocity(db, item_numbers)

        # Generate demand signals
        for part in active_parts:
            pn = part.bc_item_number
            stock = bc_inventory.get(pn, 0)
            daily_demand = velocity_map.get(pn, 0)

            if daily_demand <= 0:
                continue  # No demand history — skip

            days_of_stock = stock / daily_demand if daily_demand > 0 else 999

            signal_type = None
            severity = 5

            if stock <= 0 or days_of_stock <= CRITICAL_DAYS_OF_STOCK:
                signal_type = "critical_stockout"
                severity = 10
                stats["critical_stockouts"] += 1
            elif days_of_stock <= REORDER_DAYS_OF_STOCK:
                signal_type = "reorder_needed"
                severity = 7
                stats["reorder_needed"] += 1
            elif daily_demand > 0 and days_of_stock <= 30:
                signal_type = "demand_signal"
                severity = 4
                stats["demand_signals"] += 1

            if signal_type:
                # Skip creating if identical unacknowledged signal exists
                existing = db.query(DemandSignal).filter(
                    DemandSignal.bc_item_number == pn,
                    DemandSignal.signal_type == signal_type,
                    DemandSignal.is_acknowledged == False,
                ).first()
                if existing:
                    continue

                # Calculate recommended reorder quantity (30-day supply)
                recommended_qty = max(1, round(daily_demand * 30 - stock))

                signal = DemandSignal(
                    part_id=part.id,
                    bc_item_number=pn,
                    signal_type=signal_type,
                    severity=severity,
                    current_stock=stock,
                    reorder_point=round(daily_demand * REORDER_DAYS_OF_STOCK, 1),
                    avg_daily_demand=round(daily_demand, 3),
                    days_of_stock=round(days_of_stock, 1),
                    recommended_qty=recommended_qty,
                    recommended_vendor=part.vendor_name,
                    estimated_lead_time_days=part.lead_time_days,
                    review_run_id=run_id,
                    created_at=datetime.utcnow(),
                )
                db.add(signal)
                stats["signals_created"] += 1

        db.flush()
        logger.info(f"[InventoryReview] Run {run_id} complete: {stats}")
        return stats

    def _get_observe_until(self, db: Session) -> Optional[datetime]:
        """Get observation period end date from settings."""
        setting = db.query(AppSettings).filter(
            AppSettings.setting_key == "inventory_agent_observe_until"
        ).first()
        if setting and setting.setting_value:
            try:
                return datetime.fromisoformat(str(setting.setting_value))
            except (ValueError, TypeError):
                pass
        return None

    def _fetch_bc_inventory(self, item_numbers: List[str]) -> Dict[str, float]:
        """Fetch current inventory from BC for given items."""
        inventory = {}
        try:
            items_data = bc_client.get_items_by_numbers(item_numbers)
            for pn, data in items_data.items():
                inventory[pn] = data.get("inventory", 0)
        except Exception as e:
            logger.error(f"[InventoryReview] Failed to fetch BC inventory: {e}")
        return inventory

    def _calculate_sales_velocity(self, db: Session, item_numbers: List[str]) -> Dict[str, float]:
        """Calculate average daily demand from sales order line items (last 90 days)."""
        cutoff = datetime.utcnow() - timedelta(days=90)
        velocity = {}

        results = (
            db.query(
                SalesOrderLineItem.item_no,
                func.sum(SalesOrderLineItem.quantity).label("total_qty"),
            )
            .filter(
                SalesOrderLineItem.item_no.in_(item_numbers),
                SalesOrderLineItem.created_at >= cutoff,
            )
            .group_by(SalesOrderLineItem.item_no)
            .all()
        )

        for row in results:
            daily = float(row.total_qty) / 90.0
            velocity[row.item_no] = daily

        return velocity

    # ─── QUERY HELPERS ─────────────────────────────────────────

    def get_signals(self, db: Session, acknowledged: Optional[bool] = None,
                    signal_type: Optional[str] = None,
                    skip: int = 0, limit: int = 50) -> List[DemandSignal]:
        """List demand signals."""
        q = db.query(DemandSignal)
        if acknowledged is not None:
            q = q.filter(DemandSignal.is_acknowledged == acknowledged)
        if signal_type:
            q = q.filter(DemandSignal.signal_type == signal_type)
        return q.order_by(DemandSignal.severity.desc(), DemandSignal.created_at.desc()).offset(skip).limit(limit).all()

    def acknowledge_signal(self, db: Session, signal_id: int, user_id: int) -> DemandSignal:
        """Acknowledge a demand signal."""
        signal = db.query(DemandSignal).get(signal_id)
        if not signal:
            raise ValueError(f"Signal {signal_id} not found")
        signal.is_acknowledged = True
        signal.acknowledged_by = user_id
        signal.acknowledged_at = datetime.utcnow()
        db.flush()
        return signal

    def get_dashboard(self, db: Session) -> dict:
        """Stock position overview."""
        total_signals = db.query(DemandSignal).filter(DemandSignal.is_acknowledged == False).count()
        critical = db.query(DemandSignal).filter(
            DemandSignal.signal_type == "critical_stockout",
            DemandSignal.is_acknowledged == False,
        ).count()
        reorder = db.query(DemandSignal).filter(
            DemandSignal.signal_type == "reorder_needed",
            DemandSignal.is_acknowledged == False,
        ).count()
        demand = db.query(DemandSignal).filter(
            DemandSignal.signal_type == "demand_signal",
            DemandSignal.is_acknowledged == False,
        ).count()

        # Observation status
        observe_until = self._get_observe_until(db)
        observation_mode = observe_until and datetime.utcnow() < observe_until

        return {
            "total_active_signals": total_signals,
            "critical_stockouts": critical,
            "reorder_needed": reorder,
            "demand_signals": demand,
            "observation_mode": observation_mode,
            "observe_until": observe_until.isoformat() if observe_until else None,
        }


# Global instance
inventory_review_service = InventoryReviewService()
