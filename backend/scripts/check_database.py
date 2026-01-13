"""
Check current database state
"""
import sys
from pathlib import Path

# Add parent directory to path
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from dotenv import load_dotenv
load_dotenv()

from app.db.database import SessionLocal
from app.db.models import EmailLog, QuoteRequest, AIDecision
from sqlalchemy import func
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def check_database():
    """Check what's currently in the database"""
    db = SessionLocal()
    try:
        # Count emails by status
        total_emails = db.query(EmailLog).count()
        logger.info(f"Total emails in database: {total_emails}")

        # Get status breakdown
        statuses = db.query(EmailLog.status, func.count(EmailLog.id)).group_by(EmailLog.status).all()
        logger.info("\nEmail statuses:")
        for status, count in statuses:
            logger.info(f"  {status}: {count}")

        # Show sample emails
        logger.info("\nFirst 5 emails:")
        emails = db.query(EmailLog).order_by(EmailLog.received_at.desc()).limit(5).all()
        for email in emails:
            logger.info(f"  From: {email.from_address}")
            logger.info(f"  Subject: {email.subject[:60]}...")
            logger.info(f"  Status: {email.status}")
            logger.info(f"  Received: {email.received_at}")
            logger.info("")

        # Check quote requests
        total_quotes = db.query(QuoteRequest).count()
        logger.info(f"Total quote requests: {total_quotes}")

        # Check AI decisions
        total_ai_decisions = db.query(AIDecision).count()
        logger.info(f"Total AI decisions: {total_ai_decisions}")

    finally:
        db.close()

if __name__ == "__main__":
    check_database()
