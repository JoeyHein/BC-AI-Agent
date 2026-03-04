"""
Quote Review API — admin endpoints for reviewing configurator quotes against BC edits.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import QuoteSnapshot, QuoteReview, User
from app.api.auth import require_admin
from app.services.quote_review_service import (
    compute_quote_diff,
    fetch_current_bc_lines,
    create_review,
)
from app.integrations.ai.client import ai_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/quote-review", tags=["quote-review"])


# ── Request models ─────────────────────────────────────────────

class ReviewRequest(BaseModel):
    include_ai: bool = False
    notes: Optional[str] = None


class PatternAnalysisRequest(BaseModel):
    limit: int = 20  # How many recent reviews to analyze


# ── Endpoints ──────────────────────────────────────────────────

@router.get("/snapshots")
async def list_snapshots(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """List all quote snapshots, newest first, with reviewed/unreviewed flag."""
    snapshots = (
        db.query(QuoteSnapshot)
        .order_by(QuoteSnapshot.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )

    total = db.query(QuoteSnapshot).count()

    results = []
    for s in snapshots:
        review_count = db.query(QuoteReview).filter(QuoteReview.snapshot_id == s.id).count()
        results.append({
            "id": s.id,
            "bc_quote_id": s.bc_quote_id,
            "bc_quote_number": s.bc_quote_number,
            "source": s.source,
            "bc_customer_id": s.bc_customer_id,
            "pricing_tier": s.pricing_tier,
            "door_configs": s.door_configs,
            "original_pricing_totals": s.original_pricing_totals,
            "review_count": review_count,
            "is_reviewed": review_count > 0,
            "created_at": s.created_at.isoformat() if s.created_at else None,
        })

    return {"snapshots": results, "total": total}


@router.post("/{bc_quote_id}/review")
async def review_quote(
    bc_quote_id: str,
    body: ReviewRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """
    Diff a quote's original snapshot against current BC lines.
    Optionally run AI analysis on the diff.
    """
    snapshot = db.query(QuoteSnapshot).filter(
        QuoteSnapshot.bc_quote_id == bc_quote_id
    ).first()
    if not snapshot:
        raise HTTPException(status_code=404, detail="No snapshot found for this quote")

    # Fetch current BC lines
    try:
        bc_lines = fetch_current_bc_lines(bc_quote_id)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch BC quote lines: {e}")

    # Compute diff
    diff_result = compute_quote_diff(snapshot.original_lines or [], bc_lines)

    # Optional AI analysis
    ai_analysis = None
    if body.include_ai and diff_result["has_changes"]:
        try:
            ai_analysis = ai_client.analyze_quote_diff(
                diff=diff_result,
                door_configs=snapshot.door_configs,
                context={
                    "bc_quote_number": snapshot.bc_quote_number,
                    "pricing_tier": snapshot.pricing_tier,
                    "source": snapshot.source,
                },
            )
        except Exception as e:
            logger.warning(f"AI analysis failed: {e}")
            ai_analysis = {"error": str(e)}

    # Save review
    review = create_review(
        db=db,
        snapshot=snapshot,
        bc_lines=bc_lines,
        diff_result=diff_result,
        ai_analysis=ai_analysis,
        reviewed_by=current_user.id,
        review_notes=body.notes,
    )

    return {
        "review_id": review.id,
        "bc_quote_number": snapshot.bc_quote_number,
        "diff": diff_result,
        "ai_analysis": ai_analysis,
        "created_at": review.created_at.isoformat(),
    }


@router.post("/analyze-patterns")
async def analyze_patterns(
    body: PatternAnalysisRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """
    Cross-quote AI pattern analysis across recent reviews.
    Identifies recurring issues and suggests configurator improvements.
    """
    reviews = (
        db.query(QuoteReview)
        .filter(QuoteReview.diff_result.isnot(None))
        .order_by(QuoteReview.created_at.desc())
        .limit(body.limit)
        .all()
    )

    if not reviews:
        return {"patterns": [], "summary": "No reviews with changes found"}

    # Build data for AI
    reviews_data = []
    for r in reviews:
        snapshot = db.query(QuoteSnapshot).filter(QuoteSnapshot.id == r.snapshot_id).first()
        if not snapshot:
            continue
        diff = r.diff_result or {}
        if not diff.get("has_changes"):
            continue
        reviews_data.append({
            "bc_quote_number": snapshot.bc_quote_number,
            "door_configs": snapshot.door_configs,
            "pricing_tier": snapshot.pricing_tier,
            "source": snapshot.source,
            "diff": diff,
        })

    if not reviews_data:
        return {"patterns": [], "summary": "No reviews with actual changes found"}

    try:
        result = ai_client.analyze_quote_patterns(reviews_data)
        return result
    except Exception as e:
        logger.error(f"Pattern analysis failed: {e}")
        raise HTTPException(status_code=500, detail=f"AI pattern analysis failed: {e}")


@router.get("/reviews")
async def list_reviews(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """List past reviews, newest first."""
    reviews = (
        db.query(QuoteReview)
        .order_by(QuoteReview.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )

    total = db.query(QuoteReview).count()

    results = []
    for r in reviews:
        snapshot = db.query(QuoteSnapshot).filter(QuoteSnapshot.id == r.snapshot_id).first()
        diff = r.diff_result or {}
        results.append({
            "id": r.id,
            "snapshot_id": r.snapshot_id,
            "bc_quote_number": snapshot.bc_quote_number if snapshot else None,
            "has_changes": diff.get("has_changes", False),
            "summary": diff.get("summary", ""),
            "has_ai_analysis": r.ai_analysis is not None and "error" not in (r.ai_analysis or {}),
            "reviewed_by": r.reviewed_by,
            "review_notes": r.review_notes,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        })

    return {"reviews": results, "total": total}


@router.get("/reviews/{review_id}")
async def get_review(
    review_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Get a single review with full detail."""
    review = db.query(QuoteReview).filter(QuoteReview.id == review_id).first()
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")

    snapshot = db.query(QuoteSnapshot).filter(QuoteSnapshot.id == review.snapshot_id).first()

    return {
        "id": review.id,
        "snapshot": {
            "id": snapshot.id,
            "bc_quote_id": snapshot.bc_quote_id,
            "bc_quote_number": snapshot.bc_quote_number,
            "source": snapshot.source,
            "door_configs": snapshot.door_configs,
            "original_lines": snapshot.original_lines,
            "original_line_pricing": snapshot.original_line_pricing,
            "original_pricing_totals": snapshot.original_pricing_totals,
            "pricing_tier": snapshot.pricing_tier,
            "created_at": snapshot.created_at.isoformat() if snapshot.created_at else None,
        } if snapshot else None,
        "bc_lines_at_review": review.bc_lines_at_review,
        "diff": review.diff_result,
        "ai_analysis": review.ai_analysis,
        "reviewed_by": review.reviewed_by,
        "review_notes": review.review_notes,
        "created_at": review.created_at.isoformat() if review.created_at else None,
    }
