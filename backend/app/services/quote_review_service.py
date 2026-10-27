"""
Quote Review Service — snapshot saving, diff algorithm, AI orchestration.

Captures the original configurator output when a BC quote is created,
then diffs it against the manually-edited BC quote to identify patterns.
"""

import logging
from typing import Dict, Any, Optional, List
from collections import defaultdict
from datetime import datetime

from sqlalchemy.orm import Session

from app.db.models import QuoteSnapshot, QuoteReview, SavedQuoteConfig
from app.integrations.bc.client import bc_client

logger = logging.getLogger(__name__)


def _stamp_saved_quote_creator(
    db: Session,
    *,
    bc_quote_id: Optional[str],
    saved_config_id: Optional[int],
    creator_tag: Optional[str],
    creator_user_id: Optional[int],
    creator_email: Optional[str],
) -> None:
    """Copy the configurator creator onto any matching saved-quote draft."""
    if creator_tag is None and creator_user_id is None and not creator_email:
        return
    rows = []
    if saved_config_id:
        row = db.query(SavedQuoteConfig).filter(SavedQuoteConfig.id == saved_config_id).first()
        if row is not None:
            rows.append(row)
    if bc_quote_id:
        rows.extend(
            db.query(SavedQuoteConfig)
            .filter(SavedQuoteConfig.bc_quote_id == bc_quote_id)
            .all()
        )
    seen = set()
    for row in rows:
        if row.id in seen:
            continue
        seen.add(row.id)
        if creator_tag is None:
            continue
        row.creator_tag = creator_tag
        row.creator_user_id = creator_user_id
        row.creator_email = creator_email


def save_quote_snapshot(
    db: Session,
    bc_quote_id: str,
    bc_quote_number: str,
    source: str,
    all_lines: list,
    line_pricing: Optional[list] = None,
    pricing_totals: Optional[dict] = None,
    door_configs: Optional[list] = None,
    bc_customer_id: Optional[str] = None,
    pricing_tier: Optional[str] = None,
    saved_config_id: Optional[int] = None,
    creator_user_id: Optional[int] = None,
    creator_email: Optional[str] = None,
    creator_tag: Optional[str] = None,
) -> Optional[QuoteSnapshot]:
    """
    Save a snapshot of the original configurator output for later diffing.
    Uses upsert pattern — deletes existing snapshot for same bc_quote_id, then inserts.

    Creator fields are kept when a later save (customer-portal refresh) does
    not pass them, so a typed PO does not erase who generated the quote.
    """
    try:
        # Delete existing snapshot for this quote (handles refreshes)
        existing = db.query(QuoteSnapshot).filter(
            QuoteSnapshot.bc_quote_id == bc_quote_id
        ).first()
        preserved_user_id = existing.creator_user_id if existing else None
        preserved_email = existing.creator_email if existing else None
        preserved_tag = existing.creator_tag if existing else None
        if existing:
            db.delete(existing)
            db.flush()

        resolved_user_id = creator_user_id if creator_user_id is not None else preserved_user_id
        resolved_email = creator_email if creator_email else preserved_email
        resolved_tag = creator_tag if creator_tag else preserved_tag

        snapshot = QuoteSnapshot(
            bc_quote_id=bc_quote_id,
            bc_quote_number=bc_quote_number,
            source=source,
            original_lines=all_lines,
            original_line_pricing=line_pricing,
            original_pricing_totals=pricing_totals,
            door_configs=door_configs,
            bc_customer_id=bc_customer_id,
            pricing_tier=pricing_tier,
            saved_config_id=saved_config_id,
            creator_user_id=resolved_user_id,
            creator_email=resolved_email,
            creator_tag=resolved_tag,
        )
        db.add(snapshot)
        _stamp_saved_quote_creator(
            db,
            bc_quote_id=bc_quote_id,
            saved_config_id=saved_config_id,
            creator_tag=resolved_tag,
            creator_user_id=resolved_user_id,
            creator_email=resolved_email,
        )
        db.commit()
        db.refresh(snapshot)
        logger.info(f"Saved quote snapshot for {bc_quote_number} (source={source})")
        return snapshot
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to save quote snapshot for {bc_quote_number}: {e}")
        return None


