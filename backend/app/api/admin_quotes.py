"""
Admin Quote Search API
Cross-customer lookup of saved-quote configs by BC quote number or tag (name),
plus staff download of the Business Central sales-quote PDF by SQ number or GUID.
"""

import logging
import re
from typing import Optional, Tuple

import requests
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.api.admin_customers import get_current_admin
from app.db.database import SessionLocal
from app.db.models import User, SavedQuoteConfig, SalesOrder
from app.integrations.bc.client import bc_client

router = APIRouter(prefix="/api/admin/quotes", tags=["admin-quotes"])
logger = logging.getLogger(__name__)

# Same GUID shape DoorConfigurator uses for BC customer/quote ids.
_GUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


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


def normalize_staff_quote_ref(raw: str) -> Tuple[str, str]:
    """Parse a staff-supplied quote identifier into ('guid', uuid) or ('number', 'SQ-XXXXXX').

    Accepts:
      - BC system GUID
      - SQ-003132 (any case)
      - 3132 / 003132 → SQ-003132 (same padding as door-config load-quote)
    """
    value = (raw or "").strip()
    if not value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Quote number is required",
        )
    if _GUID_RE.fullmatch(value):
        return ("guid", value)
    upper = value.upper()
    if upper.startswith("SQ-"):
        rest = upper[3:]
        if not rest or not rest.replace("-", "").isalnum():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid quote number '{raw}'",
            )
        return ("number", upper)
    try:
        return ("number", f"SQ-{int(value):06d}")
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid quote number '{raw}'",
        )


def _lookup_bc_quote(kind: str, value: str) -> dict:
    """Resolve a sales quote from BC. Source of truth is BC, not SavedQuoteConfig.

    DoorConfigurator generate-quote stores both bc_quote_id (GUID) and
    bc_quote_number (SQ-…) on QuoteSnapshot / the generate-quote response.
    Staff DoorConfigurator quotes are often NOT in saved_quote_configs
    (that's the customer portal), so this always hits BC.
    """
    try:
        if kind == "guid":
            quote = bc_client.get_sales_quote(value)
        else:
            quote = bc_client.get_sales_quote_by_number(value)
    except requests.HTTPError as e:
        bc_status = getattr(e.response, "status_code", None)
        if bc_status == 404:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Quote {value} not found in Business Central",
            ) from e
        logger.error(f"BC lookup failed for quote {value}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to look up quote in Business Central: {e}",
        ) from e

    if not quote:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Quote {value} not found in Business Central",
        )
    return quote


@router.get("/by-number/{sq_number}/pdf")
def download_quote_pdf_by_number(
    sq_number: str,
    current_admin: User = Depends(get_current_admin),
):
    """Staff: download the BC sales-quote PDF by SQ number or GUID.

    Looks up the quote in Business Central (`number eq 'SQ-…'` or by GUID),
    then streams `BCClient.get_quote_pdf(guid)` as `Quote_SQ-XXXXXX.pdf`.

    Requires an admin JWT (same as GET /api/admin/quotes). Does not use the
    customer-portal PDF route and does not require a local SavedQuoteConfig row,
    so DoorConfigurator SQ quotes work even when they were never saved as a
    customer draft.
    """
    kind, value = normalize_staff_quote_ref(sq_number)
    quote = _lookup_bc_quote(kind, value)
    logger.info(
        "Admin %s downloading BC quote PDF %s (%s)",
        getattr(current_admin, "email", "?"),
        value,
        kind,
    )
    quote_guid = quote.get("id")
    if not quote_guid:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Business Central returned quote {value} without an id",
        )

    try:
        pdf_bytes = bc_client.get_quote_pdf(quote_guid)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to download PDF for quote {value}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to download PDF from BC: {e}",
        ) from e

    if not pdf_bytes:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Empty PDF content for quote {value}",
        )

    quote_no = quote.get("number") or value
    filename = f"Quote_{quote_no}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
