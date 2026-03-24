"""
Public API Endpoints (no authentication required)
Handles lead submissions from the embeddable door designer widget.
"""

import logging
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List

from app.db.database import SessionLocal
from app.db.models import PublicQuoteRequest as PublicQuoteRequestModel, User, UserRole
from app.services.notification_service import notification_service
from app.services.auth_service import auth_service

logger = logging.getLogger(__name__)

# ============================================================================
# PUBLIC ROUTER (no auth)
# ============================================================================

public_router = APIRouter(prefix="/api/public", tags=["public"])


# Dependency to get DB session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# --- Pydantic schemas ---

class PublicQuoteRequestSchema(BaseModel):
    contact: dict  # {name, email, phone, postalCode, notes}
    doorConfig: dict  # full door configuration from widget
    timestamp: Optional[str] = None


class LeadStatusUpdate(BaseModel):
    status: str  # contacted, converted, archived


# --- Public endpoint ---

@public_router.post("/quote-request")
def submit_quote_request(
    payload: PublicQuoteRequestSchema,
    db: Session = Depends(get_db),
):
    """
    Receive a quote request from the public door designer widget.
    No authentication required.
    """
    contact = payload.contact or {}
    door_config = payload.doorConfig or {}

    # Validate required fields
    name = (contact.get("name") or "").strip()
    email = (contact.get("email") or "").strip()
    if not name or not email:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Name and email are required in contact information.",
        )

    # Rate-limit: reject duplicate email submissions within 5 minutes
    cutoff = datetime.utcnow() - timedelta(minutes=5)
    recent = (
        db.query(PublicQuoteRequestModel)
        .filter(
            PublicQuoteRequestModel.email == email,
            PublicQuoteRequestModel.created_at >= cutoff,
        )
        .first()
    )
    if recent:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="A quote request from this email was already submitted recently. Please wait a few minutes.",
        )

    # Persist
    record = PublicQuoteRequestModel(
        name=name,
        email=email,
        phone=(contact.get("phone") or "").strip() or None,
        postal_code=(contact.get("postalCode") or "").strip() or None,
        notes=(contact.get("notes") or "").strip() or None,
        door_config=door_config,
        source="widget",
        status="new",
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    # Send admin email notification (best-effort)
    try:
        _send_admin_notification(record)
    except Exception as exc:
        logger.error(f"Failed to send admin notification for quote request {record.id}: {exc}", exc_info=True)

    return {"success": True, "message": "Quote request received"}


def _send_admin_notification(record: PublicQuoteRequestModel):
    """Build and send an HTML email to admins about a new quote request."""
    dc = record.door_config or {}

    # Build a human-readable door config summary
    config_rows = ""
    summary_fields = [
        ("Family", dc.get("familyName") or dc.get("family")),
        ("Design", dc.get("designName") or dc.get("design")),
        ("Color", dc.get("colorName") or dc.get("color")),
        ("Size", dc.get("size")),
        ("Width", f'{dc.get("widthInches")}"' if dc.get("widthInches") else None),
        ("Height", f'{dc.get("heightInches")}"' if dc.get("heightInches") else None),
        ("Window Insert", dc.get("windowInsert")),
        ("Window Qty", dc.get("windowQty")),
        ("Glass Type", dc.get("glassType")),
        ("Window Frame Color", dc.get("windowFrameColor")),
        ("Window Size", dc.get("windowSize")),
    ]
    for label, value in summary_fields:
        if value is not None and value != "":
            config_rows += f"""
                <tr>
                    <td style="padding: 6px 8px; border-bottom: 1px solid #e5e7eb; font-weight: bold;">{label}:</td>
                    <td style="padding: 6px 8px; border-bottom: 1px solid #e5e7eb;">{value}</td>
                </tr>"""

    body = f"""
    <html>
    <body style="font-family: Arial, sans-serif; line-height: 1.6;">
        <h2 style="color: #2563eb;">New Door Designer Quote Request</h2>

        <h3 style="margin-top: 20px;">Contact Information</h3>
        <table style="border-collapse: collapse; width: 100%; max-width: 500px;">
            <tr>
                <td style="padding: 6px 8px; border-bottom: 1px solid #e5e7eb; font-weight: bold;">Name:</td>
                <td style="padding: 6px 8px; border-bottom: 1px solid #e5e7eb;">{record.name}</td>
            </tr>
            <tr>
                <td style="padding: 6px 8px; border-bottom: 1px solid #e5e7eb; font-weight: bold;">Email:</td>
                <td style="padding: 6px 8px; border-bottom: 1px solid #e5e7eb;">{record.email}</td>
            </tr>
            <tr>
                <td style="padding: 6px 8px; border-bottom: 1px solid #e5e7eb; font-weight: bold;">Phone:</td>
                <td style="padding: 6px 8px; border-bottom: 1px solid #e5e7eb;">{record.phone or 'Not provided'}</td>
            </tr>
            <tr>
                <td style="padding: 6px 8px; border-bottom: 1px solid #e5e7eb; font-weight: bold;">Postal Code:</td>
                <td style="padding: 6px 8px; border-bottom: 1px solid #e5e7eb;">{record.postal_code or 'Not provided'}</td>
            </tr>
        </table>

        <h3 style="margin-top: 20px;">Door Configuration</h3>
        <table style="border-collapse: collapse; width: 100%; max-width: 500px;">
            {config_rows}
        </table>

        {"<h3 style='margin-top: 20px;'>Notes</h3><p>" + record.notes + "</p>" if record.notes else ""}

        <p style="margin-top: 20px; color: #6b7280; font-size: 13px;">
            Submitted at {record.created_at.strftime('%Y-%m-%d %H:%M UTC') if record.created_at else 'N/A'}
            &middot; Source: {record.source}
        </p>
    </body>
    </html>
    """

    notification_service.send_email(
        to_emails=notification_service.admin_emails,
        subject=f"New Door Designer Quote Request \u2014 {record.name}",
        body=body,
        is_html=True,
    )


# ============================================================================
# ADMIN ROUTER (auth required)
# ============================================================================

admin_leads_router = APIRouter(prefix="/api/admin/quote-leads", tags=["admin-quote-leads"])

security = HTTPBearer()


def get_current_admin(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    """Get current authenticated admin user from JWT token"""
    token = credentials.credentials

    payload = auth_service.decode_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_type = payload.get("user_type")
    if user_type == "customer":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )

    user_id_str = payload.get("sub")
    if user_id_str is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
        )

    try:
        user_id: int = int(user_id_str)
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
        )

    user = auth_service.get_user_by_id(db, user_id=user_id)
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )
    if user.role not in (UserRole.ADMIN, UserRole.REVIEWER):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )

    return user


