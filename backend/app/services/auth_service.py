"""
Authentication Service
Handles user authentication, JWT tokens, and password hashing
"""

import logging
from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.db.models import User, UserRole
from app.config import settings

logger = logging.getLogger(__name__)

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# JWT settings
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 24 hours


class AuthService:
    """Service for user authentication and authorization"""

    @staticmethod
    def verify_password(plain_password: str, hashed_password: str) -> bool:
        """Verify a password against its hash"""
        return pwd_context.verify(plain_password, hashed_password)

    @staticmethod
    def get_password_hash(password: str) -> str:
        """Hash a password"""
        return pwd_context.hash(password)

    @staticmethod
    def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
        """Create a JWT access token"""
        to_encode = data.copy()

        if expires_delta:
            expire = datetime.utcnow() + expires_delta
        else:
            expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)

        to_encode.update({"exp": expire})
        encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=ALGORITHM)

        return encoded_jwt

    @staticmethod
    def decode_token(token: str) -> Optional[dict]:
        """Decode and validate a JWT token"""
        try:
            payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
            return payload
        except JWTError as e:
            logger.warning(f"JWT decode error: {e}")
            return None

    @staticmethod
    def authenticate_user(db: Session, email: str, password: str) -> Optional[User]:
        """Authenticate a user by email and password"""
        user = db.query(User).filter(User.email == email).first()

        if not user:
            logger.warning(f"Login attempt for non-existent user: {email}")
            return None

        if not user.is_active:
            logger.warning(f"Login attempt for inactive user: {email}")
            return None

        if not AuthService.verify_password(password, user.password_hash):
            logger.warning(f"Invalid password for user: {email}")
            return None

        # Update last login time
        user.last_login_at = datetime.utcnow()
        db.commit()

        logger.info(f"User authenticated successfully: {email}")
        return user

    @staticmethod
    def create_user(
        db: Session,
        email: str,
        password: str,
        name: str,
        role: UserRole = UserRole.VIEWER
    ) -> User:
        """Create a new user"""
        # Check if user already exists
        existing = db.query(User).filter(User.email == email).first()
        if existing:
            raise ValueError(f"User with email {email} already exists")

        # Hash password
        password_hash = AuthService.get_password_hash(password)

        # Create user
        user = User(
            email=email,
            password_hash=password_hash,
            name=name,
            role=role,
            is_active=True
        )

        db.add(user)
        db.commit()
        db.refresh(user)

        logger.info(f"User created: {email} with role {role.value}")
        return user

    @staticmethod
    def get_user_by_email(db: Session, email: str) -> Optional[User]:
        """Get user by email"""
        return db.query(User).filter(User.email == email).first()

    @staticmethod
    def get_user_by_id(db: Session, user_id: int) -> Optional[User]:
        """Get user by ID"""
        return db.query(User).filter(User.id == user_id).first()

    @staticmethod
    def check_permission(user: User, required_role: UserRole) -> bool:
        """Check if user has required permission level"""
        role_hierarchy = {
            UserRole.VIEWER: 0,
            UserRole.REVIEWER: 1,
            UserRole.ADMIN: 2
        }

        user_level = role_hierarchy.get(user.role, 0)
        required_level = role_hierarchy.get(required_role, 0)

        return user_level >= required_level


# Global instance
auth_service = AuthService()
