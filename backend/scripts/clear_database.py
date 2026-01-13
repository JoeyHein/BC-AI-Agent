"""
Clear database to allow reprocessing of emails
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
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def clear_database():
    """Clear all email logs, quote requests, and AI decisions"""
    db = SessionLocal()
    try:
        # Count before deletion
        email_count = db.query(EmailLog).count()
        quote_count = db.query(QuoteRequest).count()
        ai_count = db.query(AIDecision).count()

        logger.info(f"Before deletion:")
        logger.info(f"  Emails: {email_count}")
        logger.info(f"  Quote requests: {quote_count}")
        logger.info(f"  AI decisions: {ai_count}")

        # Delete all (cascade should handle relationships)
        db.query(AIDecision).delete()
        db.query(QuoteRequest).delete()
        db.query(EmailLog).delete()

        db.commit()

        # Verify deletion
        email_count = db.query(EmailLog).count()
        quote_count = db.query(QuoteRequest).count()
        ai_count = db.query(AIDecision).count()

        logger.info(f"\nAfter deletion:")
        logger.info(f"  Emails: {email_count}")
        logger.info(f"  Quote requests: {quote_count}")
        logger.info(f"  AI decisions: {ai_count}")
        logger.info("\nDatabase cleared successfully!")

    except Exception as e:
        logger.error(f"Error clearing database: {e}")
        db.rollback()
        raise
    finally:
        db.close()

if __name__ == "__main__":
    clear_database()
