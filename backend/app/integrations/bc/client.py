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

    def _fetch_raw_url(self, url: str) -> bytes:
        """Fetch raw bytes from a full URL (e.g. mediaReadLink). Used for PDF content streams."""
        token = self._get_access_token()

        headers = {"Authorization": f"Bearer {token}"}

        logger.debug(f"GET {url} (raw)")

        response = requests.get(url, headers=headers)

        if response.status_code >= 400:
            logger.error(f"BC API error {response.status_code}: {response.text}")
            response.raise_for_status()

        return response.content

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
        # Escape single quotes for OData filter
        safe_term = search_term.replace("'", "''")
        filter_query = f"contains(displayName,'{safe_term}')"
        result = self._make_request(
            "GET",
            f"companies({cid})/customers?$filter={filter_query}"
        )
        return result.get("value", [])

    # ==================== Customers with Price Multiplier ====================

    def get_customers_with_multiplier(self, company_id: Optional[str] = None,
                                       top: int = 1000) -> List[Dict[str, Any]]:
        """
        Get all customers including priceMultiplierPercent field.
        Falls back to standard customers endpoint if custom field isn't available.
        """
        cid = company_id or self.company_id
        result = self._make_request("GET", f"companies({cid})/customers?$top={top}")
        return result.get("value", [])

    def get_customer_with_multiplier(self, customer_id: str,
                                      company_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Get a single customer including priceMultiplierPercent field.
        """
        cid = company_id or self.company_id
        result = self._make_request("GET", f"companies({cid})/customers({customer_id})")
        return result

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
        """Search items by number (exact match)"""
        cid = company_id or self.company_id
        # BC doesn't support OR on distinct fields, so search by number first
        safe_term = search_term.replace("'", "''")
        filter_query = f"number eq '{safe_term}'"
        result = self._make_request(
            "GET",
            f"companies({cid})/items?$filter={filter_query}"
        )
        return result.get("value", [])

    def search_items_by_name(self, search_term: str, company_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Search items by display name (partial match)"""
        cid = company_id or self.company_id
        safe_term = search_term.replace("'", "''")
        filter_query = f"contains(displayName,'{safe_term}')"
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

    def delete_sales_quote(self, quote_id: str, company_id: Optional[str] = None) -> bool:
        """Delete a sales quote"""
        cid = company_id or self.company_id
        self._make_request("DELETE", f"companies({cid})/salesQuotes({quote_id})")
        logger.info(f"Deleted sales quote: {quote_id}")
        return True

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

    # ==================== Quote PDF (BC built-in) ====================

    def get_quote_pdf(self, quote_id: str, company_id: Optional[str] = None) -> bytes:
        """
        Download the PDF for a sales quote using BC's built-in PDF generation.

        BC v2.0 API two-step flow:
        1. GET .../pdfDocument → metadata with content@odata.mediaReadLink
        2. GET that mediaReadLink URL → binary PDF bytes

        Args:
            quote_id: The BC sales quote ID (GUID)
            company_id: Optional company ID

        Returns:
            PDF file content as bytes
        """
        cid = company_id or self.company_id
        endpoint = f"companies({cid})/salesQuotes({quote_id})/pdfDocument"

        # Step 1: get pdfDocument metadata (contains the mediaReadLink)
        result = self._make_request("GET", endpoint)

        doc = result.get("value", [result])[0] if result.get("value") else result
        content_url = (
            doc.get("content@odata.mediaReadLink")
            or doc.get("pdfDocumentContent@odata.mediaReadLink")
        )

        if not content_url:
            raise ValueError(f"No PDF mediaReadLink returned for quote {quote_id}")

        # Step 2: fetch binary PDF from the mediaReadLink
        logger.info(f"Fetching quote PDF from: {content_url}")
        pdf_bytes = self._fetch_raw_url(content_url)

        if not pdf_bytes:
            raise ValueError(f"Empty PDF content for quote {quote_id}")

        logger.info(f"Downloaded PDF for quote {quote_id} ({len(pdf_bytes)} bytes)")
        return pdf_bytes

    def download_quote_pdf_to_file(self, quote_id: str, output_path: str,
                                    company_id: Optional[str] = None) -> str:
        """
        Download quote PDF and save to a file.

        Args:
            quote_id: The BC sales quote ID (GUID)
            output_path: File path to save the PDF
            company_id: Optional company ID

        Returns:
            The output file path
        """
        pdf_bytes = self.get_quote_pdf(quote_id, company_id)

        with open(output_path, "wb") as f:
            f.write(pdf_bytes)

        logger.info(f"Saved quote PDF to {output_path}")
        return output_path

    # ==================== Order PDF (BC built-in) ====================

    def get_order_confirmation_pdf(self, order_id: str, company_id: Optional[str] = None) -> bytes:
        """
        Download the PDF for a sales order using BC's built-in PDF generation.

        Args:
            order_id: The BC sales order ID (GUID)
            company_id: Optional company ID

        Returns:
            PDF file content as bytes
        """
        cid = company_id or self.company_id
        endpoint = f"companies({cid})/salesOrders({order_id})/pdfDocument"

        # Step 1: get pdfDocument metadata (contains the mediaReadLink)
        result = self._make_request("GET", endpoint)

        doc = result.get("value", [result])[0] if result.get("value") else result
        content_url = (
            doc.get("content@odata.mediaReadLink")
            or doc.get("pdfDocumentContent@odata.mediaReadLink")
        )

        if not content_url:
            raise ValueError(f"No PDF mediaReadLink returned for order {order_id}")

        # Step 2: fetch binary PDF from the mediaReadLink
        logger.info(f"Fetching order PDF from: {content_url}")
        pdf_bytes = self._fetch_raw_url(content_url)

        if not pdf_bytes:
            raise ValueError(f"Empty PDF content for order {order_id}")

        logger.info(f"Downloaded PDF for order {order_id} ({len(pdf_bytes)} bytes)")
        return pdf_bytes

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

    # ==================== Sales Orders ====================

    def get_sales_orders(self, company_id: Optional[str] = None, top: int = 100,
                         status_filter: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get list of sales orders"""
        cid = company_id or self.company_id
        endpoint = f"companies({cid})/salesOrders?$top={top}"
        if status_filter:
            endpoint += f"&$filter=status eq '{status_filter}'"
        result = self._make_request("GET", endpoint)
        return result.get("value", [])

    def get_sales_order(self, order_id: str, company_id: Optional[str] = None) -> Dict[str, Any]:
        """Get specific sales order"""
        cid = company_id or self.company_id
        result = self._make_request("GET", f"companies({cid})/salesOrders({order_id})")
        return result

    def get_sales_order_by_number(self, order_number: str, company_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Get sales order by document number"""
        cid = company_id or self.company_id
        result = self._make_request(
            "GET",
            f"companies({cid})/salesOrders?$filter=number eq '{order_number}'"
        )
        orders = result.get("value", [])
        return orders[0] if orders else None

    def create_sales_order(self, order_data: Dict[str, Any], company_id: Optional[str] = None) -> Dict[str, Any]:
        """Create new sales order"""
        cid = company_id or self.company_id
        result = self._make_request(
            "POST",
            f"companies({cid})/salesOrders",
            json=order_data
        )
        logger.info(f"Created sales order: {result.get('number', 'N/A')}")
        return result

    def update_sales_order(self, order_id: str, order_data: Dict[str, Any],
                          company_id: Optional[str] = None) -> Dict[str, Any]:
        """Update existing sales order"""
        cid = company_id or self.company_id
        # Need to get etag for PATCH
        current = self.get_sales_order(order_id, cid)
        etag = current.get("@odata.etag")
        headers = {"If-Match": etag} if etag else {}
        result = self._make_request(
            "PATCH",
            f"companies({cid})/salesOrders({order_id})",
            json=order_data,
            headers=headers
        )
        return result

    # ==================== Sales Order Lines ====================

    def get_order_lines(self, order_id: str, company_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get lines for a sales order"""
        cid = company_id or self.company_id
        result = self._make_request("GET", f"companies({cid})/salesOrders({order_id})/salesOrderLines")
        return result.get("value", [])

    def add_order_line(self, order_id: str, line_data: Dict[str, Any],
                       company_id: Optional[str] = None) -> Dict[str, Any]:
        """Add line to sales order"""
        cid = company_id or self.company_id
        result = self._make_request(
            "POST",
            f"companies({cid})/salesOrders({order_id})/salesOrderLines",
            json=line_data
        )
        return result

    # ==================== Quote to Order Conversion ====================

    def convert_quote_to_order(self, quote_id: str, company_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Convert a sales quote to a sales order using the makeOrder bound action.

        This is a BC bound action that creates a new Sales Order from the Quote.
        The quote will be archived after conversion.

        Args:
            quote_id: The BC sales quote ID (GUID)
            company_id: Optional company ID

        Returns:
            The newly created sales order
        """
        cid = company_id or self.company_id

        # BC bound action: POST salesQuotes({id})/Microsoft.NAV.makeOrder
        result = self._make_request(
            "POST",
            f"companies({cid})/salesQuotes({quote_id})/Microsoft.NAV.makeOrder"
        )
        logger.info(f"Converted quote {quote_id} to order: {result.get('number', 'N/A')}")
        return result

    # ==================== Shipments ====================

    def get_sales_shipments(self, company_id: Optional[str] = None, top: int = 100) -> List[Dict[str, Any]]:
        """Get list of posted sales shipments"""
        cid = company_id or self.company_id
        result = self._make_request("GET", f"companies({cid})/salesShipments?$top={top}")
        return result.get("value", [])

    def get_sales_shipment(self, shipment_id: str, company_id: Optional[str] = None) -> Dict[str, Any]:
        """Get specific sales shipment"""
        cid = company_id or self.company_id
        result = self._make_request("GET", f"companies({cid})/salesShipments({shipment_id})")
        return result

    def get_shipments_for_order(self, order_number: str, company_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get shipments related to a sales order"""
        cid = company_id or self.company_id
        result = self._make_request(
            "GET",
            f"companies({cid})/salesShipments?$filter=orderNumber eq '{order_number}'"
        )
        return result.get("value", [])

    def ship_sales_order(self, order_id: str, company_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Ship a sales order using the ship bound action.
        Creates a posted shipment from the order.

        Args:
            order_id: The BC sales order ID (GUID)
            company_id: Optional company ID

        Returns:
            Result of ship action
        """
        cid = company_id or self.company_id
        result = self._make_request(
            "POST",
            f"companies({cid})/salesOrders({order_id})/Microsoft.NAV.ship"
        )
        logger.info(f"Shipped order {order_id}")
        return result

    def ship_and_invoice(self, order_id: str, company_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Ship and invoice a sales order in one action.
        Creates both posted shipment and posted invoice.

        Args:
            order_id: The BC sales order ID (GUID)
            company_id: Optional company ID

        Returns:
            Result of shipAndInvoice action
        """
        cid = company_id or self.company_id
        result = self._make_request(
            "POST",
            f"companies({cid})/salesOrders({order_id})/Microsoft.NAV.shipAndInvoice"
        )
        logger.info(f"Shipped and invoiced order {order_id}")
        return result

    # ==================== Sales Invoices ====================

    def get_sales_invoices(self, company_id: Optional[str] = None, top: int = 100,
                          status_filter: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get list of sales invoices (draft and posted)"""
        cid = company_id or self.company_id
        endpoint = f"companies({cid})/salesInvoices?$top={top}"
        if status_filter:
            endpoint += f"&$filter=status eq '{status_filter}'"
        result = self._make_request("GET", endpoint)
        return result.get("value", [])

    def get_sales_invoice(self, invoice_id: str, company_id: Optional[str] = None) -> Dict[str, Any]:
        """Get specific sales invoice"""
        cid = company_id or self.company_id
        result = self._make_request("GET", f"companies({cid})/salesInvoices({invoice_id})")
        return result

    def get_invoices_for_order(self, order_number: str, company_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get invoices related to a sales order"""
        cid = company_id or self.company_id
        result = self._make_request(
            "GET",
            f"companies({cid})/salesInvoices?$filter=orderNumber eq '{order_number}'"
        )
        return result.get("value", [])

    def create_sales_invoice(self, invoice_data: Dict[str, Any], company_id: Optional[str] = None) -> Dict[str, Any]:
        """Create a draft sales invoice"""
        cid = company_id or self.company_id
        result = self._make_request(
            "POST",
            f"companies({cid})/salesInvoices",
            json=invoice_data
        )
        logger.info(f"Created sales invoice: {result.get('number', 'N/A')}")
        return result

    def post_sales_invoice(self, invoice_id: str, company_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Post a draft sales invoice to the general ledger.

        This action finalizes the invoice - it cannot be edited after posting.

        Args:
            invoice_id: The BC sales invoice ID (GUID)
            company_id: Optional company ID

        Returns:
            The posted invoice
        """
        cid = company_id or self.company_id
        result = self._make_request(
            "POST",
            f"companies({cid})/salesInvoices({invoice_id})/Microsoft.NAV.post"
        )
        logger.info(f"Posted invoice {invoice_id}")
        return result

    # ==================== API Discovery ====================

    def discover_custom_apis(self, company_id: Optional[str] = None) -> Dict[str, List[str]]:
        """
        Discover available API endpoints in BC, including custom APIs.

        Useful for finding production order endpoints and other custom pages.

        Returns:
            Dict with 'standard' and 'custom' endpoint lists
        """
        cid = company_id or self.company_id
        discovered = {
            "standard": [],
            "custom": [],
            "production": []
        }

        # Standard v2.0 endpoints to test
        standard_endpoints = [
            "companies", "customers", "vendors", "items",
            "salesQuotes", "salesOrders", "salesInvoices", "salesShipments",
            "purchaseOrders", "purchaseInvoices",
            "generalLedgerEntries", "accounts", "dimensions"
        ]

        # Common production order endpoint patterns
        production_endpoints = [
            "productionOrders",
            "prodOrders",
            "manufacturingOrders",
            "productionBOMHeaders",
            "routings",
            "workCenters",
            "machineCenters"
        ]

        # Test standard endpoints
        for endpoint in standard_endpoints:
            try:
                self._make_request("GET", f"companies({cid})/{endpoint}?$top=1")
                discovered["standard"].append(endpoint)
            except Exception:
                pass  # Endpoint doesn't exist or no access

        # Test production endpoints
        for endpoint in production_endpoints:
            try:
                self._make_request("GET", f"companies({cid})/{endpoint}?$top=1")
                discovered["production"].append(endpoint)
                logger.info(f"Found production endpoint: {endpoint}")
            except Exception:
                pass

        logger.info(f"API Discovery complete. Standard: {len(discovered['standard'])}, "
                    f"Production: {len(discovered['production'])}")

        return discovered

    def get_metadata(self, company_id: Optional[str] = None) -> str:
        """
        Get API metadata (OData $metadata) which lists all available entities.

        Returns:
            XML metadata string
        """
        token = self._get_access_token()
        cid = company_id or self.company_id
        url = f"{self.base_url}/companies({cid})/$metadata"

        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/xml"
        }

        response = requests.get(url, headers=headers)
        response.raise_for_status()
        return response.text

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

    # ==================== Customer-Filtered Queries (Customer Portal) ====================

    def get_customer_quotes(self, bc_customer_id: str, company_id: Optional[str] = None,
                           top: int = 100) -> List[Dict[str, Any]]:
        """
        Get all sales quotes for a specific customer.

        Args:
            bc_customer_id: The BC customer ID
            company_id: Optional company ID

        Returns:
            List of sales quotes for the customer
        """
        cid = company_id or self.company_id
        result = self._make_request(
            "GET",
            f"companies({cid})/salesQuotes?$filter=customerId eq '{bc_customer_id}'&$top={top}&$orderby=documentDate desc"
        )
        return result.get("value", [])

    def get_customer_orders(self, bc_customer_id: str, company_id: Optional[str] = None,
                           top: int = 100) -> List[Dict[str, Any]]:
        """
        Get all sales orders for a specific customer.

        Args:
            bc_customer_id: The BC customer ID
            company_id: Optional company ID

        Returns:
            List of sales orders for the customer
        """
        cid = company_id or self.company_id
        result = self._make_request(
            "GET",
            f"companies({cid})/salesOrders?$filter=customerId eq '{bc_customer_id}'&$top={top}&$orderby=orderDate desc"
        )
        return result.get("value", [])

    def get_customer_invoices(self, bc_customer_id: str, company_id: Optional[str] = None,
                             top: int = 100) -> List[Dict[str, Any]]:
        """
        Get all sales invoices for a specific customer.

        Args:
            bc_customer_id: The BC customer ID
            company_id: Optional company ID

        Returns:
            List of sales invoices for the customer
        """
        cid = company_id or self.company_id
        result = self._make_request(
            "GET",
            f"companies({cid})/salesInvoices?$filter=customerId eq '{bc_customer_id}'&$top={top}&$orderby=invoiceDate desc"
        )
        return result.get("value", [])

    def get_customer_shipments(self, bc_customer_id: str, company_id: Optional[str] = None,
                              top: int = 100) -> List[Dict[str, Any]]:
        """
        Get all sales shipments for a specific customer.

        Args:
            bc_customer_id: The BC customer ID
            company_id: Optional company ID

        Returns:
            List of sales shipments for the customer
        """
        cid = company_id or self.company_id
        # Note: Shipments may need to be filtered differently based on BC setup
        # This filters by sellToCustomerNumber if available
        result = self._make_request(
            "GET",
            f"companies({cid})/salesShipments?$filter=customerId eq '{bc_customer_id}'&$top={top}&$orderby=shipmentDate desc"
        )
        return result.get("value", [])

    def get_customer_order_details(self, order_id: str, bc_customer_id: str,
                                   company_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Get sales order details with verification that it belongs to the customer.

        Args:
            order_id: The BC sales order ID (GUID)
            bc_customer_id: The BC customer ID for verification
            company_id: Optional company ID

        Returns:
            Sales order details or None if not found/not owned by customer
        """
        cid = company_id or self.company_id

        try:
            order = self.get_sales_order(order_id, cid)

            # Verify customer ownership
            if order.get("customerId") != bc_customer_id:
                logger.warning(f"Customer {bc_customer_id} attempted to access order {order_id} belonging to another customer")
                return None

            # Get order lines
            lines = self.get_order_lines(order_id, cid)
            order["lines"] = lines

            # Get related shipments by order number
            order_number = order.get("number")
            if order_number:
                shipments = self.get_shipments_for_order(order_number, cid)
                order["shipments"] = shipments

                # Get related invoices
                invoices = self.get_invoices_for_order(order_number, cid)
                order["invoices"] = invoices

            return order

        except Exception as e:
            logger.error(f"Error fetching customer order details: {e}")
            return None


# Global BC client instance
bc_client = BusinessCentralClient()
