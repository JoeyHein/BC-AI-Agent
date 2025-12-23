"""
Test Business Central OData API Connectivity
"""

import sys
import os
from pathlib import Path

# Add parent directory to path
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from dotenv import load_dotenv
load_dotenv()

from app.config import settings
import logging
import msal
import requests

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def get_access_token():
    """Get OAuth token"""
    authority = f"https://login.microsoftonline.com/{settings.BC_TENANT_ID}"
    app = msal.ConfidentialClientApplication(
        settings.BC_CLIENT_ID,
        authority=authority,
        client_credential=settings.BC_CLIENT_SECRET
    )

    scope = ["https://api.businesscentral.dynamics.com/.default"]
    result = app.acquire_token_for_client(scopes=scope)

    if "access_token" in result:
        return result["access_token"]
    else:
        raise Exception(f"Auth failed: {result.get('error_description')}")


def test_odata_connection():
    """Test OData V4 endpoint"""
    logger.info("=" * 60)
    logger.info("BC AI Agent - OData V4 Connection Test")
    logger.info("=" * 60)

    # Get token
    logger.info("\n1. Getting access token...")
    token = get_access_token()
    logger.info(f"✅ Token acquired (length: {len(token)})")

    # Test OData endpoint
    logger.info("\n2. Testing OData V4 endpoint...")

    company_name = "Open Distribution Company Inc."
    base_url = f"https://api.businesscentral.dynamics.com/v2.0/{settings.BC_TENANT_ID}/{settings.BC_ENVIRONMENT}"

    # Try to list companies first
    url = f"{base_url}/api/v2.0/companies"

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    logger.info(f"   URL: {url}")
    response = requests.get(url, headers=headers)

    if response.status_code == 200:
        logger.info(f"✅ REST API works! Status: {response.status_code}")
        companies = response.json().get("value", [])
        logger.info(f"   Found {len(companies)} companies:")
        for company in companies:
            logger.info(f"   - {company.get('displayName')} (ID: {company.get('id')})")
    else:
        logger.error(f"❌ REST API failed: {response.status_code}")
        logger.error(f"   Response: {response.text}")

        # Try OData V4
        logger.info("\n3. Trying OData V4 endpoint...")
        odata_url = f"{base_url}/ODataV4/Company('{company_name}')/SalesOrderList"
        logger.info(f"   URL: {odata_url}")

        odata_response = requests.get(odata_url, headers=headers)

        if odata_response.status_code == 200:
            logger.info(f"✅ OData V4 works! Status: {odata_response.status_code}")
            data = odata_response.json()
            logger.info(f"   Response keys: {list(data.keys())}")
        else:
            logger.error(f"❌ OData V4 also failed: {odata_response.status_code}")
            logger.error(f"   Response: {odata_response.text}")

    logger.info("\n" + "=" * 60)


if __name__ == "__main__":
    try:
        test_odata_connection()
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        sys.exit(1)
