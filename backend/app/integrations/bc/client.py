"""
Business Central API Client with OAuth 2.0 Authentication
"""

import logging
from typing import Optional, Dict, List, Any
import msal
import requests
from datetime import datetime, timedelta

from app.config import settings

logger = logging.getLogger(__name__)


class BusinessCentralClient:
    """Business Central API client with OAuth 2.0 authentication"""

    def __init__(self):
        self.tenant_id = settings.BC_TENANT_ID
        self.client_id = settings.BC_CLIENT_ID
        self.client_secret = settings.BC_CLIENT_SECRET
        self.base_url = settings.bc_api_url
        self.company_id = settings.BC_COMPANY_ID

        self._token: Optional[str] = None
        self._token_expires_at: Optional[datetime] = None

        # MSAL Confidential Client
        self.app: Optional[msal.ConfidentialClientApplication] = None

        if all([self.tenant_id, self.client_id, self.client_secret]):
            self._initialize_msal()
        else:
            logger.warning("BC credentials not configured. Client will not authenticate.")

    def _initialize_msal(self):
        """Initialize MSAL application"""
        authority = f"https://login.microsoftonline.com/{self.tenant_id}"
        self.app = msal.ConfidentialClientApplication(
            self.client_id,
            authority=authority,
            client_credential=self.client_secret
        )
        logger.info("MSAL application initialized for BC authentication")

    def _get_access_token(self) -> str:
        """Get valid access token (with caching)"""
        # Check if we have a valid cached token
        if self._token and self._token_expires_at:
            if datetime.utcnow() < self._token_expires_at - timedelta(minutes=5):
                return self._token

        # Acquire new token
        if not self.app:
            raise ValueError("MSAL app not initialized. Check BC credentials.")

        scope = ["https://api.businesscentral.dynamics.com/.default"]

        result = self.app.acquire_token_for_client(scopes=scope)

        if "access_token" in result:
            self._token = result["access_token"]
            # Tokens typically expire in 1 hour
            self._token_expires_at = datetime.utcnow() + timedelta(seconds=result.get("expires_in", 3600))
            logger.info("Successfully acquired BC access token")
            return self._token
        else:
            error = result.get("error")
            error_description = result.get("error_description")
            logger.error(f"Failed to acquire BC token: {error} - {error_description}")
            raise Exception(f"Authentication failed: {error}")

    def _make_request(self, method: str, endpoint: str, **kwargs) -> Dict[str, Any]:
        """Make authenticated request to BC API"""
        token = self._get_access_token()

        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {token}"
        headers["Content-Type"] = "application/json"

        url = f"{self.base_url}/{endpoint}"

        logger.debug(f"{method.upper()} {url}")

        response = requests.request(method, url, headers=headers, **kwargs)

        if response.status_code >= 400:
            logger.error(f"BC API error {response.status_code}: {response.text}")
            response.raise_for_status()

        return response.json() if response.content else {}

    # ==================== Companies ====================

    def get_companies(self) -> List[Dict[str, Any]]:
        """Get list of companies"""
        result = self._make_request("GET", "companies")
        return result.get("value", [])

    def get_company(self, company_id: Optional[str] = None) -> Dict[str, Any]:
        """Get specific company details"""
        cid = company_id or self.company_id
        if not cid:
            raise ValueError("Company ID not provided")

        result = self._make_request("GET", f"companies({cid})")
        return result

    # ==================== Customers ====================

    def get_customers(self, company_id: Optional[str] = None, top: int = 100) -> List[Dict[str, Any]]:
        """Get list of customers"""
        cid = company_id or self.company_id
        result = self._make_request("GET", f"companies({cid})/customers?$top={top}")
        return result.get("value", [])

    def get_customer(self, customer_id: str, company_id: Optional[str] = None) -> Dict[str, Any]:
        """Get specific customer"""
        cid = company_id or self.company_id
        result = self._make_request("GET", f"companies({cid})/customers({customer_id})")
        return result

    def search_customers(self, search_term: str, company_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Search customers by name or number"""
        cid = company_id or self.company_id
        filter_query = f"contains(displayName,'{search_term}') or contains(number,'{search_term}')"
        result = self._make_request(
            "GET",
            f"companies({cid})/customers?$filter={filter_query}"
        )
        return result.get("value", [])

    # ==================== Items ====================

    def get_items(self, company_id: Optional[str] = None, top: int = 100) -> List[Dict[str, Any]]:
        """Get list of items/products"""
        cid = company_id or self.company_id
        result = self._make_request("GET", f"companies({cid})/items?$top={top}")
        return result.get("value", [])

    def get_item(self, item_id: str, company_id: Optional[str] = None) -> Dict[str, Any]:
        """Get specific item"""
        cid = company_id or self.company_id
        result = self._make_request("GET", f"companies({cid})/items({item_id})")
        return result

    def search_items(self, search_term: str, company_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Search items by number or description"""
        cid = company_id or self.company_id
        filter_query = f"contains(displayName,'{search_term}') or contains(number,'{search_term}')"
        result = self._make_request(
            "GET",
            f"companies({cid})/items?$filter={filter_query}"
        )
        return result.get("value", [])

    # ==================== Sales Quotes ====================

    def get_sales_quotes(self, company_id: Optional[str] = None, top: int = 100) -> List[Dict[str, Any]]:
        """Get list of sales quotes"""
        cid = company_id or self.company_id
        result = self._make_request("GET", f"companies({cid})/salesQuotes?$top={top}")
        return result.get("value", [])

    def get_sales_quote(self, quote_id: str, company_id: Optional[str] = None) -> Dict[str, Any]:
        """Get specific sales quote"""
        cid = company_id or self.company_id
        result = self._make_request("GET", f"companies({cid})/salesQuotes({quote_id})")
        return result

    def create_sales_quote(self, quote_data: Dict[str, Any], company_id: Optional[str] = None) -> Dict[str, Any]:
        """Create new sales quote (draft)"""
        cid = company_id or self.company_id
        result = self._make_request(
            "POST",
            f"companies({cid})/salesQuotes",
            json=quote_data
        )
        logger.info(f"Created sales quote: {result.get('number', 'N/A')}")
        return result

    def update_sales_quote(self, quote_id: str, quote_data: Dict[str, Any], company_id: Optional[str] = None) -> Dict[str, Any]:
        """Update existing sales quote"""
        cid = company_id or self.company_id
        result = self._make_request(
            "PATCH",
            f"companies({cid})/salesQuotes({quote_id})",
            json=quote_data
        )
        return result

    # ==================== Sales Quote Lines ====================

    def get_quote_lines(self, quote_id: str, company_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get lines for a sales quote"""
        cid = company_id or self.company_id
        result = self._make_request("GET", f"companies({cid})/salesQuotes({quote_id})/salesQuoteLines")
        return result.get("value", [])

    def add_quote_line(self, quote_id: str, line_data: Dict[str, Any], company_id: Optional[str] = None) -> Dict[str, Any]:
        """Add line to sales quote"""
        cid = company_id or self.company_id
        result = self._make_request(
            "POST",
            f"companies({cid})/salesQuotes({quote_id})/salesQuoteLines",
            json=line_data
        )
        return result

    # ==================== Vendors ====================

    def get_vendors(self, company_id: Optional[str] = None, top: int = 100) -> List[Dict[str, Any]]:
        """Get list of vendors"""
        cid = company_id or self.company_id
        result = self._make_request("GET", f"companies({cid})/vendors?$top={top}")
        return result.get("value", [])

    # ==================== Purchase Orders ====================

    def get_purchase_orders(self, company_id: Optional[str] = None, top: int = 100) -> List[Dict[str, Any]]:
        """Get list of purchase orders"""
        cid = company_id or self.company_id
        result = self._make_request("GET", f"companies({cid})/purchaseOrders?$top={top}")
        return result.get("value", [])

    # ==================== Test Connection ====================

    def test_connection(self) -> bool:
        """Test BC API connectivity"""
        try:
            companies = self.get_companies()
            logger.info(f"✅ BC connection successful. Found {len(companies)} companies.")
            return True
        except Exception as e:
            logger.error(f"❌ BC connection failed: {e}")
            return False


# Global BC client instance
bc_client = BusinessCentralClient()
