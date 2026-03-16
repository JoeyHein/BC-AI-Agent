"""
Admin Customer Management API Endpoints
Manage customer portal accounts from the admin interface
"""

import logging
import secrets
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr
from typing import Optional, List

from app.db.database import SessionLocal
from app.db.models import User, UserRole, BCCustomer, SavedQuoteConfig, SalesOrder
from app.services.auth_service import auth_service
from app.services.bc_sync_service import bc_sync_service
from app.integrations.bc.client import bc_client
from app.services.notification_service import notification_service
from app.config import settings

router = APIRouter(prefix="/api/admin/customers", tags=["admin-customers"])
logger = logging.getLogger(__name__)

# Security
security = HTTPBearer()


# Dependency to get DB session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# Dependency to get current admin user
def get_current_admin(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
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

    # Check that this is NOT a customer token (admin only)
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
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is inactive",
        )

    # Only admins can access these endpoints
    if user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin role required",
        )

    return user


# ============================================================================
# REQUEST/RESPONSE MODELS
# ============================================================================

class CustomerListResponse(BaseModel):
    id: int
    email: str
    name: Optional[str]
    is_active: bool
    email_verified: bool
    bc_customer_id: Optional[str]
    bc_company_name: Optional[str]
    bc_price_multiplier: Optional[float]
    pricing_tier: Optional[str]
    created_at: datetime
    last_login_at: Optional[datetime]
    saved_quotes_count: int

    class Config:
        from_attributes = True


class CustomerDetailResponse(BaseModel):
    id: int
    email: str
    name: Optional[str]
    is_active: bool
    email_verified: bool
    bc_customer_id: Optional[str]
    bc_company_name: Optional[str]
    bc_price_multiplier: Optional[float]
    pricing_tier: Optional[str]
    bc_contact_name: Optional[str]
    bc_email: Optional[str]
    bc_phone: Optional[str]
    created_at: datetime
    last_login_at: Optional[datetime]
    saved_quotes_count: int
    submitted_quotes_count: int

    class Config:
        from_attributes = True


class UpdatePricingTierRequest(BaseModel):
    pricing_tier: Optional[str]  # gold, silver, bronze, retail, or null to clear


class LinkCustomerRequest(BaseModel):
    bc_customer_id: str


class CreateCustomerRequest(BaseModel):
    email: EmailStr
    name: str
    password: str
    bc_customer_id: Optional[str] = None


class UpdateCustomerRequest(BaseModel):
    name: Optional[str] = None
    is_active: Optional[bool] = None
    email_verified: Optional[bool] = None


class BCCustomerSearchResponse(BaseModel):
    bc_customer_id: str
    company_name: Optional[str]
    contact_name: Optional[str]
    email: Optional[str]
    phone: Optional[str]
    already_linked: bool


class PendingCustomerResponse(BaseModel):
    id: int
    email: str
    name: Optional[str]
    company_name: Optional[str]
    phone: Optional[str]
    account_type: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class ApproveCustomerRequest(BaseModel):
    account_type: str  # 'dealer' or 'home_builder'


class UpdateAccountTypeRequest(BaseModel):
    account_type: str  # 'dealer' or 'home_builder'


# ============================================================================
# ENDPOINTS
# ============================================================================

