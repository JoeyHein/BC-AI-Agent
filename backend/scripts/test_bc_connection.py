"""
Test Business Central API Connectivity
Run this script after configuring BC credentials in .env
"""

import sys
import os
from pathlib import Path

# Add parent directory to path
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from dotenv import load_dotenv
load_dotenv()

from app.integrations.bc.client import bc_client
from app.config import settings
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def test_connection():
    """Test BC API connection"""
    logger.info("=" * 60)
    logger.info("BC AI Agent - Business Central Connection Test")
    logger.info("=" * 60)

    # Check configuration
    logger.info("\n1. Checking configuration...")
    if not settings.BC_TENANT_ID:
        logger.error("❌ BC_TENANT_ID not configured")
        return False
    if not settings.BC_CLIENT_ID:
        logger.error("❌ BC_CLIENT_ID not configured")
        return False
    if not settings.BC_CLIENT_SECRET:
        logger.error("❌ BC_CLIENT_SECRET not configured")
        return False

    logger.info(f"✅ Tenant ID: {settings.BC_TENANT_ID[:8]}...")
    logger.info(f"✅ Client ID: {settings.BC_CLIENT_ID[:8]}...")
    logger.info(f"✅ Environment: {settings.BC_ENVIRONMENT}")
    logger.info(f"✅ Base URL: {settings.BC_BASE_URL}")

    # Test authentication
    logger.info("\n2. Testing OAuth 2.0 authentication...")
    try:
        token = bc_client._get_access_token()
        logger.info(f"✅ Successfully acquired access token")
        logger.info(f"   Token length: {len(token)} characters")
    except Exception as e:
        logger.error(f"❌ Authentication failed: {e}")
        return False

    # Test companies endpoint
    logger.info("\n3. Testing companies endpoint...")
    try:
        companies = bc_client.get_companies()
        logger.info(f"✅ Successfully retrieved companies")
        logger.info(f"   Found {len(companies)} companies:")
        for company in companies:
            logger.info(f"   - {company.get('displayName')} (ID: {company.get('id')})")
    except Exception as e:
        logger.error(f"❌ Failed to retrieve companies: {e}")
        return False

    # Test customers (if company ID configured)
    if settings.BC_COMPANY_ID:
        logger.info("\n4. Testing customers endpoint...")
        try:
            customers = bc_client.get_customers(top=5)
            logger.info(f"✅ Successfully retrieved customers")
            logger.info(f"   Sample customers (top 5):")
            for customer in customers[:5]:
                logger.info(f"   - {customer.get('displayName')} ({customer.get('number')})")
        except Exception as e:
            logger.error(f"❌ Failed to retrieve customers: {e}")
            return False

        # Test items
        logger.info("\n5. Testing items endpoint...")
        try:
            items = bc_client.get_items(top=5)
            logger.info(f"✅ Successfully retrieved items")
            logger.info(f"   Sample items (top 5):")
            for item in items[:5]:
                logger.info(f"   - {item.get('displayName')} ({item.get('number')})")
        except Exception as e:
            logger.error(f"❌ Failed to retrieve items: {e}")
            return False

        # Test sales quotes
        logger.info("\n6. Testing sales quotes endpoint...")
        try:
            quotes = bc_client.get_sales_quotes(top=5)
            logger.info(f"✅ Successfully retrieved sales quotes")
            logger.info(f"   Found {len(quotes)} quotes (showing top 5):")
            for quote in quotes[:5]:
                logger.info(f"   - Quote {quote.get('number')}: {quote.get('customerName')} - ${quote.get('totalAmountIncludingTax', 0):,.2f}")
        except Exception as e:
            logger.error(f"❌ Failed to retrieve sales quotes: {e}")
            return False

    logger.info("\n" + "=" * 60)
    logger.info("✅ ALL TESTS PASSED - BC API Connection Successful!")
    logger.info("=" * 60)
    return True


if __name__ == "__main__":
    success = test_connection()
    sys.exit(0 if success else 1)
