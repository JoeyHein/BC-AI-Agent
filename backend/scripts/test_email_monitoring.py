"""
Test Email Monitoring Service
Run this script after Exchange Online permissions are granted
"""

import sys
import os
from pathlib import Path

# Add parent directory to path
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from dotenv import load_dotenv
load_dotenv()

from app.services.email_monitor import email_monitor
from app.config import settings
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def test_email_monitoring():
    """Test the complete email monitoring workflow"""
    logger.info("=" * 80)
    logger.info("BC AI Agent - Email Monitoring Service Test")
    logger.info("=" * 80)

    # Check configuration
    logger.info("\n1. Checking configuration...")
    logger.info(f"   Inbox 1: {settings.EMAIL_INBOX_1}")
    logger.info(f"   Inbox 2: {settings.EMAIL_INBOX_2}")
    logger.info(f"   Anthropic API configured: {'Yes' if settings.ANTHROPIC_API_KEY else 'No'}")

    # Test email monitoring (last 24 hours)
    logger.info("\n2. Monitoring inboxes (last 24 hours)...")
    try:
        results = email_monitor.monitor_inboxes(hours_back=24, max_emails_per_inbox=50)

        logger.info("\n" + "=" * 80)
        logger.info("MONITORING RESULTS")
        logger.info("=" * 80)
        logger.info(f"Total emails checked: {results['total_emails_checked']}")
        logger.info(f"New emails found: {results['new_emails_found']}")
        logger.info(f"Quote requests parsed: {results['quote_requests_parsed']}")
        logger.info(f"Errors: {results['errors']}")

        logger.info("\nBy inbox:")
        for inbox, inbox_results in results['by_inbox'].items():
            logger.info(f"  {inbox}:")
            if 'error' in inbox_results:
                logger.info(f"    ERROR: {inbox_results['error']}")
            else:
                logger.info(f"    Checked: {inbox_results['emails_checked']}")
                logger.info(f"    New: {inbox_results['new_emails']}")
                logger.info(f"    Quotes: {inbox_results['quotes_parsed']}")

    except Exception as e:
        logger.error(f"Monitoring failed: {e}", exc_info=True)
        return False

    # Get pending quote requests
    logger.info("\n3. Retrieving pending quote requests...")
    try:
        pending_quotes = email_monitor.get_pending_quote_requests(min_confidence=0.0)
        logger.info(f"   Found {len(pending_quotes)} pending quote requests")

        if pending_quotes:
            logger.info("\n   Top 5 quote requests:")
            for i, quote in enumerate(pending_quotes[:5], 1):
                confidence = quote.confidence_scores.get("overall", 0.0)
                logger.info(f"   [{i}] Customer: {quote.customer_name}")
                logger.info(f"       Email: {quote.contact_email}")
                logger.info(f"       Confidence: {confidence:.2%}")
                logger.info(f"       Status: {quote.status}")
                logger.info(f"       Doors: {len(quote.door_specs.get('doors', [])) if quote.door_specs else 0}")
                logger.info("")

    except Exception as e:
        logger.error(f"Failed to retrieve pending quotes: {e}")
        return False

    # Get stats
    logger.info("\n4. Getting statistics...")
    try:
        stats = email_monitor.get_stats()
        logger.info(f"   Total emails logged: {stats['total_emails_logged']}")
        logger.info(f"   Total emails parsed: {stats['total_emails_parsed']}")
        logger.info(f"   Pending quote requests: {stats['pending_quote_requests']}")
        logger.info(f"   Emails (last 24h): {stats['emails_last_24h']}")

    except Exception as e:
        logger.error(f"Failed to get stats: {e}")
        return False

    logger.info("\n" + "=" * 80)
    logger.info("✅ EMAIL MONITORING TEST COMPLETE")
    logger.info("=" * 80)

    return True


if __name__ == "__main__":
    success = test_email_monitoring()
    sys.exit(0 if success else 1)
