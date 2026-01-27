"""
Admin Customer Management API Endpoints
Manage customer portal accounts from the admin interface
"""

import logging
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr
from typing import Optional, List

from app.db.database import SessionLocal
from app.db.models import User, UserRole, BCCustomer, SavedQuoteConfig
from app.services.auth_service import auth_service
from app.integrations.bc.client import bc_client

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
    bc_contact_name: Optional[str]
    bc_email: Optional[str]
    bc_phone: Optional[str]
    created_at: datetime
    last_login_at: Optional[datetime]
    saved_quotes_count: int
    submitted_quotes_count: int

    class Config:
        from_attributes = True


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
        # Get BC company name if linked
        bc_company_name = None
        if customer.bc_customer_id:
            bc_customer = db.query(BCCustomer).filter(
                BCCustomer.bc_customer_id == customer.bc_customer_id
            ).first()
            if bc_customer:
                bc_company_name = bc_customer.company_name

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
    bc_contact_name = None
    bc_email = None
    bc_phone = None

    if customer.bc_customer_id:
        bc_customer = db.query(BCCustomer).filter(
            BCCustomer.bc_customer_id == customer.bc_customer_id
        ).first()
        if bc_customer:
            bc_company_name = bc_customer.company_name
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