def compute_quote_diff(
    original_lines: list,
    bc_lines: list,
) -> Dict[str, Any]:
    """
    Diff original configurator lines against current BC quote lines.

    Matches by part number (lineObjectNumber in BC).
    Aggregates quantities for duplicate part numbers.

    Returns:
        {added, removed, modified, unchanged_count, summary}
    """
    # Build aggregated maps: part_number -> {total_qty, total_amount, descriptions}
    def aggregate_lines(lines: list, part_key: str, qty_key: str, price_key: str = None) -> dict:
        agg = {}
        for line in lines:
            pn = line.get(part_key, "")
            if not pn:
                continue
            # Skip comment lines
            line_type = line.get("lineType") or line.get("line_type", "")
            if line_type == "Comment":
                continue

            qty = line.get(qty_key, 0) or 0
            price = line.get(price_key, 0) if price_key else 0

            if pn in agg:
                agg[pn]["quantity"] += qty
                if price:
                    agg[pn]["total_amount"] += round(price * qty, 2)
            else:
                agg[pn] = {
                    "part_number": pn,
                    "description": line.get("description", ""),
                    "quantity": qty,
                    "unit_price": price,
                    "total_amount": round(price * qty, 2) if price else 0,
                }
        return agg

    # Original lines from snapshot (from all_lines format)
    original_agg = aggregate_lines(
        original_lines,
        part_key="part_number",
        qty_key="quantity",
        price_key="unit_price",
    )

    # BC lines (from salesQuoteLines API)
    bc_agg = aggregate_lines(
        bc_lines,
        part_key="lineObjectNumber",
        qty_key="quantity",
        price_key="unitPrice",
    )

    original_parts = set(original_agg.keys())
    bc_parts = set(bc_agg.keys())

    added = []
    removed = []
    modified = []
    unchanged_count = 0

    # Parts only in BC (added by staff)
    for pn in bc_parts - original_parts:
        item = bc_agg[pn]
        added.append({
            "part_number": pn,
            "description": item["description"],
            "quantity": item["quantity"],
            "unit_price": item["unit_price"],
        })

    # Parts only in original (removed by staff)
    for pn in original_parts - bc_parts:
        item = original_agg[pn]
        removed.append({
            "part_number": pn,
            "description": item["description"],
            "quantity": item["quantity"],
        })

    # Parts in both — check for changes
    for pn in original_parts & bc_parts:
        orig = original_agg[pn]
        curr = bc_agg[pn]

        qty_changed = orig["quantity"] != curr["quantity"]
        price_changed = (
            orig["unit_price"] and curr["unit_price"]
            and abs(orig["unit_price"] - curr["unit_price"]) > 0.01
        )

        if qty_changed or price_changed:
            change = {
                "part_number": pn,
                "description": curr["description"],
            }
            if qty_changed:
                change["quantity_original"] = orig["quantity"]
                change["quantity_current"] = curr["quantity"]
            if price_changed:
                change["price_original"] = orig["unit_price"]
                change["price_current"] = curr["unit_price"]
            modified.append(change)
        else:
            unchanged_count += 1

    # Build summary
    changes = []
    if added:
        changes.append(f"{len(added)} part(s) added")
    if removed:
        changes.append(f"{len(removed)} part(s) removed")
    if modified:
        changes.append(f"{len(modified)} part(s) modified")
    summary = ", ".join(changes) if changes else "No changes detected"

    return {
        "added": added,
        "removed": removed,
        "modified": modified,
        "unchanged_count": unchanged_count,
        "summary": summary,
        "has_changes": bool(added or removed or modified),
    }


def fetch_current_bc_lines(bc_quote_id: str) -> list:
    """Fetch current quote lines from BC for comparison."""
    try:
        lines = bc_client.get_quote_lines(bc_quote_id)
        return lines
    except Exception as e:
        logger.error(f"Failed to fetch BC quote lines for {bc_quote_id}: {e}")
        raise


def create_review(
    db: Session,
    snapshot: QuoteSnapshot,
    bc_lines: list,
    diff_result: dict,
    ai_analysis: Optional[dict] = None,
    reviewed_by: Optional[int] = None,
    review_notes: Optional[str] = None,
) -> QuoteReview:
    """Create a new QuoteReview record."""
    review = QuoteReview(
        snapshot_id=snapshot.id,
        bc_lines_at_review=bc_lines,
        diff_result=diff_result,
        ai_analysis=ai_analysis,
        reviewed_by=reviewed_by,
        review_notes=review_notes,
    )
    db.add(review)
    db.commit()
    db.refresh(review)
    return review
