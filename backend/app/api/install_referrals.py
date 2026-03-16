"""
Install Referral API Endpoints
Customer-facing referral submission + Admin queue management
"""

import logging
import uuid
from datetime import date, datetime
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List

from app.db.database import SessionLocal
from app.db.models import User, UserRole, InstallReferral
from app.services.auth_service import auth_service
from app.services.notification_service import notification_service
from app.api.customer_auth import get_current_customer
from app.api.admin_customers import get_current_admin

logger = logging.getLogger(__name__)

# ============================================================================
# ROUTERS
# ============================================================================

customer_router = APIRouter(
    prefix="/api/customer/portal/install-referrals",
    tags=["customer-install-referrals"],
)

admin_router = APIRouter(
    prefix="/api/admin/install-referrals",
    tags=["admin-install-referrals"],
)


# Dependency to get DB session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ============================================================================
# REQUEST/RESPONSE MODELS
# ============================================================================

class CreateReferralRequest(BaseModel):
    site_address: str
    site_contact_name: str
    site_contact_phone: str
    requested_date: Optional[date] = None
    access_notes: Optional[str] = None
    order_reference: Optional[str] = None
    project_lot_id: Optional[str] = None


class ReferralListItem(BaseModel):
    id: str
    order_reference: Optional[str]
    site_address: str
    status: str
    requested_date: Optional[date]
    scheduled_date: Optional[date]
    created_at: datetime

    class Config:
        from_attributes = True


class CustomerReferralDetail(BaseModel):
    id: str
    status: str
    scheduled_date: Optional[date]
    site_address: str
    site_contact_name: str
    site_contact_phone: str
    requested_date: Optional[date]
    access_notes: Optional[str]
    order_reference: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class AdminReferralResponse(BaseModel):
    id: str
    customer_id: int
    customer_name: Optional[str]
    customer_email: str
    order_reference: Optional[str]
    project_lot_id: Optional[str]
    site_address: str
    site_contact_name: str
    site_contact_phone: str
    requested_date: Optional[date]
    access_notes: Optional[str]
    status: str
    assigned_sub: Optional[str]
    scheduled_date: Optional[date]
    internal_notes: Optional[str]
    created_at: datetime
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True


class UpdateReferralRequest(BaseModel):
    status: Optional[str] = None
    assigned_sub: Optional[str] = None
    scheduled_date: Optional[date] = None
    internal_notes: Optional[str] = None


# ============================================================================
# CUSTOMER ENDPOINTS
# ============================================================================

