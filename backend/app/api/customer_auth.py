"""
Customer Portal Authentication API Endpoints
Self-registration, login, password reset for external customers
"""

import logging
import secrets
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr
from typing import Optional

from app.db.database import SessionLocal
from app.db.models import User, UserRole, BCCustomer
from app.services.auth_service import auth_service
from app.services.notification_service import notification_service
from app.config import settings

router = APIRouter(prefix="/api/customer", tags=["customer-auth"])
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


# Dependency to get current customer user from JWT token
def get_current_customer(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
) -> User:
    """Get current authenticated customer from JWT token"""
    token = credentials.credentials

    # Decode token
    payload = auth_service.decode_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Check that this is a customer token
    user_type = payload.get("user_type")
    if user_type != "customer":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Customer access required",
        )

    # Get user ID from token
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

    # Get user from database
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

    if user.user_type != 'CUSTOMER':
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Customer access required",
        )

    return user


# ============================================================================
# REQUEST/RESPONSE MODELS
# ============================================================================

class CustomerRegisterRequest(BaseModel):
    """Customer registration request"""
    email: EmailStr
    password: str
    name: str
    company_name: Optional[str] = None
    phone: Optional[str] = None


class CustomerLoginRequest(BaseModel):
    """Customer login request"""
    email: EmailStr
    password: str


class ForgotPasswordRequest(BaseModel):
    """Forgot password request"""
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    """Reset password request"""
    token: str
    new_password: str


class CustomerProfileUpdateRequest(BaseModel):
    """Update customer profile"""
    name: Optional[str] = None
    phone: Optional[str] = None


class CustomerTokenResponse(BaseModel):
    """JWT token response for customers"""
    access_token: str
    token_type: str = "bearer"
    user: dict


class CustomerResponse(BaseModel):
    """Customer user response"""
    id: int
    email: str
    name: Optional[str]
    is_active: bool
    email_verified: bool
    bc_customer_id: Optional[str]
    bc_company_name: Optional[str] = None
    created_at: datetime
    last_login_at: Optional[datetime]

    class Config:
        from_attributes = True


# ============================================================================
# ENDPOINTS
# ============================================================================

@router.post("/register", response_model=CustomerResponse)
def register_customer(
    register_data: CustomerRegisterRequest,
    db: Session = Depends(get_db)
):
    """
    Self-registration for customers.
    Creates a customer account that will be matched to BC customer by email.
    """
    # Check if user already exists
    existing = db.query(User).filter(User.email == register_data.email).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="An account with this email already exists"
        )

    # Hash password
    password_hash = auth_service.get_password_hash(register_data.password)

    # Generate email verification token
    verification_token = secrets.token_urlsafe(32)
    verification_expires = datetime.utcnow() + timedelta(hours=24)

    # Try to match with existing BC customer by email
    bc_customer = db.query(BCCustomer).filter(BCCustomer.email == register_data.email).first()
    bc_customer_id = bc_customer.bc_customer_id if bc_customer else None

    # Create customer user
    user = User(
        email=register_data.email,
        password_hash=password_hash,
        name=register_data.name,
        role=UserRole.VIEWER,  # Customers get viewer role
        user_type='CUSTOMER',
        is_active=True,
        email_verified=False,
        email_verification_token=verification_token,
        email_verification_expires=verification_expires,
        bc_customer_id=bc_customer_id
    )

    db.add(user)
    db.commit()
    db.refresh(user)

    logger.info(f"Customer registered: {register_data.email}, BC match: {bc_customer_id is not None}")

    # Send email notifications (async in background - don't block registration)
    try:
        # Build verification link
        verification_link = f"{settings.CUSTOMER_PORTAL_URL}#/verify-email/{verification_token}"

        # Send welcome email with verification link
        notification_service.send_customer_welcome_email(
            customer_email=register_data.email,
            customer_name=register_data.name,
            verification_link=verification_link
        )

        # Notify admins about new registration
        notification_service.notify_admins_new_customer(
            customer_email=register_data.email,
            customer_name=register_data.name,
            company_name=register_data.company_name,
            bc_matched=bc_customer_id is not None
        )
    except Exception as e:
        # Don't fail registration if email fails
        logger.error(f"Failed to send registration emails: {e}")

    return CustomerResponse(
        id=user.id,
        email=user.email,
        name=user.name,
        is_active=user.is_active,
        email_verified=user.email_verified,
        bc_customer_id=user.bc_customer_id,
        bc_company_name=bc_customer.company_name if bc_customer else None,
        created_at=user.created_at,
        last_login_at=user.last_login_at
    )


@router.post("/login", response_model=CustomerTokenResponse)
def login_customer(
    login_data: CustomerLoginRequest,
    db: Session = Depends(get_db)
):
    """Customer login - returns JWT with user_type: customer"""
    # Get user by email
    user = db.query(User).filter(User.email == login_data.email).first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Check if this is a customer account
    if user.user_type != 'CUSTOMER':
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="This is not a customer account. Please use the admin login.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is inactive"
        )

    # Verify password
    if not auth_service.verify_password(login_data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Update last login time
    user.last_login_at = datetime.utcnow()
    db.commit()

    # Get BC customer info if linked
    bc_company_name = None
    if user.bc_customer_id:
        bc_customer = db.query(BCCustomer).filter(
            BCCustomer.bc_customer_id == user.bc_customer_id
        ).first()
        if bc_customer:
            bc_company_name = bc_customer.company_name

    # Create access token with customer user_type
    access_token = auth_service.create_access_token(
        data={
            "sub": str(user.id),
            "user_type": "customer"
        }
    )

    logger.info(f"Customer logged in: {user.email}")

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "email": user.email,
            "name": user.name,
            "email_verified": user.email_verified,
            "bc_customer_id": user.bc_customer_id,
            "bc_company_name": bc_company_name
        }
    }