@router.get("", response_model=List[CustomerListResponse])
def list_customers(
    current_admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """List all customer portal accounts"""
    customers = db.query(User).filter(User.user_type == 'CUSTOMER').all()

    result = []
    for customer in customers:
        # Get BC company name, multiplier, and pricing tier if linked
        bc_company_name = None
        bc_price_multiplier = None
        pricing_tier = None
        if customer.bc_customer_id:
            bc_customer = db.query(BCCustomer).filter(
                BCCustomer.bc_customer_id == customer.bc_customer_id
            ).first()
            if bc_customer:
                bc_company_name = bc_customer.company_name
                bc_price_multiplier = bc_customer.price_multiplier
                pricing_tier = bc_customer.pricing_tier

        # Count saved quotes
        saved_quotes_count = db.query(SavedQuoteConfig).filter(
            SavedQuoteConfig.user_id == customer.id
        ).count()

        result.append(CustomerListResponse(
            id=customer.id,
            email=customer.email,
            name=customer.name,
            is_active=customer.is_active,
            email_verified=customer.email_verified or False,
            bc_customer_id=customer.bc_customer_id,
            bc_company_name=bc_company_name,
            bc_price_multiplier=bc_price_multiplier,
            pricing_tier=pricing_tier,
            created_at=customer.created_at,
            last_login_at=customer.last_login_at,
            saved_quotes_count=saved_quotes_count
        ))

    return result


@router.get("/bc-customers", response_model=List[BCCustomerSearchResponse])
def search_bc_customers(
    q: Optional[str] = None,
    current_admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """Search BC customers for linking to portal accounts"""
    # Get all BC customers from cache
    bc_customers = db.query(BCCustomer).all()

    # Filter by search query if provided
    if q:
        q_lower = q.lower()
        bc_customers = [
            c for c in bc_customers
            if (c.company_name and q_lower in c.company_name.lower()) or
               (c.contact_name and q_lower in c.contact_name.lower()) or
               (c.email and q_lower in c.email.lower()) or
               (c.bc_customer_id and q_lower in c.bc_customer_id.lower())
        ]

    # Check which are already linked
    linked_ids = set(
        u.bc_customer_id for u in
        db.query(User).filter(User.bc_customer_id.isnot(None)).all()
    )

    result = []
    for bc in bc_customers[:50]:  # Limit results
        result.append(BCCustomerSearchResponse(
            bc_customer_id=bc.bc_customer_id,
            company_name=bc.company_name,
            contact_name=bc.contact_name,
            email=bc.email,
            phone=bc.phone,
            already_linked=bc.bc_customer_id in linked_ids
        ))

    return result


@router.post("/sync-bc-customers")
async def sync_bc_customers(
    current_admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """Trigger a sync of all BC customers to local cache, including price multipliers"""
    logger.info(f"Admin {current_admin.email} triggered BC customer sync")

    results = await bc_sync_service.sync_customers(db=db)

    return {
        "message": "BC customer sync complete",
        "customers_synced": results.get("customers_synced", 0),
        "customers_updated": results.get("customers_updated", 0),
        "errors": results.get("errors", [])
    }


@router.post("/bulk-create-from-bc")
def bulk_create_from_bc(
    current_admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """
    Bulk-create customer portal accounts from BC customer data.
    Skips Amazon customers, customers without email, and already-linked customers.
    Creates accounts silently (no welcome emails).
    """
    logger.info(f"Admin {current_admin.email} triggered bulk create from BC")

    # Load all BC customers
    bc_customers = db.query(BCCustomer).all()

    # Pre-load existing emails and linked bc_customer_ids for O(1) lookup
    existing_emails = set(
        u.email.lower() for u in db.query(User.email).all()
    )
    linked_bc_ids = set(
        u.bc_customer_id for u in
        db.query(User.bc_customer_id).filter(User.bc_customer_id.isnot(None)).all()
    )

    created = 0
    skipped_existing = 0
    skipped_no_email = 0
    skipped_amazon = 0
    created_customers = []
    errors = []

    for bc in bc_customers:
        try:
            # Skip Amazon customers
            if bc.company_name and "amazon" in bc.company_name.lower():
                skipped_amazon += 1
                continue

            # Skip if no email
            if not bc.email:
                skipped_no_email += 1
                continue

            # Skip if email already exists
            if bc.email.lower() in existing_emails:
                skipped_existing += 1
                continue

            # Skip if bc_customer_id already linked
            if bc.bc_customer_id in linked_bc_ids:
                skipped_existing += 1
                continue

            # Create user with unusable random password
            random_password = secrets.token_urlsafe(32)
            password_hash = auth_service.get_password_hash(random_password)

            user = User(
                email=bc.email.lower(),
                password_hash=password_hash,
                name=bc.contact_name or bc.company_name,
                role=UserRole.VIEWER,
                user_type='CUSTOMER',
                is_active=True,
                email_verified=True,
                bc_customer_id=bc.bc_customer_id
            )
            db.add(user)

            # Track for O(1) duplicate prevention within this batch
            existing_emails.add(bc.email.lower())
            linked_bc_ids.add(bc.bc_customer_id)

            created += 1
            created_customers.append({
                "email": bc.email,
                "name": bc.contact_name or bc.company_name,
                "company": bc.company_name,
                "bc_customer_id": bc.bc_customer_id
            })

        except Exception as e:
            errors.append({
                "bc_customer_id": bc.bc_customer_id,
                "company": bc.company_name,
                "error": str(e)
            })

    # Single commit for atomicity
    if created > 0:
        db.commit()

    logger.info(
        f"Bulk create complete: {created} created, {skipped_existing} existing, "
        f"{skipped_no_email} no email, {skipped_amazon} Amazon, {len(errors)} errors"
    )

    return {
        "created": created,
        "skipped_existing": skipped_existing,
        "skipped_no_email": skipped_no_email,
        "skipped_amazon": skipped_amazon,
        "created_customers": created_customers,
        "errors": errors
    }


@router.get("/pending", response_model=List[PendingCustomerResponse])
def list_pending_customers(
    current_admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """List all customers with pending account status"""
    pending = db.query(User).filter(
        User.user_type == 'CUSTOMER',
        User.account_status == 'pending'
    ).order_by(User.created_at.desc()).all()

    return [
        PendingCustomerResponse(
            id=c.id,
            email=c.email,
            name=c.name,
            company_name=c.company_name,
            phone=c.phone,
            account_type=c.account_type,
            created_at=c.created_at
        )
        for c in pending
    ]


@router.post("/{customer_id}/approve")
def approve_customer(
    customer_id: int,
    approve_data: ApproveCustomerRequest,
    current_admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """Approve a pending customer registration"""
    customer = db.query(User).filter(
        User.id == customer_id,
        User.user_type == 'CUSTOMER'
    ).first()

    if not customer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Customer not found"
        )

    if customer.account_status != 'pending':
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Customer account is already '{customer.account_status}', not pending"
        )

    # Validate account_type
    if approve_data.account_type not in ('dealer', 'home_builder'):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid account type. Must be 'dealer' or 'home_builder'"
        )

    customer.account_status = 'active'
    customer.account_type = approve_data.account_type
    customer.approved_by = current_admin.id
    customer.approved_at = datetime.utcnow()
    db.commit()
    db.refresh(customer)

    logger.info(f"Admin {current_admin.email} approved customer {customer.email} as {approve_data.account_type}")

    # Send welcome email to customer
    try:
        verification_link = None
        if not customer.email_verified and customer.email_verification_token:
            verification_link = f"{settings.CUSTOMER_PORTAL_URL}#/verify-email/{customer.email_verification_token}"

        notification_service.send_customer_welcome_email(
            customer_email=customer.email,
            customer_name=customer.name or "Customer",
            verification_link=verification_link
        )
    except Exception as e:
        logger.error(f"Failed to send welcome email to {customer.email}: {e}")

    return {
        "message": f"Customer {customer.email} approved successfully",
        "customer_id": customer.id,
        "account_type": customer.account_type,
        "account_status": customer.account_status
    }


@router.post("/{customer_id}/decline")
def decline_customer(
    customer_id: int,
    current_admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """Decline a pending customer registration"""
    customer = db.query(User).filter(
        User.id == customer_id,
        User.user_type == 'CUSTOMER'
    ).first()

    if not customer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Customer not found"
        )

    if customer.account_status != 'pending':
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Customer account is already '{customer.account_status}', not pending"
        )

    customer.account_status = 'declined'
    db.commit()
    db.refresh(customer)

    logger.info(f"Admin {current_admin.email} declined customer {customer.email}")

    # Optionally send decline notification
    try:
        notification_service.send_email(
            to_emails=[customer.email],
            subject="OPENDC Portal - Account Application Update",
            body=f"""
            <html>
            <body style="font-family: Arial, sans-serif; line-height: 1.6; max-width: 600px; margin: 0 auto;">
                <div style="background-color: #2563eb; color: white; padding: 20px; text-align: center;">
                    <h1 style="margin: 0;">OPENDC</h1>
                    <p style="margin: 5px 0 0 0;">Customer Portal</p>
                </div>
                <div style="padding: 30px;">
                    <h2 style="color: #1f2937;">Account Application Update</h2>
                    <p>Hi {customer.name or 'Customer'},</p>
                    <p>Thank you for your interest in the OPENDC Customer Portal. Unfortunately, we are unable to approve your account at this time.</p>
                    <p>If you believe this is an error or would like more information, please contact us at support@opendc.com.</p>
                    <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 30px 0;">
                    <p style="color: #6b7280; font-size: 14px;">
                        If you have any questions, please contact us at support@opendc.com
                    </p>
                </div>
            </body>
            </html>
            """
        )
    except Exception as e:
        logger.error(f"Failed to send decline notification to {customer.email}: {e}")

    return {
        "message": f"Customer {customer.email} declined",
        "customer_id": customer.id,
        "account_status": customer.account_status
    }


@router.patch("/{customer_id}/account-type")
def update_customer_account_type(
    customer_id: int,
    update_data: UpdateAccountTypeRequest,
    current_admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """Update the account type for a customer (admin only)"""
    customer = db.query(User).filter(
        User.id == customer_id,
        User.user_type == 'CUSTOMER'
    ).first()

    if not customer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Customer not found"
        )

    # Validate account_type
    if update_data.account_type not in ('dealer', 'home_builder'):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid account type. Must be 'dealer' or 'home_builder'"
        )

    old_type = customer.account_type
    customer.account_type = update_data.account_type
    db.commit()
    db.refresh(customer)

    logger.info(
        f"Admin {current_admin.email} changed account type for "
        f"{customer.email} from '{old_type}' to '{update_data.account_type}'"
    )

    return {
        "message": f"Account type updated to '{update_data.account_type}'",
        "customer_id": customer.id,
        "account_type": customer.account_type
    }


@router.get("/{customer_id}", response_model=CustomerDetailResponse)
def get_customer(
    customer_id: int,
    current_admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """Get customer details"""
    customer = db.query(User).filter(
        User.id == customer_id,
        User.user_type == 'CUSTOMER'
    ).first()

    if not customer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Customer not found"
        )

    # Get BC customer info if linked
    bc_company_name = None
    bc_price_multiplier = None
    pricing_tier = None
    bc_contact_name = None
    bc_email = None
    bc_phone = None

    if customer.bc_customer_id:
        bc_customer = db.query(BCCustomer).filter(
            BCCustomer.bc_customer_id == customer.bc_customer_id
        ).first()
        if bc_customer:
            bc_company_name = bc_customer.company_name
            bc_price_multiplier = bc_customer.price_multiplier
            pricing_tier = bc_customer.pricing_tier
            bc_contact_name = bc_customer.contact_name
            bc_email = bc_customer.email
            bc_phone = bc_customer.phone

    # Count quotes
    saved_quotes_count = db.query(SavedQuoteConfig).filter(
        SavedQuoteConfig.user_id == customer.id
    ).count()

    submitted_quotes_count = db.query(SavedQuoteConfig).filter(
        SavedQuoteConfig.user_id == customer.id,
        SavedQuoteConfig.is_submitted == True
    ).count()

    return CustomerDetailResponse(
        id=customer.id,
        email=customer.email,
        name=customer.name,
        is_active=customer.is_active,
        email_verified=customer.email_verified or False,
        bc_customer_id=customer.bc_customer_id,
        bc_company_name=bc_company_name,
        bc_price_multiplier=bc_price_multiplier,
        pricing_tier=pricing_tier,
        bc_contact_name=bc_contact_name,
        bc_email=bc_email,
        bc_phone=bc_phone,
        created_at=customer.created_at,
        last_login_at=customer.last_login_at,
        saved_quotes_count=saved_quotes_count,
        submitted_quotes_count=submitted_quotes_count
    )


@router.post("/{customer_id}/link", response_model=CustomerDetailResponse)
def link_customer_to_bc(
    customer_id: int,
    link_data: LinkCustomerRequest,
    current_admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """Link a customer portal account to a BC customer"""
    customer = db.query(User).filter(
        User.id == customer_id,
        User.user_type == 'CUSTOMER'
    ).first()

    if not customer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Customer not found"
        )

    # Verify BC customer exists
    bc_customer = db.query(BCCustomer).filter(
        BCCustomer.bc_customer_id == link_data.bc_customer_id
    ).first()

    if not bc_customer:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="BC customer not found"
        )

    # Check if already linked to another portal account
    existing_link = db.query(User).filter(
        User.bc_customer_id == link_data.bc_customer_id,
        User.id != customer_id
    ).first()

    if existing_link:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"BC customer is already linked to another portal account ({existing_link.email})"
        )

    # Update customer
    customer.bc_customer_id = link_data.bc_customer_id
    db.commit()
    db.refresh(customer)

    logger.info(f"Admin {current_admin.email} linked customer {customer.email} to BC customer {link_data.bc_customer_id}")

    return get_customer(customer_id, current_admin, db)


