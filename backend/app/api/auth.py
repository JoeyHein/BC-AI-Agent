"""
Authentication API Endpoints
Login, register, logout, and user management
"""

import logging
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime

from app.api.staff_principal import service_user_if_key
from app.db.database import SessionLocal
from app.db.models import User, UserRole
from app.services.auth_service import auth_service
from app.services.staff_permissions import (
    enforce_staff_permission,
    has_permission,
    serialize_user,
)

router = APIRouter(prefix="/api/auth", tags=["authentication"])
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


# Dependency to get current user from JWT token
def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
) -> User:
    """Get current authenticated user from a JWT, or from a staff service key.

    Service keys (prefix ``osk_``) resolve to the automation identity when
    the route is in the key's scopes. Any other bearer token follows the
    JWT checks below, unchanged.
    """
    service_user = service_user_if_key(request, credentials, db)
    if service_user is not None:
        return service_user

    token = credentials.credentials

    # Decode token
    payload = auth_service.decode_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Get user ID from token (convert from string to int)
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

    enforce_staff_permission(request, user)
    return user


# Dependency to require admin role
def require_admin(current_user: User = Depends(get_current_user)) -> User:
    """Users, settings, and service keys. Owner and admin presets, or a custom grant."""
    if not has_permission(current_user, "users.manage"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    return current_user


def require_reviewer(current_user: User = Depends(get_current_user)) -> User:
    """Quote, order, or purchasing changes. The route's own permission still applies."""
    if not (
        has_permission(current_user, "quotes.edit")
        or has_permission(current_user, "sales_orders.edit")
        or has_permission(current_user, "purchase_orders.edit")
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Reviewer access required"
        )
    return current_user


# ============================================================================
# REQUEST/RESPONSE MODELS
# ============================================================================

class LoginRequest(BaseModel):
    """Login request"""
    email: EmailStr
    password: str


class RegisterRequest(BaseModel):
    """Registration request"""
    email: EmailStr
    password: str
    name: str
    role: Optional[str] = "viewer"  # admin, reviewer, viewer


class TokenResponse(BaseModel):
    """JWT token response"""
    access_token: str
    token_type: str = "bearer"
    user: dict


class UserResponse(BaseModel):
    """User response"""
    id: int
    email: str
    name: Optional[str] = None
    role: str
    is_active: bool
    created_at: Optional[datetime] = None
    last_login_at: Optional[datetime] = None
    permissions: dict = {}
    permissions_custom: bool = False
    invite_pending: bool = False

    class Config:
        from_attributes = True


# ============================================================================
# ENDPOINTS
# ============================================================================

@router.post("/login", response_model=TokenResponse)
def login(
    login_data: LoginRequest,
    db: Session = Depends(get_db)
):
    """Login with email and password"""
    # Authenticate user
    user = auth_service.authenticate_user(db, login_data.email, login_data.password)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account is disabled.",
        )

    # Create access token (sub must be string per JWT spec)
    access_token = auth_service.create_access_token(data={"sub": str(user.id)})

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": serialize_user(user),
    }


@router.post("/register", response_model=UserResponse)
def register(
    register_data: RegisterRequest,
    db: Session = Depends(get_db)
):
    """Create the first staff admin when the users table is empty.

    After that, staff accounts are invited from Settings. Customer signup
    stays on /api/customer/register.
    """
    if db.query(User).count() > 0:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Staff accounts are created by an administrator. Ask an owner to send you a setup link.",
        )

    logger.info("Creating first admin user")
    try:
        user = auth_service.create_user(
            db=db,
            email=register_data.email,
            password=register_data.password,
            name=register_data.name,
            role=UserRole.ADMIN,
        )
        return serialize_user(user)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.get("/me", response_model=UserResponse)
def get_current_user_info(
    current_user: User = Depends(get_current_user)
):
    """Get current user info, including the permissions the nav should use."""
    return serialize_user(current_user)


@router.post("/logout")
def logout(current_user: User = Depends(get_current_user)):
    """Logout (client should discard token)"""
    return {"message": "Logged out successfully"}


from app.api.staff_users import register_staff_routes

register_staff_routes(router, get_db, get_current_user)