@customer_router.post("", response_model=CustomerReferralDetail, status_code=status.HTTP_201_CREATED)
def create_referral(
    data: CreateReferralRequest,
    current_user: User = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    """Create a new install referral request"""
    referral = InstallReferral(
        id=str(uuid.uuid4()),
        customer_id=current_user.id,
        site_address=data.site_address,
        site_contact_name=data.site_contact_name,
        site_contact_phone=data.site_contact_phone,
        requested_date=data.requested_date,
        access_notes=data.access_notes,
        order_reference=data.order_reference,
        project_lot_id=data.project_lot_id,
        status="new",
    )

    db.add(referral)
    db.commit()
    db.refresh(referral)

    logger.info(f"Install referral created by {current_user.email}: {referral.id}")

    # Notify admins
    try:
        notification_service.send_email(
            to_emails=notification_service.admin_emails,
            subject=f"New Install Referral — {data.site_address}",
            body=f"""
            <html>
            <body style="font-family: Arial, sans-serif; line-height: 1.6;">
                <h2 style="color: #2563eb;">New Install Referral Request</h2>
                <table style="border-collapse: collapse; width: 100%; max-width: 500px;">
                    <tr>
                        <td style="padding: 8px; border-bottom: 1px solid #e5e7eb; font-weight: bold;">Customer:</td>
                        <td style="padding: 8px; border-bottom: 1px solid #e5e7eb;">{current_user.name or current_user.email}</td>
                    </tr>
                    <tr>
                        <td style="padding: 8px; border-bottom: 1px solid #e5e7eb; font-weight: bold;">Site Address:</td>
                        <td style="padding: 8px; border-bottom: 1px solid #e5e7eb;">{data.site_address}</td>
                    </tr>
                    <tr>
                        <td style="padding: 8px; border-bottom: 1px solid #e5e7eb; font-weight: bold;">Site Contact:</td>
                        <td style="padding: 8px; border-bottom: 1px solid #e5e7eb;">{data.site_contact_name} — {data.site_contact_phone}</td>
                    </tr>
                    <tr>
                        <td style="padding: 8px; border-bottom: 1px solid #e5e7eb; font-weight: bold;">Requested Date:</td>
                        <td style="padding: 8px; border-bottom: 1px solid #e5e7eb;">{data.requested_date or 'Not specified'}</td>
                    </tr>
                    <tr>
                        <td style="padding: 8px; border-bottom: 1px solid #e5e7eb; font-weight: bold;">Order Ref:</td>
                        <td style="padding: 8px; border-bottom: 1px solid #e5e7eb;">{data.order_reference or 'N/A'}</td>
                    </tr>
                </table>
                {f'<p><strong>Access Notes:</strong> {data.access_notes}</p>' if data.access_notes else ''}
            </body>
            </html>
            """,
        )
    except Exception as e:
        logger.error(f"Failed to send admin notification for referral {referral.id}: {e}")

    return CustomerReferralDetail(
        id=referral.id,
        status=referral.status,
        scheduled_date=referral.scheduled_date,
        site_address=referral.site_address,
        site_contact_name=referral.site_contact_name,
        site_contact_phone=referral.site_contact_phone,
        requested_date=referral.requested_date,
        access_notes=referral.access_notes,
        order_reference=referral.order_reference,
        created_at=referral.created_at,
    )


@customer_router.get("", response_model=List[ReferralListItem])
def list_customer_referrals(
    current_user: User = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    """List the current customer's install referrals"""
    referrals = (
        db.query(InstallReferral)
        .filter(InstallReferral.customer_id == current_user.id)
        .order_by(InstallReferral.created_at.desc())
        .all()
    )

    return [
        ReferralListItem(
            id=r.id,
            order_reference=r.order_reference,
            site_address=r.site_address,
            status=r.status,
            requested_date=r.requested_date,
            scheduled_date=r.scheduled_date,
            created_at=r.created_at,
        )
        for r in referrals
    ]


@customer_router.get("/{referral_id}", response_model=CustomerReferralDetail)
def get_customer_referral(
    referral_id: str,
    current_user: User = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    """Get a single referral (customer view — no internal_notes or assigned_sub)"""
    referral = (
        db.query(InstallReferral)
        .filter(
            InstallReferral.id == referral_id,
            InstallReferral.customer_id == current_user.id,
        )
        .first()
    )

    if not referral:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Referral not found",
        )

    return CustomerReferralDetail(
        id=referral.id,
        status=referral.status,
        scheduled_date=referral.scheduled_date,
        site_address=referral.site_address,
        site_contact_name=referral.site_contact_name,
        site_contact_phone=referral.site_contact_phone,
        requested_date=referral.requested_date,
        access_notes=referral.access_notes,
        order_reference=referral.order_reference,
        created_at=referral.created_at,
    )


# ============================================================================
# ADMIN ENDPOINTS
# ============================================================================

@admin_router.get("", response_model=List[AdminReferralResponse])
def list_all_referrals(
    status_filter: Optional[str] = Query(None, alias="status"),
    current_admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """List all install referrals (admin queue). Optionally filter by status."""
    query = db.query(InstallReferral)

    if status_filter:
        if status_filter not in ("new", "scheduled", "complete"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid status filter. Must be 'new', 'scheduled', or 'complete'.",
            )
        query = query.filter(InstallReferral.status == status_filter)

    # Sort: new first, then by created_at desc
    from sqlalchemy import case
    query = query.order_by(
        case(
            (InstallReferral.status == "new", 0),
            (InstallReferral.status == "scheduled", 1),
            else_=2,
        ),
        InstallReferral.created_at.desc(),
    )

    referrals = query.all()

    # Batch-load customer info
    customer_ids = list({r.customer_id for r in referrals})
    customers_map = {}
    if customer_ids:
        customers = db.query(User).filter(User.id.in_(customer_ids)).all()
        customers_map = {c.id: c for c in customers}

    result = []
    for r in referrals:
        customer = customers_map.get(r.customer_id)
        result.append(
            AdminReferralResponse(
                id=r.id,
                customer_id=r.customer_id,
                customer_name=customer.name if customer else None,
                customer_email=customer.email if customer else "unknown",
                order_reference=r.order_reference,
                project_lot_id=r.project_lot_id,
                site_address=r.site_address,
                site_contact_name=r.site_contact_name,
                site_contact_phone=r.site_contact_phone,
                requested_date=r.requested_date,
                access_notes=r.access_notes,
                status=r.status,
                assigned_sub=r.assigned_sub,
                scheduled_date=r.scheduled_date,
                internal_notes=r.internal_notes,
                created_at=r.created_at,
                updated_at=r.updated_at,
            )
        )

    return result


@admin_router.patch("/{referral_id}", response_model=AdminReferralResponse)
def update_referral(
    referral_id: str,
    data: UpdateReferralRequest,
    current_admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """Update an install referral (admin only)"""
    referral = db.query(InstallReferral).filter(InstallReferral.id == referral_id).first()

    if not referral:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Referral not found",
        )

    old_status = referral.status

    if data.status is not None:
        if data.status not in ("new", "scheduled", "complete"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid status. Must be 'new', 'scheduled', or 'complete'.",
            )
        referral.status = data.status

    if data.assigned_sub is not None:
        referral.assigned_sub = data.assigned_sub

    if data.scheduled_date is not None:
        referral.scheduled_date = data.scheduled_date

    if data.internal_notes is not None:
        referral.internal_notes = data.internal_notes

    db.commit()
    db.refresh(referral)

    logger.info(f"Admin {current_admin.email} updated referral {referral_id}: status={referral.status}")

    # If status changed to 'scheduled', notify the customer
    if data.status == "scheduled" and old_status != "scheduled":
        try:
            customer = db.query(User).filter(User.id == referral.customer_id).first()
            if customer:
                scheduled_str = str(referral.scheduled_date) if referral.scheduled_date else "TBD"
                notification_service.send_email(
                    to_emails=[customer.email],
                    subject=f"Install Scheduled — {referral.site_address}",
                    body=f"""
                    <html>
                    <body style="font-family: Arial, sans-serif; line-height: 1.6; max-width: 600px; margin: 0 auto;">
                        <div style="background-color: #2563eb; color: white; padding: 20px; text-align: center;">
                            <h1 style="margin: 0;">OPENDC</h1>
                            <p style="margin: 5px 0 0 0;">Customer Portal</p>
                        </div>
                        <div style="padding: 30px;">
                            <h2 style="color: #1f2937;">Installation Scheduled</h2>
                            <p>Your installation at <strong>{referral.site_address}</strong> has been scheduled for <strong>{scheduled_str}</strong>.</p>
                            <p>Our installer will be in touch.</p>
                            <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 30px 0;">
                            <p style="color: #6b7280; font-size: 14px;">
                                If you have any questions, please contact us at support@opendc.com
                            </p>
                        </div>
                    </body>
                    </html>
                    """,
                )
        except Exception as e:
            logger.error(f"Failed to send scheduling notification for referral {referral_id}: {e}")

    # Build response with customer info
    customer = db.query(User).filter(User.id == referral.customer_id).first()

    return AdminReferralResponse(
        id=referral.id,
        customer_id=referral.customer_id,
        customer_name=customer.name if customer else None,
        customer_email=customer.email if customer else "unknown",
        order_reference=referral.order_reference,
        project_lot_id=referral.project_lot_id,
        site_address=referral.site_address,
        site_contact_name=referral.site_contact_name,
        site_contact_phone=referral.site_contact_phone,
        requested_date=referral.requested_date,
        access_notes=referral.access_notes,
        status=referral.status,
        assigned_sub=referral.assigned_sub,
        scheduled_date=referral.scheduled_date,
        internal_notes=referral.internal_notes,
        created_at=referral.created_at,
        updated_at=referral.updated_at,
    )
