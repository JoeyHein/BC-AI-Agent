"""
Admin Quote Search API
Cross-customer lookup of saved-quote configs by BC quote number or tag (name),
plus staff download of the Business Central sales-quote PDF by SQ number or GUID.
"""

import logging
import re
from datetime import datetime
from typing import Optional, Tuple

import requests
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.api.admin_customers import get_current_admin
from app.db.database import SessionLocal
from app.db.models import User, SavedQuoteConfig, SalesOrder, QuoteSnapshot, BCCustomer
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


def _creator_fields(tag, user_id, email) -> dict:
    return {
        "creator_tag": tag,
        "creator_user_id": user_id,
        "creator_email": email,
    }


def _ordered_quote_numbers(db: Session, numbers: list) -> set:
    nums = [n for n in numbers if n]
    if not nums:
        return set()
    order_rows = db.query(SalesOrder.bc_quote_number).filter(
        SalesOrder.bc_quote_number.in_(nums),
    ).all()
    return {r[0] for r in order_rows if r[0]}


def _snapshot_customer(snapshot: QuoteSnapshot, portal_user: Optional[User], bc_customer: Optional[BCCustomer]) -> dict:
    if portal_user is not None:
        return {
            "id": portal_user.id,
            "email": portal_user.email,
            "name": portal_user.name or portal_user.email,
            "company_name": getattr(portal_user, "company_name", None) or (
                bc_customer.company_name if bc_customer is not None else None
            ),
            "bc_customer_id": snapshot.bc_customer_id,
        }
    if bc_customer is not None:
        label = bc_customer.company_name or bc_customer.contact_name
    elif snapshot.source == "email":
        label = "Email auto-quote"
    else:
        label = "Configurator"
    return {
        "id": None,
        "email": snapshot.creator_email,
        "name": label,
        "company_name": label,
        "bc_customer_id": snapshot.bc_customer_id,
    }


@router.get("")
def search_all_quotes(
    search: Optional[str] = None,
    limit: int = 50,
    current_admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """Admin: global search across saved-quote configs and configurator quotes.

    ?search= matches name, BC quote number, creator tag, or creator email.
    No search term → the most recent quotes. Configurator quotes that were
    never saved as a customer draft are included once they have a creator tag,
    so staff can see who generated them when a PO was typed.
    """
    cap = max(1, min(limit, 200))
    like = f"%{search.strip()}%" if search and search.strip() else None

    q = (
        db.query(SavedQuoteConfig, User)
        .join(User, SavedQuoteConfig.user_id == User.id)
        .filter(User.user_type == 'CUSTOMER')
    )
    if like:
        q = q.filter(or_(
            SavedQuoteConfig.name.ilike(like),
            SavedQuoteConfig.bc_quote_number.ilike(like),
            SavedQuoteConfig.creator_tag.ilike(like),
            SavedQuoteConfig.creator_email.ilike(like),
        ))

    rows = q.order_by(SavedQuoteConfig.created_at.desc()).limit(cap).all()

    snap_q = db.query(QuoteSnapshot).filter(QuoteSnapshot.creator_tag.isnot(None))
    if like:
        snap_q = snap_q.filter(or_(
            QuoteSnapshot.bc_quote_number.ilike(like),
            QuoteSnapshot.creator_tag.ilike(like),
            QuoteSnapshot.creator_email.ilike(like),
        ))
    snapshots = snap_q.order_by(QuoteSnapshot.created_at.desc()).limit(cap).all()

    saved_bc_ids = {c.bc_quote_id for c, _ in rows if c.bc_quote_id}
    saved_config_ids = {c.id for c, _ in rows}
    extra_snapshots = [
        s for s in snapshots
        if s.bc_quote_id not in saved_bc_ids and s.saved_config_id not in saved_config_ids
    ]

    overlay_ids = [c.bc_quote_id for c, _ in rows if c.bc_quote_id and not c.creator_tag]
    overlay = {}
    if overlay_ids:
        for snap in db.query(QuoteSnapshot).filter(QuoteSnapshot.bc_quote_id.in_(overlay_ids)).all():
            overlay[snap.bc_quote_id] = snap

    bc_ids = {s.bc_customer_id for s in extra_snapshots if s.bc_customer_id}
    users_by_bc = {}
    bc_by_id = {}
    if bc_ids:
        for user in db.query(User).filter(
            User.bc_customer_id.in_(bc_ids),
            User.user_type == "CUSTOMER",
        ).all():
            users_by_bc.setdefault(user.bc_customer_id, user)
        for bc in db.query(BCCustomer).filter(BCCustomer.bc_customer_id.in_(bc_ids)).all():
            bc_by_id[bc.bc_customer_id] = bc

    numbers = [c.bc_quote_number for c, _ in rows if c.bc_quote_number]
    numbers.extend(s.bc_quote_number for s in extra_snapshots if s.bc_quote_number)
    ordered_nums = _ordered_quote_numbers(db, numbers)

    results = []
    for config, owner in rows:
        snap = overlay.get(config.bc_quote_id)
        tag = config.creator_tag or (snap.creator_tag if snap else None)
        user_id = config.creator_user_id if config.creator_user_id is not None else (
            snap.creator_user_id if snap else None
        )
        email = config.creator_email or (snap.creator_email if snap else None)
        results.append((config.created_at or datetime.min, {
            "id": config.id,
            "name": config.name,
            "description": config.description,
            "is_submitted": config.is_submitted,
            "bc_quote_number": config.bc_quote_number,
            "bc_quote_id": config.bc_quote_id,
            "created_at": config.created_at.isoformat() if config.created_at else None,
            "updated_at": config.updated_at.isoformat() if config.updated_at else None,
            "submitted_at": config.submitted_at.isoformat() if config.submitted_at else None,
            "order_placed": bool(config.bc_quote_number and config.bc_quote_number in ordered_nums),
            **_creator_fields(tag, user_id, email),
            "customer": {
                "id": owner.id,
                "email": owner.email,
                "name": owner.name or owner.email,
                "company_name": getattr(owner, "company_name", None),
                "bc_customer_id": owner.bc_customer_id,
            },
        }))

    for snap in extra_snapshots:
        results.append((snap.created_at or datetime.min, {
            "id": f"snapshot-{snap.id}",
            "name": snap.creator_tag or snap.bc_quote_number,
            "description": "Email auto-quote" if snap.source == "email" else "Configurator quote",
            "is_submitted": False,
            "bc_quote_number": snap.bc_quote_number,
            "bc_quote_id": snap.bc_quote_id,
            "created_at": snap.created_at.isoformat() if snap.created_at else None,
            "updated_at": snap.updated_at.isoformat() if snap.updated_at else None,
            "submitted_at": None,
            "order_placed": bool(snap.bc_quote_number and snap.bc_quote_number in ordered_nums),
            **_creator_fields(snap.creator_tag, snap.creator_user_id, snap.creator_email),
            "customer": _snapshot_customer(
                snap,
                users_by_bc.get(snap.bc_customer_id),
                bc_by_id.get(snap.bc_customer_id),
            ),
        }))

    results.sort(key=lambda item: item[0], reverse=True)
    return [payload for _, payload in results[:cap]]


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
