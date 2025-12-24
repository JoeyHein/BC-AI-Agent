"""
Test Microsoft Graph API Email Connectivity
Run this script after configuring Graph API credentials in .env
"""

import sys
import os
from pathlib import Path

# Add parent directory to path
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from dotenv import load_dotenv
load_dotenv()

from app.integrations.email.client import graph_client
from app.config import settings
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def test_email_connection():
    """Test Graph API email connection"""
    logger.info("=" * 60)
    logger.info("BC AI Agent - Microsoft Graph Email Connection Test")
    logger.info("=" * 60)

    # Check configuration
    logger.info("\n1. Checking configuration...")
    if not settings.GRAPH_TENANT_ID:
        logger.error("❌ GRAPH_TENANT_ID not configured")
        return False
    if not settings.GRAPH_CLIENT_ID:
        logger.error("❌ GRAPH_CLIENT_ID not configured")
        return False
    if not settings.GRAPH_CLIENT_SECRET:
        logger.error("❌ GRAPH_CLIENT_SECRET not configured")
        return False

    logger.info(f"✅ Tenant ID: {settings.GRAPH_TENANT_ID[:8]}...")
    logger.info(f"✅ Client ID: {settings.GRAPH_CLIENT_ID[:8]}...")
    logger.info(f"✅ Inbox 1: {settings.EMAIL_INBOX_1}")
    logger.info(f"✅ Inbox 2: {settings.EMAIL_INBOX_2}")

    # Test authentication
    logger.info("\n2. Testing OAuth 2.0 authentication...")
    try:
        token = graph_client._get_access_token()
        logger.info(f"✅ Successfully acquired access token")
        logger.info(f"   Token length: {len(token)} characters")
    except Exception as e:
        logger.error(f"❌ Authentication failed: {e}")
        return False

    # Test inbox access for EMAIL_INBOX_1
    if settings.EMAIL_INBOX_1:
        logger.info(f"\n3. Testing inbox access for {settings.EMAIL_INBOX_1}...")
        try:
            emails = graph_client.get_inbox_emails(settings.EMAIL_INBOX_1, max_count=5)
            logger.info(f"✅ Successfully retrieved inbox emails")
            logger.info(f"   Found {len(emails)} emails (showing top 5):")
            for email in emails[:5]:
                sender = email.get('from', {}).get('emailAddress', {}).get('address', 'Unknown')
                subject = email.get('subject', 'No Subject')
                received = email.get('receivedDateTime', '')
                logger.info(f"   - From: {sender}")
                logger.info(f"     Subject: {subject[:50]}")
                logger.info(f"     Received: {received}")
                logger.info("")
        except Exception as e:
            logger.error(f"❌ Failed to retrieve inbox: {e}")
            return False

    # Test inbox access for EMAIL_INBOX_2
    if settings.EMAIL_INBOX_2 and settings.EMAIL_INBOX_2 != settings.EMAIL_INBOX_1:
        logger.info(f"\n4. Testing inbox access for {settings.EMAIL_INBOX_2}...")
        try:
            emails = graph_client.get_inbox_emails(settings.EMAIL_INBOX_2, max_count=5)
            logger.info(f"✅ Successfully retrieved inbox emails")
            logger.info(f"   Found {len(emails)} emails (showing top 5):")
            for email in emails[:5]:
                sender = email.get('from', {}).get('emailAddress', {}).get('address', 'Unknown')
                subject = email.get('subject', 'No Subject')
                logger.info(f"   - From: {sender}, Subject: {subject[:50]}")
        except Exception as e:
            logger.error(f"❌ Failed to retrieve inbox: {e}")
            return False

    # Test folder operations
    logger.info("\n5. Testing folder operations...")
    try:
        folders = graph_client.get_folders(settings.EMAIL_INBOX_1)
        logger.info(f"✅ Successfully retrieved folders")
        logger.info(f"   Found {len(folders)} folders:")
        for folder in folders[:10]:
            logger.info(f"   - {folder.get('displayName')} (ID: {folder.get('id')[:8]}...)")
    except Exception as e:
        logger.error(f"❌ Failed to retrieve folders: {e}")
        return False

    # Test sent emails (for AI learning)
    logger.info("\n6. Testing sent emails retrieval...")
    try:
        sent_emails = graph_client.get_sent_emails(settings.EMAIL_INBOX_1, days_back=30, max_count=5)
        logger.info(f"✅ Successfully retrieved sent emails")
        logger.info(f"   Found {len(sent_emails)} sent emails (last 30 days, showing top 5):")
        for email in sent_emails[:5]:
            to_recipients = email.get('toRecipients', [])
            to_address = to_recipients[0].get('emailAddress', {}).get('address', 'Unknown') if to_recipients else 'Unknown'
            subject = email.get('subject', 'No Subject')
            logger.info(f"   - To: {to_address}, Subject: {subject[:50]}")
    except Exception as e:
        logger.error(f"❌ Failed to retrieve sent emails: {e}")
        return False

    logger.info("\n" + "=" * 60)
    logger.info("✅ ALL TESTS PASSED - Graph Email API Connection Successful!")
    logger.info("=" * 60)
    return True


if __name__ == "__main__":
    success = test_email_connection()
    sys.exit(0 if success else 1)