@router.post("/{customer_id}/unlink", response_model=CustomerDetailResponse)
def unlink_customer_from_bc(
    customer_id: int,
    current_admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """Unlink a customer portal account from BC customer"""
    customer = db.query(User).filter(
        User.id == customer_id,
        User.user_type == 'CUSTOMER'
    ).first()

    if not customer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Customer not found"
        )

    old_bc_id = customer.bc_customer_id
    customer.bc_customer_id = None
    db.commit()
    db.refresh(customer)

    logger.info(f"Admin {current_admin.email} unlinked customer {customer.email} from BC customer {old_bc_id}")

    return get_customer(customer_id, current_admin, db)


@router.patch("/{customer_id}", response_model=CustomerDetailResponse)
def update_customer(
    customer_id: int,
    update_data: UpdateCustomerRequest,
    current_admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """Update customer account details"""
    customer = db.query(User).filter(
        User.id == customer_id,
        User.user_type == 'CUSTOMER'
    ).first()

    if not customer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Customer not found"
        )

    if update_data.name is not None:
        customer.name = update_data.name

    if update_data.is_active is not None:
        customer.is_active = update_data.is_active

    if update_data.email_verified is not None:
        customer.email_verified = update_data.email_verified

    db.commit()
    db.refresh(customer)

    logger.info(f"Admin {current_admin.email} updated customer {customer.email}")

    return get_customer(customer_id, current_admin, db)


