"""
Microsoft Graph API Email Client for BC AI Agent
Uses Application Permissions for automated email monitoring
"""

import logging
from typing import Optional, Dict, List, Any
from datetime import datetime, timedelta
import msal
import requests

from app.config import settings

logger = logging.getLogger(__name__)


class GraphEmailClient:
    """Microsoft Graph API client for email operations with Application permissions"""

    def __init__(self):
        self.tenant_id = settings.GRAPH_TENANT_ID
        self.client_id = settings.GRAPH_CLIENT_ID
        self.client_secret = settings.GRAPH_CLIENT_SECRET

        self._token: Optional[str] = None
        self._token_expires_at: Optional[datetime] = None

        # MSAL Confidential Client for application permissions
        self.app: Optional[msal.ConfidentialClientApplication] = None

        if all([self.tenant_id, self.client_id, self.client_secret]):
            self._initialize_msal()
        else:
            logger.warning("Graph API credentials not configured. Email client will not authenticate.")

    def _initialize_msal(self):
        """Initialize MSAL application"""
        authority = f"https://login.microsoftonline.com/{self.tenant_id}"
        self.app = msal.ConfidentialClientApplication(
            self.client_id,
            authority=authority,
            client_credential=self.client_secret
        )
        logger.info("MSAL application initialized for Graph API")

    def _get_access_token(self) -> str:
        """Get valid access token (with caching)"""
        # Check if we have a valid cached token
        if self._token and self._token_expires_at:
            if datetime.utcnow() < self._token_expires_at - timedelta(minutes=5):
                return self._token

        # Acquire new token
        if not self.app:
            raise ValueError("MSAL app not initialized. Check Graph API credentials.")

        scope = ["https://graph.microsoft.com/.default"]

        result = self.app.acquire_token_for_client(scopes=scope)

        if "access_token" in result:
            self._token = result["access_token"]
            # Tokens typically expire in 1 hour
            self._token_expires_at = datetime.utcnow() + timedelta(seconds=result.get("expires_in", 3600))
            logger.info("Successfully acquired Graph API access token")
            return self._token
        else:
            error = result.get("error")
            error_description = result.get("error_description")
            logger.error(f"Failed to acquire Graph token: {error} - {error_description}")
            raise Exception(f"Authentication failed: {error}")

    def _make_request(self, method: str, endpoint: str, **kwargs) -> Dict[str, Any]:
        """Make authenticated request to Graph API"""
        token = self._get_access_token()

        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {token}"
        headers["Content-Type"] = "application/json"

        url = f"https://graph.microsoft.com/v1.0/{endpoint}"

        logger.debug(f"{method.upper()} {url}")

        response = requests.request(method, url, headers=headers, **kwargs)

        if response.status_code >= 400:
            logger.error(f"Graph API error {response.status_code}: {response.text}")
            response.raise_for_status()

        return response.json() if response.content else {}

    # ==================== Email Operations ====================

    def get_inbox_emails(self, user_email: str, max_count: int = 50,
                         filter_query: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get emails from user's inbox

        Args:
            user_email: User's email address (joey@opendc.ca)
            max_count: Maximum number of emails to retrieve
            filter_query: Optional OData filter query

        Returns:
            List of email messages
        """
        endpoint = f"users/{user_email}/mailFolders/inbox/messages"
        params = {
            "$top": max_count,
            "$orderby": "receivedDateTime desc"
        }

        if filter_query:
            params["$filter"] = filter_query

        result = self._make_request("GET", endpoint, params=params)
        return result.get("value", [])

    def get_email_by_id(self, user_email: str, message_id: str) -> Dict[str, Any]:
        """Get specific email by ID"""
        endpoint = f"users/{user_email}/messages/{message_id}"
        return self._make_request("GET", endpoint)

    def get_unread_emails(self, user_email: str, max_count: int = 50) -> List[Dict[str, Any]]:
        """Get unread emails from inbox"""
        filter_query = "isRead eq false"
        return self.get_inbox_emails(user_email, max_count, filter_query)

    def get_recent_emails(self, user_email: str, hours: int = 24, max_count: int = 50) -> List[Dict[str, Any]]:
        """Get emails received in the last N hours"""
        cutoff_date = datetime.utcnow() - timedelta(hours=hours)
        filter_query = f"receivedDateTime ge {cutoff_date.isoformat()}Z"
        return self.get_inbox_emails(user_email, max_count, filter_query)

    def mark_as_read(self, user_email: str, message_id: str) -> bool:
        """Mark email as read"""
        endpoint = f"users/{user_email}/messages/{message_id}"
        try:
            self._make_request("PATCH", endpoint, json={"isRead": True})
            logger.info(f"Marked email {message_id} as read")
            return True
        except Exception as e:
            logger.error(f"Failed to mark email as read: {e}")
            return False

    def move_to_folder(self, user_email: str, message_id: str, folder_id: str) -> bool:
        """Move email to a folder"""
        endpoint = f"users/{user_email}/messages/{message_id}/move"
        try:
            self._make_request("POST", endpoint, json={"destinationId": folder_id})
            logger.info(f"Moved email {message_id} to folder {folder_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to move email: {e}")
            return False

    def create_folder(self, user_email: str, folder_name: str, parent_folder_id: Optional[str] = None) -> Optional[str]:
        """Create a new mail folder

        Returns:
            Folder ID if successful, None otherwise
        """
        if parent_folder_id:
            endpoint = f"users/{user_email}/mailFolders/{parent_folder_id}/childFolders"
        else:
            endpoint = f"users/{user_email}/mailFolders"

        try:
            result = self._make_request("POST", endpoint, json={"displayName": folder_name})
            folder_id = result.get("id")
            logger.info(f"Created folder '{folder_name}': {folder_id}")
            return folder_id
        except Exception as e:
            logger.error(f"Failed to create folder: {e}")
            return None

    def get_folders(self, user_email: str) -> List[Dict[str, Any]]:
        """Get all mail folders"""
        endpoint = f"users/{user_email}/mailFolders"
        result = self._make_request("GET", endpoint)
        return result.get("value", [])

    def find_folder_by_name(self, user_email: str, folder_name: str) -> Optional[Dict[str, Any]]:
        """Find folder by display name"""
        folders = self.get_folders(user_email)
        for folder in folders:
            if folder.get("displayName") == folder_name:
                return folder
        return None

    # ==================== Draft Operations ====================

    def create_draft_reply(self, user_email: str, message_id: str, reply_content: str) -> Optional[str]:
        """Create a draft reply to an email

        Args:
            user_email: User's email address
            message_id: ID of email to reply to
            reply_content: HTML content of the reply

        Returns:
            Draft message ID if successful, None otherwise
        """
        endpoint = f"users/{user_email}/messages/{message_id}/createReply"

        try:
            result = self._make_request("POST", endpoint)
            draft_id = result.get("id")

            # Update draft with content
            if draft_id:
                update_endpoint = f"users/{user_email}/messages/{draft_id}"
                self._make_request("PATCH", update_endpoint, json={"body": {
                    "contentType": "HTML",
                    "content": reply_content
                }})

            logger.info(f"Created draft reply {draft_id} for message {message_id}")
            return draft_id
        except Exception as e:
            logger.error(f"Failed to create draft reply: {e}")
            return None

    # ==================== Sent Items ====================

    def get_sent_emails(self, user_email: str, days_back: int = 90, max_count: int = 100) -> List[Dict[str, Any]]:
        """Get sent emails for learning user's writing style

        Args:
            user_email: User's email address
            days_back: Number of days to look back
            max_count: Maximum number of emails

        Returns:
            List of sent email messages
        """
        cutoff_date = datetime.utcnow() - timedelta(days=days_back)
        endpoint = f"users/{user_email}/mailFolders/sentitems/messages"

        params = {
            "$top": max_count,
            "$orderby": "sentDateTime desc",
            "$filter": f"sentDateTime ge {cutoff_date.isoformat()}Z"
        }

        result = self._make_request("GET", endpoint, params=params)
        return result.get("value", [])

    # ==================== Test Connection ====================

    def test_connection(self, user_email: str) -> bool:
        """Test Graph API connectivity"""
        try:
            inbox = self.get_inbox_emails(user_email, max_count=1)
            logger.info(f"✅ Graph API connection successful for {user_email}")
            return True
        except Exception as e:
            logger.error(f"❌ Graph API connection failed: {e}")
            return False


# Global Graph client instance
graph_client = GraphEmailClient()
