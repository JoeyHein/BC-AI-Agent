"""
Authentication API Endpoints
Login, register, logout, and user management
"""

import logging
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime

from app.db.database import SessionLocal
from app.db.models import User, UserRole
from app.services.auth_service import auth_service

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
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
) -> User:
    """Get current authenticated user from JWT token"""
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

    return user


# Dependency to require admin role
def require_admin(current_user: User = Depends(get_current_user)) -> User:
    """Require admin role"""
    if not auth_service.check_permission(current_user, UserRole.ADMIN):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    return current_user


# Dependency to require reviewer role
def require_reviewer(current_user: User = Depends(get_current_user)) -> User:
    """Require reviewer role or higher"""
    if not auth_service.check_permission(current_user, UserRole.REVIEWER):
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
    name: Optional[str]
    role: str
    is_active: bool
    created_at: datetime
    last_login_at: Optional[datetime]

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

    # Create access token (sub must be string per JWT spec)
    access_token = auth_service.create_access_token(data={"sub": str(user.id)})

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "email": user.email,
            "name": user.name,
            "role": user.role.value
        }
    }


@router.post("/register", response_model=UserResponse)
def register(
    register_data: RegisterRequest,
    db: Session = Depends(get_db)
):
    """Register a new user (public endpoint for first admin)"""
    # Check if any users exist
    existing_users_count = db.query(User).count()

    # If this is the first user, make them admin
    if existing_users_count == 0:
        role = UserRole.ADMIN
        logger.info("Creating first admin user")
    else:
        # For subsequent users, require admin to create
        # For now, we'll allow self-registration as viewer
        role_str = register_data.role.lower()
        if role_str not in ["viewer", "reviewer", "admin"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid role. Must be viewer, reviewer, or admin"
            )
        role = UserRole[role_str.upper()]

        # Only allow viewer for self-registration
        if role != UserRole.VIEWER and existing_users_count > 0:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only admin can create users with elevated permissions"
            )

    try:
        user = auth_service.create_user(
            db=db,
            email=register_data.email,
            password=register_data.password,
            name=register_data.name,
            role=role
        )

        return user

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.get("/me", response_model=UserResponse)
def get_current_user_info(
    current_user: User = Depends(get_current_user)
):
    """Get current user info"""
    return current_user


@router.post("/logout")
def logout(current_user: User = Depends(get_current_user)):
    """Logout (client should discard token)"""
    return {"message": "Logged out successfully"}


@router.get("/users", response_model=list[UserResponse])
def list_users(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """List all users (admin only)"""
    users = db.query(User).all()
    return users


@router.post("/users", response_model=UserResponse)
def create_user(
    register_data: RegisterRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Create a new user (admin only)"""
    role_str = register_data.role.lower()
    if role_str not in ["viewer", "reviewer", "admin"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid role"
        )

    role = UserRole[role_str.upper()]

    try:
        user = auth_service.create_user(
            db=db,
            email=register_data.email,
            password=register_data.password,
            name=register_data.name,
            role=role
        )

        return user

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.delete("/users/{user_id}")
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Delete a user (admin only)"""
    # Don't allow deleting yourself
    if user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete your own account"
        )

    user = auth_service.get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    db.delete(user)
    db.commit()

    return {"message": f"User {user.email} deleted successfully"}
