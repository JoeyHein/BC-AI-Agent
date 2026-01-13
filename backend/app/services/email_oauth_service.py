"""
Email OAuth Service
Handles OAuth2 flow for connecting user email accounts to Microsoft Graph
"""

import logging
from datetime import datetime, timedelta
from typing import Optional
import requests
from sqlalchemy.orm import Session

from app.db.models import EmailConnection, User
from app.config import settings

logger = logging.getLogger(__name__)


class EmailOAuthService:
    """Service for OAuth2 email connection flow"""

    def __init__(self):
        self.tenant_id = settings.GRAPH_TENANT_ID
        self.client_id = settings.GRAPH_CLIENT_ID
        self.client_secret = settings.GRAPH_CLIENT_SECRET
        self.redirect_uri = "http://localhost:8000/api/email-connections/oauth/callback"  # TODO: Make configurable

    def get_authorization_url(self, state: str) -> str:
        """
        Get Microsoft OAuth authorization URL

        Args:
            state: Random state parameter for CSRF protection

        Returns:
            Authorization URL for user to visit
        """
        # Scopes needed for reading email
        scopes = [
            "openid",
            "profile",
            "email",
            "Mail.Read",
            "User.Read"
        ]

        scope_string = " ".join(scopes)

        auth_url = (
            f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/authorize?"
            f"client_id={self.client_id}&"
            f"response_type=code&"
            f"redirect_uri={self.redirect_uri}&"
            f"response_mode=query&"
            f"scope={scope_string}&"
            f"state={state}&"
            f"prompt=login"
        )

        return auth_url

    def exchange_code_for_tokens(self, code: str) -> Optional[dict]:
        """
        Exchange authorization code for access and refresh tokens

        Args:
            code: Authorization code from OAuth callback

        Returns:
            Dictionary with access_token, refresh_token, expires_in, etc.
        """
        token_url = f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/token"

        data = {
            'client_id': self.client_id,
            'client_secret': self.client_secret,
            'code': code,
            'redirect_uri': self.redirect_uri,
            'grant_type': 'authorization_code'
        }

        try:
            response = requests.post(token_url, data=data)
            response.raise_for_status()

            tokens = response.json()
            logger.info("Successfully exchanged code for tokens")
            return tokens

        except requests.RequestException as e:
            logger.error(f"Error exchanging code for tokens: {e}")
            if hasattr(e.response, 'text'):
                logger.error(f"Response: {e.response.text}")
            return None

    def refresh_access_token(self, refresh_token: str) -> Optional[dict]:
        """
        Refresh an expired access token using refresh token

        Args:
            refresh_token: Refresh token

        Returns:
            Dictionary with new access_token, expires_in, etc.
        """
        token_url = f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/token"

        data = {
            'client_id': self.client_id,
            'client_secret': self.client_secret,
            'refresh_token': refresh_token,
            'grant_type': 'refresh_token'
        }

        try:
            response = requests.post(token_url, data=data)
            response.raise_for_status()

            tokens = response.json()
            logger.info("Successfully refreshed access token")
            return tokens

        except requests.RequestException as e:
            logger.error(f"Error refreshing access token: {e}")
            return None

    def get_user_email(self, access_token: str) -> Optional[str]:
        """
        Get user's email address using access token

        Args:
            access_token: Access token

        Returns:
            User's email address
        """
        url = "https://graph.microsoft.com/v1.0/me"

        headers = {
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json'
        }

        try:
            response = requests.get(url, headers=headers)
            response.raise_for_status()

            user_info = response.json()
            email = user_info.get('userPrincipalName') or user_info.get('mail')

            logger.info(f"Retrieved email: {email}")
            return email

        except requests.RequestException as e:
            logger.error(f"Error getting user email: {e}")
            return None

    def save_email_connection(
        self,
        db: Session,
        user_id: int,
        email_address: str,
        access_token: str,
        refresh_token: Optional[str],
        expires_in: int
    ) -> EmailConnection:
        """
        Save email connection to database

        Args:
            db: Database session
            user_id: User ID
            email_address: Email address
            access_token: Access token
            refresh_token: Refresh token
            expires_in: Token expiration time in seconds

        Returns:
            EmailConnection object
        """
        # Calculate token expiration time
        token_expires_at = datetime.utcnow() + timedelta(seconds=expires_in)

        # Check if connection already exists for this email
        existing = db.query(EmailConnection).filter(
            EmailConnection.email_address == email_address
        ).first()

        if existing:
            # Update existing connection
            existing.user_id = user_id
            existing.access_token = access_token
            existing.refresh_token = refresh_token
            existing.token_expires_at = token_expires_at
            existing.is_active = True
            existing.last_sync_status = "connected"

            db.commit()
            db.refresh(existing)

            logger.info(f"Updated email connection: {email_address}")
            return existing

        # Create new connection
        connection = EmailConnection(
            user_id=user_id,
            email_address=email_address,
            access_token=access_token,
            refresh_token=refresh_token,
            token_expires_at=token_expires_at,
            is_active=True,
            last_sync_status="connected"
        )

        db.add(connection)
        db.commit()
        db.refresh(connection)

        logger.info(f"Created new email connection: {email_address}")
        return connection

    def disconnect_email(self, db: Session, connection_id: int, user_id: int) -> bool:
        """
        Disconnect an email connection

        Args:
            db: Database session
            connection_id: Connection ID
            user_id: User ID (for permission check)

        Returns:
            True if successful
        """
        connection = db.query(EmailConnection).filter(
            EmailConnection.id == connection_id,
            EmailConnection.user_id == user_id
        ).first()

        if not connection:
            logger.warning(f"Connection {connection_id} not found for user {user_id}")
            return False

        # Soft delete - mark as inactive
        connection.is_active = False
        connection.last_sync_status = "disconnected"

        db.commit()

        logger.info(f"Disconnected email: {connection.email_address}")
        return True


# Global instance
email_oauth_service = EmailOAuthService()