@router.get("/verify-email/{token}")
def verify_email(
    token: str,
    db: Session = Depends(get_db)
):
    """Verify customer email address"""
    user = db.query(User).filter(
        User.email_verification_token == token,
        User.user_type == 'CUSTOMER'
    ).first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid verification token"
        )

    if user.email_verification_expires < datetime.utcnow():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Verification token has expired"
        )

    user.email_verified = True
    user.email_verification_token = None
    user.email_verification_expires = None
    db.commit()

    logger.info(f"Customer email verified: {user.email}")

    return {"message": "Email verified successfully"}


@router.post("/forgot-password")
def forgot_password(
    request: ForgotPasswordRequest,
    db: Session = Depends(get_db)
):
    """Request password reset for customer account"""
    user = db.query(User).filter(
        User.email == request.email,
        User.user_type == 'CUSTOMER'
    ).first()

    # Always return success to prevent email enumeration
    if not user:
        return {"message": "If an account exists with this email, you will receive a password reset link"}

    # Generate reset token
    reset_token = secrets.token_urlsafe(32)
    reset_expires = datetime.utcnow() + timedelta(hours=1)

    user.password_reset_token = reset_token
    user.password_reset_expires = reset_expires
    db.commit()

    logger.info(f"Password reset requested for: {user.email}")

    # Send password reset email
    try:
        reset_link = f"{settings.CUSTOMER_PORTAL_URL}#/reset-password/{reset_token}"
        notification_service.send_password_reset_email(
            customer_email=user.email,
            customer_name=user.name or "Customer",
            reset_link=reset_link
        )
    except Exception as e:
        logger.error(f"Failed to send password reset email: {e}")

    return {"message": "If an account exists with this email, you will receive a password reset link"}


@router.post("/reset-password")
def reset_password(
    request: ResetPasswordRequest,
    db: Session = Depends(get_db)
):
    """Reset password using reset token"""
    user = db.query(User).filter(
        User.password_reset_token == request.token,
        User.user_type == 'CUSTOMER'
    ).first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid reset token"
        )

    if user.password_reset_expires < datetime.utcnow():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Reset token has expired"
        )

    # Update password
    user.password_hash = auth_service.get_password_hash(request.new_password)
    user.password_reset_token = None
    user.password_reset_expires = None
    db.commit()

    logger.info(f"Password reset completed for: {user.email}")

    return {"message": "Password reset successfully"}


@router.get("/me", response_model=CustomerResponse)
def get_current_customer_info(
    current_user: User = Depends(get_current_customer),
    db: Session = Depends(get_db)
):
    """Get current customer info"""
    # Get BC customer info if linked
    bc_company_name = None
    if current_user.bc_customer_id:
        bc_customer = db.query(BCCustomer).filter(
            BCCustomer.bc_customer_id == current_user.bc_customer_id
        ).first()
        if bc_customer:
            bc_company_name = bc_customer.company_name

    return CustomerResponse(
        id=current_user.id,
        email=current_user.email,
        name=current_user.name,
        is_active=current_user.is_active,
        email_verified=current_user.email_verified,
        bc_customer_id=current_user.bc_customer_id,
        bc_company_name=bc_company_name,
        created_at=current_user.created_at,
        last_login_at=current_user.last_login_at
    )


@router.patch("/me", response_model=CustomerResponse)
def update_customer_profile(
    profile_data: CustomerProfileUpdateRequest,
    current_user: User = Depends(get_current_customer),
    db: Session = Depends(get_db)
):
    """Update current customer profile"""
    if profile_data.name is not None:
        current_user.name = profile_data.name

    db.commit()
    db.refresh(current_user)

    # Get BC customer info if linked
    bc_company_name = None
    if current_user.bc_customer_id:
        bc_customer = db.query(BCCustomer).filter(
            BCCustomer.bc_customer_id == current_user.bc_customer_id
        ).first()
        if bc_customer:
            bc_company_name = bc_customer.company_name

    logger.info(f"Customer profile updated: {current_user.email}")

    return CustomerResponse(
        id=current_user.id,
        email=current_user.email,
        name=current_user.name,
        is_active=current_user.is_active,
        email_verified=current_user.email_verified,
        bc_customer_id=current_user.bc_customer_id,
        bc_company_name=bc_company_name,
        created_at=current_user.created_at,
        last_login_at=current_user.last_login_at
    )


@router.post("/change-password")
def change_password(
    old_password: str,
    new_password: str,
    current_user: User = Depends(get_current_customer),
    db: Session = Depends(get_db)
):
    """Change password for authenticated customer"""
    # Verify old password
    if not auth_service.verify_password(old_password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect"
        )

    # Update password
    current_user.password_hash = auth_service.get_password_hash(new_password)
    db.commit()

    logger.info(f"Password changed for customer: {current_user.email}")

    return {"message": "Password changed successfully"}
