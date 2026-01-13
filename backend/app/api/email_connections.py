"""
Email Connection API Endpoints
OAuth flow for connecting user email accounts
"""

import logging
import secrets
from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

from app.db.database import SessionLocal
from app.db.models import EmailConnection, User
from app.services.email_oauth_service import email_oauth_service
from app.api.auth import get_current_user

router = APIRouter(prefix="/api/email-connections", tags=["email-connections"])
logger = logging.getLogger(__name__)


# Dependency to get DB session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# In-memory state storage (TODO: Move to Redis for production)
oauth_states = {}


# ============================================================================
# REQUEST/RESPONSE MODELS
# ============================================================================

class EmailConnectionResponse(BaseModel):
    """Email connection response"""
    id: int
    email_address: str
    is_active: bool
    created_at: datetime
    last_checked_at: Optional[datetime]
    last_sync_status: Optional[str]

    class Config:
        from_attributes = True


# ============================================================================
# ENDPOINTS
# ============================================================================

@router.get("/oauth/start")
def start_oauth_flow(
    current_user: User = Depends(get_current_user)
):
    """
    Start OAuth flow to connect a new email account

    Returns authorization URL for user to visit Microsoft login
    """
    # Generate random state for CSRF protection
    state = secrets.token_urlsafe(32)

    # Store state with user ID (expires in 10 minutes)
    oauth_states[state] = {
        'user_id': current_user.id,
        'created_at': datetime.utcnow()
    }

    # Get authorization URL
    auth_url = email_oauth_service.get_authorization_url(state)

    return {
        "authorization_url": auth_url,
        "state": state
    }


@router.get("/oauth/callback")
async def oauth_callback(
    code: str = Query(..., description="Authorization code from Microsoft"),
    state: str = Query(..., description="State parameter for CSRF protection"),
    db: Session = Depends(get_db)
):
    """
    OAuth callback endpoint - handles redirect from Microsoft login

    This endpoint is called by Microsoft after user authorizes the app
    """
    # Validate state
    if state not in oauth_states:
        logger.error(f"Invalid or expired OAuth state: {state}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired state parameter"
        )

    state_data = oauth_states[state]
    user_id = state_data['user_id']

    # Clean up state
    del oauth_states[state]

    # Exchange code for tokens
    tokens = email_oauth_service.exchange_code_for_tokens(code)

    if not tokens:
        logger.error("Failed to exchange authorization code for tokens")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to connect email account"
        )

    # Get user's email address
    access_token = tokens.get('access_token')
    email_address = email_oauth_service.get_user_email(access_token)

    if not email_address:
        logger.error("Failed to retrieve user email address")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve email address"
        )

    # Save email connection
    try:
        connection = email_oauth_service.save_email_connection(
            db=db,
            user_id=user_id,
            email_address=email_address,
            access_token=access_token,
            refresh_token=tokens.get('refresh_token'),
            expires_in=tokens.get('expires_in', 3600)
        )

        logger.info(f"Email connection successful: {email_address}")

        # Redirect to frontend email settings page (port 3001, route /settings/email)
        return RedirectResponse(
            url=f"http://localhost:3001/settings/email?email_connected={email_address}",
            status_code=status.HTTP_302_FOUND
        )

    except Exception as e:
        logger.error(f"Error saving email connection: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save email connection"
        )


@router.get("", response_model=List[EmailConnectionResponse])
def list_email_connections(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    List all email connections for current user
    """
    connections = db.query(EmailConnection).filter(
        EmailConnection.user_id == current_user.id,
        EmailConnection.is_active == True
    ).all()

    return connections


@router.get("/all", response_model=List[EmailConnectionResponse])
def list_all_email_connections(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    List all active email connections (all users)

    For monitoring purposes
    """
    connections = db.query(EmailConnection).filter(
        EmailConnection.is_active == True
    ).all()

    return connections


@router.delete("/{connection_id}")
def disconnect_email(
    connection_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Disconnect an email connection
    """
    success = email_oauth_service.disconnect_email(
        db=db,
        connection_id=connection_id,
        user_id=current_user.id
    )

    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Email connection not found"
        )

    return {"message": "Email disconnected successfully"}


@router.post("/{connection_id}/refresh")
def refresh_email_token(
    connection_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Manually refresh an email connection token
    """
    connection = db.query(EmailConnection).filter(
        EmailConnection.id == connection_id,
        EmailConnection.user_id == current_user.id
    ).first()

    if not connection:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Email connection not found"
        )

    if not connection.refresh_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No refresh token available"
        )

    # Refresh token
    tokens = email_oauth_service.refresh_access_token(connection.refresh_token)

    if not tokens:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to refresh token"
        )

    # Update connection
    connection.access_token = tokens.get('access_token')
    if tokens.get('refresh_token'):
        connection.refresh_token = tokens.get('refresh_token')

    from datetime import timedelta
    connection.token_expires_at = datetime.utcnow() + timedelta(seconds=tokens.get('expires_in', 3600))

    db.commit()

    return {"message": "Token refreshed successfully"}
