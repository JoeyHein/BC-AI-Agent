"""
Upwardor Portal API Client
Integrates with Upwardor door configurator portal to get product data and pricing
"""

import requests
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


class UpwardorAPIError(Exception):
    """Custom exception for Upwardor API errors"""
    pass


class UpwardorAPIClient:
    """Client for interacting with the Upwardor Portal API"""

    def __init__(self, base_url: str = "http://195.35.8.196:6100"):
        self.base_url = base_url
        self.session = requests.Session()
        self.access_token: Optional[str] = None
        self.token_expiry: Optional[datetime] = None

    def login(self, email: str, password: str) -> Dict[str, Any]:
        """
        Login to Upwardor Portal and get access token

        Args:
            email: User email
            password: User password

        Returns:
            User data and company information

        Raises:
            UpwardorAPIError: If login fails
        """
        url = f"{self.base_url}/user/login"

        try:
            response = self.session.post(
                url,
                json={"email": email, "password": password},
                headers={"Content-Type": "application/json"},
                timeout=10
            )

            if response.status_code != 200:
                raise UpwardorAPIError(
                    f"Login failed: {response.status_code} - {response.text}"
                )

            data = response.json()

            # Extract and store access token - try different possible field names
            token_fields = ['access_token', 'accessToken', 'token', 'jwt', 'auth_token']
            for field in token_fields:
                if field in data:
                    self.access_token = data[field]
                    logger.info(f"Found token in field: {field}")
                    break
                # Also check if token is nested in a 'data' or 'result' field
                if 'data' in data and isinstance(data['data'], dict) and field in data['data']:
                    self.access_token = data['data'][field]
                    logger.info(f"Found token in data.{field}")
                    break

            if not self.access_token:
                # Log the response to help debug
                logger.error(f"Login response keys: {list(data.keys())}")
                logger.error(f"Full response: {data}")
                raise UpwardorAPIError(
                    f"No access token found in login response. Available keys: {list(data.keys())}"
                )

            # Set token expiry (default to 24 hours if not specified)
            self.token_expiry = datetime.now() + timedelta(hours=24)

            logger.info(f"Successfully logged in to Upwardor Portal as {email}")

            return data

        except requests.RequestException as e:
            raise UpwardorAPIError(f"Login request failed: {str(e)}")

    def ensure_authenticated(self):
        """Check if we have a valid token, raise error if not"""
        if not self.access_token:
            raise UpwardorAPIError("Not authenticated. Call login() first.")

        if self.token_expiry and datetime.now() >= self.token_expiry:
            raise UpwardorAPIError("Token expired. Call login() again.")

    def get_user_detail(self, user_id: str) -> Dict[str, Any]:
        """
        Get user/company details

        Args:
            user_id: User ID

        Returns:
            User and company details

        Raises:
            UpwardorAPIError: If request fails
        """
        self.ensure_authenticated()

        url = f"{self.base_url}/admin/user/detail"

        try:
            response = self.session.get(
                url,
                params={"id": user_id},
                headers={
                    "Authorization": f"Bearer {self.access_token}",
                    "Content-Type": "application/json"
                },
                timeout=10
            )

            if response.status_code != 200:
                raise UpwardorAPIError(
                    f"Get user detail failed: {response.status_code} - {response.text}"
                )

            return response.json()

        except requests.RequestException as e:
            raise UpwardorAPIError(f"User detail request failed: {str(e)}")

    def get_door_products(self) -> List[Dict[str, Any]]:
        """
        Get available door products/configurations

        Note: This endpoint needs to be discovered by navigating the portal

        Returns:
            List of door products

        Raises:
            UpwardorAPIError: If request fails
        """
        self.ensure_authenticated()

        # TODO: Update with actual endpoint once discovered
        # Possible endpoints to try:
        # - /api/products
        # - /api/doors
        # - /api/catalog
        # - /admin/products/list

        raise NotImplementedError(
            "Door products endpoint not yet discovered. "
            "Navigate to products/doors section in portal and capture the API call."
        )

    def get_door_pricing(self, door_config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Get pricing for a specific door configuration

        Args:
            door_config: Door configuration details

        Returns:
            Pricing information

        Raises:
            UpwardorAPIError: If request fails
        """
        self.ensure_authenticated()

        # TODO: Update with actual endpoint once discovered
        # Possible endpoints to try:
        # - /api/pricing/calculate
        # - /api/quote/calculate
        # - /admin/pricing/get

        raise NotImplementedError(
            "Pricing endpoint not yet discovered. "
            "Configure a door and get a quote in the portal, then capture the API call."
        )

    def validate_door_configuration(self, door_config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate a door configuration against Upwardor's product catalog

        Args:
            door_config: Door configuration to validate

        Returns:
            Validation results with any errors or warnings
        """
        # TODO: Implement once we have product catalog endpoint
        raise NotImplementedError("Validation endpoint not yet discovered")


# Singleton instance for the application
_upwardor_client: Optional[UpwardorAPIClient] = None


def get_upwardor_client() -> UpwardorAPIClient:
    """Get or create the Upwardor API client singleton"""
    global _upwardor_client

    if _upwardor_client is None:
        _upwardor_client = UpwardorAPIClient()

        # Auto-login with credentials from environment or config
        # TODO: Move credentials to environment variables
        try:
            _upwardor_client.login(
                email="opentest@yopmail.com",
                password="Welcome@123"
            )
            logger.info("Upwardor client auto-authenticated successfully")
        except UpwardorAPIError as e:
            logger.warning(f"Failed to auto-authenticate Upwardor client: {e}")

    return _upwardor_client
