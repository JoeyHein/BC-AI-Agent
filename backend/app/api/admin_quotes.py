"""
Admin Quote Search API
Cross-customer lookup of saved-quote configs by BC quote number or tag (name).
"""

import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session
from typing import Optional

from app.db.database import SessionLocal
from app.db.models import User, SavedQuoteConfig, SalesOrder
from app.api.admin_customers import get_current_admin

router = APIRouter(prefix="/api/admin/quotes", tags=["admin-quotes"])
logger = logging.getLogger(__name__)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("")
def search_all_quotes(
    search: Optional[str] = None,
    limit: int = 50,
    current_admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """Admin: global search across every customer's saved-quote configs.

    ?search= matches name (tag) or BC quote number, case-insensitive substring.
    No search term → returns the most recent `limit` quotes across all customers.
    """
    q = (
        db.query(SavedQuoteConfig, User)
        .join(User, SavedQuoteConfig.user_id == User.id)
        .filter(User.user_type == 'CUSTOMER')
    )
    if search and search.strip():
        like = f"%{search.strip()}%"
        q = q.filter(or_(
            SavedQuoteConfig.name.ilike(like),
            SavedQuoteConfig.bc_quote_number.ilike(like),
        ))

    rows = q.order_by(SavedQuoteConfig.created_at.desc()).limit(max(1, min(limit, 200))).all()

    submitted_nums = [c.bc_quote_number for c, _ in rows if c.bc_quote_number]
    ordered_nums: set = set()
    if submitted_nums:
        order_rows = db.query(SalesOrder.bc_quote_number).filter(
            SalesOrder.bc_quote_number.in_(submitted_nums),
        ).all()
        ordered_nums = {r[0] for r in order_rows if r[0]}

    return [
        {
            "id": c.id,
            "name": c.name,
            "description": c.description,
            "is_submitted": c.is_submitted,
            "bc_quote_number": c.bc_quote_number,
            "bc_quote_id": c.bc_quote_id,
            "created_at": c.created_at.isoformat() if c.created_at else None,
            "updated_at": c.updated_at.isoformat() if c.updated_at else None,
            "submitted_at": c.submitted_at.isoformat() if c.submitted_at else None,
            "order_placed": bool(c.bc_quote_number and c.bc_quote_number in ordered_nums),
            "customer": {
                "id": u.id,
                "email": u.email,
                "name": u.name or u.email,
                "company_name": getattr(u, "company_name", None),
                "bc_customer_id": u.bc_customer_id,
            },
        }
        for c, u in rows
    ]