@admin_leads_router.get("")
def list_quote_leads(
    status_filter: Optional[str] = None,
    limit: int = 50,
    skip: int = 0,
    _admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """List all public quote requests (admin only)."""
    query = db.query(PublicQuoteRequestModel)

    if status_filter:
        query = query.filter(PublicQuoteRequestModel.status == status_filter)

    total = query.count()
    leads = query.order_by(PublicQuoteRequestModel.created_at.desc()).offset(skip).limit(limit).all()

    return {
        "total": total,
        "leads": [
            {
                "id": lead.id,
                "name": lead.name,
                "email": lead.email,
                "phone": lead.phone,
                "postalCode": lead.postal_code,
                "doorConfig": lead.door_config,
                "source": lead.source,
                "status": lead.status,
                "notes": lead.notes,
                "createdAt": lead.created_at.isoformat() if lead.created_at else None,
            }
            for lead in leads
        ],
    }


@admin_leads_router.patch("/{lead_id}")
def update_lead_status(
    lead_id: int,
    body: LeadStatusUpdate,
    _admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """Update a quote lead's status (admin only)."""
    allowed = {"new", "contacted", "converted", "archived"}
    if body.status not in allowed:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid status. Must be one of: {', '.join(sorted(allowed))}",
        )

    lead = db.query(PublicQuoteRequestModel).filter(PublicQuoteRequestModel.id == lead_id).first()
    if not lead:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead not found")

    lead.status = body.status
    db.commit()
    db.refresh(lead)

    return {
        "success": True,
        "id": lead.id,
        "status": lead.status,
    }