@router.post("", response_model=CustomerDetailResponse)
def create_customer(
    create_data: CreateCustomerRequest,
    current_admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """Create a new customer account (admin-created)"""
    # Check if email already exists
    existing = db.query(User).filter(User.email == create_data.email).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="An account with this email already exists"
        )

    # Verify BC customer if provided
    if create_data.bc_customer_id:
        bc_customer = db.query(BCCustomer).filter(
            BCCustomer.bc_customer_id == create_data.bc_customer_id
        ).first()
        if not bc_customer:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="BC customer not found"
            )

    # Create user
    password_hash = auth_service.get_password_hash(create_data.password)

    customer = User(
        email=create_data.email,
        password_hash=password_hash,
        name=create_data.name,
        role=UserRole.VIEWER,
        user_type='CUSTOMER',
        is_active=True,
        email_verified=True,  # Admin-created accounts are pre-verified
        bc_customer_id=create_data.bc_customer_id
    )

    db.add(customer)
    db.commit()
    db.refresh(customer)

    logger.info(f"Admin {current_admin.email} created customer account {customer.email}")

    return get_customer(customer.id, current_admin, db)


@router.patch("/{customer_id}/pricing-tier")
def update_customer_pricing_tier(
    customer_id: int,
    update_data: UpdatePricingTierRequest,
    current_admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """Set the pricing tier for a customer's linked BC account"""
    customer = db.query(User).filter(
        User.id == customer_id,
        User.user_type == 'CUSTOMER'
    ).first()

    if not customer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Customer not found"
        )

    if not customer.bc_customer_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Customer is not linked to a BC account"
        )

    bc_customer = db.query(BCCustomer).filter(
        BCCustomer.bc_customer_id == customer.bc_customer_id
    ).first()

    if not bc_customer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="BC customer record not found"
        )

    # Validate tier value
    valid_tiers = {"gold", "silver", "bronze", "retail"}
    tier = update_data.pricing_tier
    if tier is not None:
        tier = tier.lower().strip()
        if tier not in valid_tiers:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid pricing tier: {tier}. Must be one of: {', '.join(sorted(valid_tiers))}"
            )

    bc_customer.pricing_tier = tier
    db.commit()

    logger.info(
        f"Admin {current_admin.email} set pricing tier for "
        f"{bc_customer.company_name} ({bc_customer.bc_customer_id}) to '{tier}'"
    )

    return get_customer(customer_id, current_admin, db)


