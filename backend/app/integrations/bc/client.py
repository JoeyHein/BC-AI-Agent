"""
Business Central API Client with OAuth 2.0 Authentication
"""

import logging
from typing import Optional, Dict, List, Any
from urllib.parse import quote
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
        self.odata_url = settings.bc_odata_url
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
        """Initialize MSAL application. Tolerates invalid credentials (e.g. CI
        test env vars) by falling back to the unauthenticated state — real API
        calls will still fail, but module import succeeds. Catches broadly
        because MSAL's exception types vary across versions."""
        authority = f"https://login.microsoftonline.com/{self.tenant_id}"
        try:
            self.app = msal.ConfidentialClientApplication(
                self.client_id,
                authority=authority,
                client_credential=self.client_secret
            )
            logger.info("MSAL application initialized for BC authentication")
        except Exception as e:
            self.app = None
            logger.warning(f"MSAL init failed ({type(e).__name__}: {e}); BC client will not authenticate")

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
            # Extract BC error message from response body so callers see the real reason
            bc_message = ""
            try:
                error_body = response.json()
                bc_message = error_body.get("error", {}).get("message", "")
            except Exception:
                bc_message = response.text[:500] if response.text else ""
            raise requests.HTTPError(
                f"{response.status_code} {response.reason} for url: {url} | BC: {bc_message}",
                response=response,
            )

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

    def get_customers(self, company_id: Optional[str] = None, top: int = 1000) -> List[Dict[str, Any]]:
        """Get list of customers, paginated through all results."""
        cid = company_id or self.company_id
        all_customers: List[Dict[str, Any]] = []
        url = f"{self.base_url}/companies({cid})/customers?$top={top}"

        while url:
            token = self._get_access_token()
            resp = requests.get(url, headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            })
            if resp.status_code >= 400:
                logger.error(f"BC API error {resp.status_code}: {resp.text[:300]}")
                break
            data = resp.json()
            all_customers.extend(data.get("value", []))
            url = data.get("@odata.nextLink")

        return all_customers

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
        Follows @odata.nextLink to paginate through all results.
        """
        cid = company_id or self.company_id
        all_customers: List[Dict[str, Any]] = []
        url = f"{self.base_url}/companies({cid})/customers?$top={top}"

        while url:
            token = self._get_access_token()
            resp = requests.get(url, headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            })
            if resp.status_code >= 400:
                logger.error(f"BC API error {resp.status_code}: {resp.text[:300]}")
                break
            data = resp.json()
            all_customers.extend(data.get("value", []))
            url = data.get("@odata.nextLink")

        logger.info(f"Fetched {len(all_customers)} customers from BC (paginated)")
        return all_customers

    def get_customer_with_multiplier(self, customer_id: str,
                                      company_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Get a single customer including priceMultiplierPercent field.
        """
        cid = company_id or self.company_id
        result = self._make_request("GET", f"companies({cid})/customers({customer_id})")
        return result

    # ==================== OData V4 helpers ====================
    #
    # The standard BC v2.0 REST API does not expose Customer_Price_Group,
    # ItemMasterList Unit_Price, or the SalesPriceLists entity. We read those
    # via published BC OData V4 web services (the same approach the Upwardor
    # portal uses). The pages "CustomerList", "ItemMasterList", and
    # "SalesPriceLists" must be published on the BC tenant for these calls to
    # succeed; on 404 we log and return None so callers can fall back.

    def _odata_company_path(self) -> str:
        """Build the OData V4 base path with company name URL-encoded."""
        company_name = settings.BC_COMPANY_NAME or ""
        return f"{self.odata_url}/Company('{quote(company_name)}')"

    @staticmethod
    def _odata_escape(s: str) -> str:
        """Escape single quotes for OData $filter values."""
        return (s or "").replace("'", "''")

    def _odata_get(
        self,
        entity_set: str,
        filter_str: Optional[str] = None,
        top: Optional[int] = None,
        select: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """OData V4 GET against {odata_url}/Company('NAME')/{entity_set}.

        Returns parsed JSON on success, None if the entity isn't published
        (404) or the request errors out. Callers must tolerate None.
        """
        if not self.odata_url:
            return None
        token = self._get_access_token()
        url = f"{self._odata_company_path()}/{entity_set}"
        params: List[str] = []
        if filter_str:
            params.append(f"$filter={filter_str}")
        if top:
            params.append(f"$top={top}")
        if select:
            params.append(f"$select={select}")
        if params:
            url += "?" + "&".join(params)

        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        try:
            resp = requests.get(url, headers=headers, timeout=30)
        except requests.RequestException as e:
            logger.warning(f"OData GET network error for {entity_set}: {e}")
            return None
        if resp.status_code == 404:
            logger.warning(
                f"OData entity '{entity_set}' returned 404 — page may not be "
                f"published on the BC tenant"
            )
            return None
        if resp.status_code >= 400:
            logger.error(
                f"OData GET {entity_set} -> {resp.status_code}: {resp.text[:300]}"
            )
            return None
        try:
            return resp.json()
        except ValueError:
            return None

    # ==================== Sales Prices (OData V4) ====================

    def get_sales_price(
        self,
        part_number: str,
        price_group: str,
        uom: str,
    ) -> Optional[Dict[str, Any]]:
        """Look up a unit price from BC's published SalesPriceLists for a
        specific (item, customer price group, UoM). Returns the price-list
        line dict (with Unit_Price, Description, Unit_of_Measure_Code) or
        None if no match.
        """
        if not (part_number and price_group and uom):
            return None
        flt = (
            f"Product_No eq '{self._odata_escape(part_number)}' and "
            f"Assign_to_No eq '{self._odata_escape(price_group)}' and "
            f"Unit_of_Measure_Code eq '{self._odata_escape(uom)}'"
        )
        data = self._odata_get("SalesPriceLists", filter_str=flt, top=1)
        if not data:
            return None
        rows = data.get("value", [])
        return rows[0] if rows else None

    def get_default_sales_price(
        self,
        part_number: str,
        uom: str,
    ) -> Optional[Dict[str, Any]]:
        """Lookup the 'All Customers' Sales Price List entry — i.e. the row
        where Source Type = All Customers (Assign_to_No is blank). This is
        the second tier of the lookup chain after the customer-group-specific
        entry has missed.
        """
        if not (part_number and uom):
            return None
        flt = (
            f"Product_No eq '{self._odata_escape(part_number)}' and "
            f"Assign_to_No eq '' and "
            f"Unit_of_Measure_Code eq '{self._odata_escape(uom)}'"
        )
        data = self._odata_get("SalesPriceLists", filter_str=flt, top=1)
        if not data:
            return None
        rows = data.get("value", [])
        return rows[0] if rows else None

    # ==================== Item Master (OData V4) ====================

    def get_item_master(self, part_number: str) -> Optional[Dict[str, Any]]:
        """Read a single item from the published ItemMasterList page.
        Returns dict with No, Base_Unit_of_Measure, Description, Unit_Price,
        etc., or None if not found / page not published.
        """
        if not part_number:
            return None
        flt = f"No eq '{self._odata_escape(part_number)}'"
        data = self._odata_get("ItemMasterList", filter_str=flt, top=1)
        if not data:
            return None
        rows = data.get("value", [])
        return rows[0] if rows else None

    def get_item_masters(self, part_numbers: List[str]) -> Dict[str, Dict[str, Any]]:
        """Batch-fetch ItemMasterList records by part number. Returns
        {No: row}. Batches into chunks to stay under URL length limits.
        """
        if not part_numbers:
            return {}
        result: Dict[str, Dict[str, Any]] = {}
        unique = list({pn for pn in part_numbers if pn})
        batch_size = 25
        for start in range(0, len(unique), batch_size):
            batch = unique[start:start + batch_size]
            flt = " or ".join(
                f"No eq '{self._odata_escape(pn)}'" for pn in batch
            )
            data = self._odata_get("ItemMasterList", filter_str=flt)
            if not data:
                continue
            for row in data.get("value", []):
                no = row.get("No")
                if no:
                    result[no] = row
        return result

    # ==================== Customer Card (OData V4) ====================

    def get_customer_card(self, customer_no: str) -> Optional[Dict[str, Any]]:
        """Read a single customer record from the published CustomerList
        page (or Customer_Card_Excel) so we can read Customer_Price_Group.
        """
        if not customer_no:
            return None
        flt = f"No eq '{self._odata_escape(customer_no)}'"
        data = self._odata_get("CustomerList", filter_str=flt, top=1)
        if not data:
            return None
        rows = data.get("value", [])
        return rows[0] if rows else None

    def get_customer_cards(self) -> List[Dict[str, Any]]:
        """Bulk-fetch all customers via CustomerList (OData V4). Returns the
        list (possibly large). Empty list if page is not published.
        """
        data = self._odata_get("CustomerList")
        if not data:
            return []
        return data.get("value", [])

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

    def get_items_by_numbers(self, part_numbers: List[str],
                              company_id: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
        """
        Batch-fetch items by part number from BC.

        Returns dict keyed by part number for O(1) lookup.
        Batches requests to stay under URL length limits (~40 items per call).
        """
        if not part_numbers:
            return {}

        cid = company_id or self.company_id
        select = "$select=number,unitCost,unitPrice,generalProductPostingGroupCode"
        result: Dict[str, Dict[str, Any]] = {}
        batch_size = 40

        for start in range(0, len(part_numbers), batch_size):
            batch = part_numbers[start:start + batch_size]
            filter_parts = " or ".join(
                f"number eq '{pn.replace(chr(39), chr(39)*2)}'" for pn in batch
            )
            endpoint = f"companies({cid})/items?$filter={filter_parts}&{select}"
            try:
                resp = self._make_request("GET", endpoint)
                for item in resp.get("value", []):
                    result[item["number"]] = item
            except Exception as e:
                logger.warning(f"Batch item fetch failed for {len(batch)} items: {e}")

        return result

    def search_items_by_prefix(self, prefix: str, company_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Fetch all items whose number starts with a given prefix.
        Paginates with $top=1000 to collect all matches.
        """
        cid = company_id or self.company_id
        safe_prefix = prefix.replace("'", "''")
        filter_query = f"startswith(number,'{safe_prefix}')"
        select = "$select=number"
        all_items: List[Dict[str, Any]] = []
        skip = 0
        page_size = 1000

        while True:
            endpoint = (
                f"companies({cid})/items"
                f"?$filter={filter_query}&{select}&$top={page_size}&$skip={skip}"
            )
            result = self._make_request("GET", endpoint)
            items = result.get("value", [])
            all_items.extend(items)
            if len(items) < page_size:
                break
            skip += page_size

        logger.info(f"search_items_by_prefix('{prefix}'): found {len(all_items)} items")
        return all_items

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

    def update_sales_quote(self, quote_id: str, quote_data: Dict[str, Any], etag: str = "*", company_id: Optional[str] = None) -> Dict[str, Any]:
        """Update existing sales quote. Pass etag from GET response for optimistic concurrency."""
        cid = company_id or self.company_id
        result = self._make_request(
            "PATCH",
            f"companies({cid})/salesQuotes({quote_id})",
            json=quote_data,
            headers={"If-Match": etag},
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
        # BC enforces a 100-character limit on line descriptions — truncate if needed
        if "description" in line_data and line_data["description"] and len(line_data["description"]) > 100:
            line_data = {**line_data, "description": line_data["description"][:97] + "..."}
        result = self._make_request(
            "POST",
            f"companies({cid})/salesQuotes({quote_id})/salesQuoteLines",
            json=line_data
        )
        return result

    def update_quote_line(self, quote_id: str, line_id: str, etag: str, update_data: Dict[str, Any], company_id: Optional[str] = None) -> Dict[str, Any]:
        """Update a sales quote line (PATCH). Uses If-Match to satisfy BC's optimistic concurrency."""
        cid = company_id or self.company_id
        result = self._make_request(
            "PATCH",
            f"companies({cid})/salesQuotes({quote_id})/salesQuoteLines({line_id})",
            json=update_data,
            headers={"If-Match": etag},
        )
        return result

    def delete_quote_line(self, quote_id: str, line_id: str, company_id: Optional[str] = None) -> bool:
        """Delete a sales quote line. BC accepts If-Match: * here (no ETag needed)."""
        cid = company_id or self.company_id
        self._make_request(
            "DELETE",
            f"companies({cid})/salesQuotes({quote_id})/salesQuoteLines({line_id})",
            headers={"If-Match": "*"},
        )
        return True

    def set_quote_line_output(self, quote_number: str, line_no: int, output: bool = True) -> None:
        """
        Set the Output flag on a sales quote line via OData.

        The standard v2.0 salesQuoteLines API doesn't expose the 'Output' field,
        so we use the Sales_QuoteSalesLines_Excel OData endpoint directly.
        When Output=True on a Comment line, BC shows it on printed quotes
        and subtotals the items below it.
        """
        token = self._get_access_token()
        key = f"Document_Type='Quote',Document_No='{quote_number}',Line_No={line_no}"
        url = f"{self.odata_url}/Sales_QuoteSalesLines_Excel({key})"

        # GET the current etag first
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        get_resp = requests.get(url, headers=headers, timeout=30)
        if get_resp.status_code >= 400:
            logger.warning(f"Could not GET OData line for Output flag: {get_resp.status_code}")
            return
        etag = get_resp.json().get("@odata.etag", "*")

        # PATCH to set Output
        patch_headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "If-Match": etag,
        }
        resp = requests.patch(url, json={"Output": output}, headers=patch_headers, timeout=30)
        if resp.status_code < 300:
            logger.info(f"Set Output={output} on {quote_number} line {line_no}")
        else:
            logger.warning(f"Failed to set Output on {quote_number} line {line_no}: {resp.status_code}")

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

    def create_purchase_order(self, po_data: Dict[str, Any], company_id: Optional[str] = None) -> Dict[str, Any]:
        """Create a new purchase order in BC"""
        cid = company_id or self.company_id
        result = self._make_request(
            "POST",
            f"companies({cid})/purchaseOrders",
            json=po_data
        )
        return result

    def add_purchase_order_line(self, po_id: str, line_data: Dict[str, Any],
                                 company_id: Optional[str] = None) -> Dict[str, Any]:
        """Add a line item to a purchase order"""
        cid = company_id or self.company_id
        result = self._make_request(
            "POST",
            f"companies({cid})/purchaseOrders({po_id})/purchaseOrderLines",
            json=line_data
        )
        return result

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
        Convert a sales quote to a sales order.

        Tries makeOrder first. If BC rejects it (e.g. requestedDeliveryDate
        not on the v2.0 salesQuotes entity), falls back to manually creating
        a sales order and copying all quote lines.

        Args:
            quote_id: The BC sales quote ID (GUID)
            company_id: Optional company ID

        Returns:
            The newly created sales order
        """
        cid = company_id or self.company_id

        try:
            result = self._make_request(
                "POST",
                f"companies({cid})/salesQuotes({quote_id})/Microsoft.NAV.makeOrder"
            )
            logger.info(f"Converted quote {quote_id} to order via makeOrder: {result.get('number', 'N/A')}")
            return result
        except Exception as e:
            error_msg = str(e)
            if "delivery" not in error_msg.lower() and "Requested" not in error_msg:
                raise  # Not the delivery date issue, re-raise

        # Fallback: create order manually with delivery date set
        logger.info(f"makeOrder failed (delivery date), creating order manually from quote {quote_id}")
        return self._manual_quote_to_order(quote_id, cid)

    def _manual_quote_to_order(self, quote_id: str, company_id: str) -> Dict[str, Any]:
        """
        Manually convert a quote to an order by creating a new sales order,
        copying all quote lines, then deleting the quote.

        This bypasses makeOrder's limitation where requestedDeliveryDate
        cannot be set on the salesQuotes v2.0 entity.
        """
        from datetime import datetime, timedelta

        # 1. Get the quote header
        quote = self.get_sales_quote(quote_id, company_id)

        # 2. Create order with delivery date (6 weeks out)
        delivery_date = (datetime.utcnow() + timedelta(weeks=6)).strftime("%Y-%m-%d")
        order_data = {
            "customerId": quote.get("customerId"),
            "externalDocumentNumber": quote.get("externalDocumentNumber", ""),
            "requestedDeliveryDate": delivery_date,
        }
        order = self.create_sales_order(order_data, company_id)
        order_id = order["id"]
        logger.info(f"Created sales order {order.get('number')} with delivery date {delivery_date}")

        # 3. Copy quote lines to order
        quote_lines = self.get_quote_lines(quote_id, company_id)
        for ql in quote_lines:
            line_data = {}
            if ql.get("lineType") == "Comment":
                line_data = {
                    "lineType": "Comment",
                    "description": ql.get("description", ""),
                }
            else:
                line_data = {
                    "lineType": ql.get("lineType", "Item"),
                    "lineObjectNumber": ql.get("lineObjectNumber", ""),
                    "description": ql.get("description", ""),
                    "quantity": ql.get("quantity", 0),
                }
                if ql.get("unitPrice"):
                    line_data["unitPrice"] = ql["unitPrice"]

            try:
                self.add_order_line(order_id, line_data, company_id)
            except Exception as line_err:
                logger.warning(f"Failed to copy quote line to order: {line_err}")

        # 4. Delete the original quote (it's been converted)
        try:
            self.delete_sales_quote(quote_id, company_id)
            logger.info(f"Deleted original quote {quote_id} after manual conversion")
        except Exception as del_err:
            logger.warning(f"Could not delete quote {quote_id} after conversion: {del_err}")

        # 5. Return the order (re-fetch to get totals)
        return self.get_sales_order(order_id, company_id)

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
            f"companies({cid})/salesQuotes?$filter=customerId eq {bc_customer_id}&$top={top}&$orderby=documentDate desc"
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
            f"companies({cid})/salesOrders?$filter=customerId eq {bc_customer_id}&$top={top}&$orderby=orderDate desc"
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
            f"companies({cid})/salesInvoices?$filter=customerId eq {bc_customer_id}&$top={top}&$orderby=invoiceDate desc"
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
            f"companies({cid})/salesShipments?$filter=customerId eq {bc_customer_id}&$top={top}&$orderby=shipmentDate desc"
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
