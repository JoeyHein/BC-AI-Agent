"""
One-shot backfill: mark every BC sales order that exists right now as
already-viewed in order_view_state. Run after the y1z2a3b4c5d6 migration.

Without this, every currently-open BC order (36 today) would render with
a NEW badge on the next page load, defeating the purpose of the badge.

Safe to re-run: existing rows are left alone.
"""

import logging
import sys

from app.db.database import SessionLocal
from app.db.models import OrderViewState
from app.integrations.bc.client import bc_client

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def main():
    db = SessionLocal()
    try:
        orders = bc_client.get_sales_orders(top=500)
        logger.info(f"Fetched {len(orders)} sales orders from BC")

        existing = {r.bc_order_number for r in db.query(OrderViewState.bc_order_number).all()}
        logger.info(f"order_view_state already tracks {len(existing)} rows")

        inserted = 0
        for o in orders:
            num = o.get("number")
            if not num or num in existing:
                continue
            db.add(OrderViewState(bc_order_number=num, viewed_by_user_id=None))
            inserted += 1

        db.commit()
        logger.info(f"Backfilled {inserted} order_view_state row(s)")
    except Exception as e:
        db.rollback()
        logger.error(f"Backfill failed: {e}")
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