class SetPasswordRequest(BaseModel):
    new_password: str


@router.post("/{customer_id}/set-password")
def set_customer_password(
    customer_id: int,
    request: SetPasswordRequest,
    current_admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """Directly set a customer's password (admin use only)"""
    customer = db.query(User).filter(
        User.id == customer_id,
        User.user_type == 'CUSTOMER'
    ).first()

    if not customer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Customer not found"
        )

    if len(request.new_password) < 8:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must be at least 8 characters"
        )

    customer.password_hash = auth_service.get_password_hash(request.new_password)
    # Clear any pending reset token
    customer.password_reset_token = None
    customer.password_reset_expires = None
    db.commit()

    logger.info(f"Admin {current_admin.email} set password for customer {customer.email}")

    return {"message": "Password updated successfully"}


@router.delete("/{customer_id}")
def delete_customer(
    customer_id: int,
    current_admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """Delete a customer account"""
    customer = db.query(User).filter(
        User.id == customer_id,
        User.user_type == 'CUSTOMER'
    ).first()

    if not customer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Customer not found"
        )

    email = customer.email
    db.delete(customer)
    db.commit()

    logger.info(f"Admin {current_admin.email} deleted customer account {email}")

    return {"message": f"Customer account {email} deleted successfully"}


@router.get("/{customer_id}/activity")
def get_customer_activity(
    customer_id: int,
    current_admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """Get customer activity - saved quotes and orders"""
    customer = db.query(User).filter(
        User.id == customer_id,
        User.user_type == 'CUSTOMER'
    ).first()

    if not customer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Customer not found"
        )

    # Get saved quotes
    quotes = db.query(SavedQuoteConfig).filter(
        SavedQuoteConfig.user_id == customer.id
    ).order_by(SavedQuoteConfig.created_at.desc()).all()

    quotes_data = [
        {
            "id": q.id,
            "name": q.name,
            "status": "submitted" if q.is_submitted else "draft",
            "bc_quote_number": q.bc_quote_number,
            "created_at": q.created_at.isoformat() if q.created_at else None,
            "submitted_at": q.submitted_at.isoformat() if q.submitted_at else None,
        }
        for q in quotes
    ]

    # Get orders via bc_customer_id
    orders_data = []
    if customer.bc_customer_id:
        orders = db.query(SalesOrder).filter(
            SalesOrder.customer_id == customer.bc_customer_id
        ).order_by(SalesOrder.created_at.desc()).all()

        orders_data = [
            {
                "id": o.id,
                "bc_order_number": o.bc_order_number,
                "status": o.status.value,
                "total_amount": float(o.total_amount) if o.total_amount else None,
                "created_at": o.created_at.isoformat() if o.created_at else None,
            }
            for o in orders
        ]

    return {
        "quotes": quotes_data,
        "orders": orders_data,
        "last_login_at": customer.last_login_at.isoformat() if customer.last_login_at else None,
    }


@router.post("/{customer_id}/reset-password")
def admin_reset_password(
    customer_id: int,
    current_admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """Generate a password reset link for a customer (admin-initiated)"""
    customer = db.query(User).filter(
        User.id == customer_id,
        User.user_type == 'CUSTOMER'
    ).first()

    if not customer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Customer not found"
        )

    # Generate reset token with 1-hour expiry
    reset_token = secrets.token_urlsafe(32)
    customer.password_reset_token = reset_token
    customer.password_reset_expires = datetime.utcnow() + timedelta(hours=1)
    db.commit()

    reset_link = f"{settings.CUSTOMER_PORTAL_URL}#/reset-password/{reset_token}"

    logger.info(f"Admin {current_admin.email} generated password reset for customer {customer.email}")

    return {
        "reset_token": reset_token,
        "reset_link": reset_link,
        "expires_in_hours": 1,
    }
