"""
Email Monitoring Service for BC AI Agent
Monitors inboxes, parses emails with AI, and stores quote requests
"""

import logging
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta

from app.integrations.email.client import graph_client
from app.integrations.ai.client import ai_client
from app.db.database import SessionLocal
from app.db.models import EmailLog, QuoteRequest, AIDecision
from app.config import settings

logger = logging.getLogger(__name__)


class EmailMonitorService:
    """Service for monitoring emails and processing quote requests"""

    def __init__(self):
        self.graph_client = graph_client
        self.ai_client = ai_client
        self.monitored_inboxes = [settings.EMAIL_INBOX_1, settings.EMAIL_INBOX_2]

    def monitor_inboxes(self, hours_back: int = 24, max_emails_per_inbox: int = 50) -> Dict[str, Any]:
        """Monitor all configured inboxes for new emails

        Args:
            hours_back: How many hours back to check for emails
            max_emails_per_inbox: Maximum emails to process per inbox

        Returns:
            Dict with processing summary
        """
        logger.info(f"Starting email monitoring cycle - checking last {hours_back} hours")

        results = {
            "total_emails_checked": 0,
            "new_emails_found": 0,
            "quote_requests_parsed": 0,
            "errors": 0,
            "by_inbox": {}
        }

        for inbox_email in self.monitored_inboxes:
            if not inbox_email:
                continue

            logger.info(f"Checking inbox: {inbox_email}")

            try:
                inbox_results = self._process_inbox(inbox_email, hours_back, max_emails_per_inbox)
                results["by_inbox"][inbox_email] = inbox_results
                results["total_emails_checked"] += inbox_results["emails_checked"]
                results["new_emails_found"] += inbox_results["new_emails"]
                results["quote_requests_parsed"] += inbox_results["quotes_parsed"]
                results["errors"] += inbox_results["errors"]

            except Exception as e:
                logger.error(f"Error processing inbox {inbox_email}: {e}")
                results["errors"] += 1
                results["by_inbox"][inbox_email] = {"error": str(e)}

        logger.info(f"Monitoring cycle complete. Found {results['new_emails_found']} new emails, "
                   f"parsed {results['quote_requests_parsed']} quote requests")

        return results

    def _process_inbox(self, inbox_email: str, hours_back: int, max_emails: int) -> Dict[str, Any]:
        """Process emails from a single inbox"""
        results = {
            "emails_checked": 0,
            "new_emails": 0,
            "quotes_parsed": 0,
            "errors": 0
        }

        # Get recent emails
        try:
            emails = self.graph_client.get_recent_emails(inbox_email, hours=hours_back, max_count=max_emails)
            results["emails_checked"] = len(emails)
            logger.info(f"Found {len(emails)} emails in {inbox_email}")

        except Exception as e:
            logger.error(f"Failed to retrieve emails from {inbox_email}: {e}")
            results["errors"] += 1
            return results

        # Process each email
        db = SessionLocal()
        try:
            for email in emails:
                try:
                    processed = self._process_single_email(db, email, inbox_email)
                    if processed:
                        results["new_emails"] += 1
                        if processed == "quote_request":
                            results["quotes_parsed"] += 1
                except Exception as e:
                    logger.error(f"Error processing email {email.get('id')}: {e}")
                    results["errors"] += 1

            db.commit()

        finally:
            db.close()

        return results

    def _process_single_email(self, db, email: Dict[str, Any], inbox_email: str) -> Optional[str]:
        """Process a single email

        Returns:
            "quote_request" if email was a quote request
            "other" if email was logged but not a quote request
            None if email was already processed
        """
        message_id = email.get("id")
        internet_message_id = email.get("internetMessageId")

        # Check if already processed
        existing = db.query(EmailLog).filter(
            EmailLog.message_id == internet_message_id
        ).first()

        if existing:
            logger.debug(f"Email {internet_message_id} already processed, skipping")
            return None

        # Extract email data
        from_address = email.get("from", {}).get("emailAddress", {}).get("address", "")
        from_name = email.get("from", {}).get("emailAddress", {}).get("name", from_address)
        subject = email.get("subject", "")
        received_at = email.get("receivedDateTime")
        body = email.get("body", {}).get("content", "")

        logger.info(f"Processing new email from {from_name}: {subject[:50]}")

        # Step 1: Categorize email
        category_result = self.ai_client.analyze_email_category(subject, body)

        category = category_result.get("category", "unknown") if category_result.get("success") else "unknown"
        is_quote_request = category == "quote_request"

        # Step 2: Log email in database
        email_log = EmailLog(
            message_id=internet_message_id,
            received_at=datetime.fromisoformat(received_at.replace('Z', '+00:00')) if received_at else datetime.utcnow(),
            from_address=from_address,
            subject=subject,
            body=body,
            attachments=None,  # TODO: Handle attachments in future
            status="pending" if is_quote_request else "informational"
        )
        db.add(email_log)
        db.flush()  # Get the ID

        # Step 3: If quote request, parse with AI
        if is_quote_request:
            logger.info(f"  -> Identified as quote request, parsing...")
            self._parse_quote_request(db, email_log, subject, body, from_name, from_address)
            return "quote_request"

        logger.info(f"  -> Categorized as '{category}', not processing further")
        return "other"

    def _parse_quote_request(self, db, email_log: EmailLog, subject: str, body: str,
                            from_name: str, from_address: str):
        """Parse quote request with AI and store in database"""

        sender_info = {"name": from_name, "email": from_address}

        # Parse with Claude AI
        parse_result = self.ai_client.parse_email_for_quote(subject, body, sender_info)

        if not parse_result.get("success"):
            logger.error(f"Failed to parse quote request: {parse_result.get('error')}")
            email_log.status = "error"
            return

        parsed_data = parse_result.get("data", {})
        confidence = parse_result.get("confidence", 0.0)

        # Extract customer info
        customer = parsed_data.get("customer", {})
        doors = parsed_data.get("doors", [])
        project = parsed_data.get("project", {})

        # Create QuoteRequest record
        quote_request = QuoteRequest(
            email_id=email_log.id,
            customer_name=customer.get("company_name") or customer.get("contact_name"),
            contact_email=customer.get("email") or from_address,
            contact_phone=customer.get("phone"),
            door_specs={"doors": doors} if doors else None,
            parsed_data=parsed_data,
            confidence_scores={
                "overall": confidence,
                "customer": customer.get("confidence", 0.0),
                "project": project.get("confidence", 0.0)
            },
            status="pending" if confidence >= 0.7 else "low_confidence",
            created_at=datetime.utcnow()
        )
        db.add(quote_request)
        db.flush()  # Get the ID

        # Record AI decision for audit trail
        ai_decision = AIDecision(
            quote_request_id=quote_request.id,
            decision_type="email_parse",
            input_data={"subject": subject, "body_preview": body[:500]},
            output_data=parsed_data,
            confidence_score=confidence,
            model_used=parse_result.get("model", "claude-3-5-sonnet-20241022"),
            prompt_tokens=parse_result.get("tokens", {}).get("input", 0),
            completion_tokens=parse_result.get("tokens", {}).get("output", 0),
            created_at=datetime.utcnow()
        )
        db.add(ai_decision)

        # Update email log
        email_log.status = "parsed"
        email_log.parsed_at = datetime.utcnow()

        logger.info(f"  -> Quote request parsed. Confidence: {confidence:.2f}, "
                   f"Customer: {quote_request.customer_name}, "
                   f"Doors: {len(doors)}")

    def get_pending_quote_requests(self, min_confidence: float = 0.0) -> List[QuoteRequest]:
        """Get quote requests pending review

        Args:
            min_confidence: Minimum confidence score (0.0 to 1.0)

        Returns:
            List of QuoteRequest objects
        """
        db = SessionLocal()
        try:
            query = db.query(QuoteRequest).filter(
                QuoteRequest.status.in_(["pending", "low_confidence"])
            )

            if min_confidence > 0:
                # Filter by overall confidence in confidence_scores JSON
                # This is a simplified filter - in production you'd use JSON operators
                results = [qr for qr in query.all()
                          if qr.confidence_scores.get("overall", 0) >= min_confidence]
            else:
                results = query.all()

            return results

        finally:
            db.close()

    def get_stats(self) -> Dict[str, Any]:
        """Get monitoring statistics"""
        db = SessionLocal()
        try:
            total_emails = db.query(EmailLog).count()
            parsed_emails = db.query(EmailLog).filter(EmailLog.status == "parsed").count()
            pending_quotes = db.query(QuoteRequest).filter(
                QuoteRequest.status.in_(["pending", "low_confidence"])
            ).count()

            # Get recent activity (last 24 hours)
            yesterday = datetime.utcnow() - timedelta(hours=24)
            recent_emails = db.query(EmailLog).filter(
                EmailLog.received_at >= yesterday
            ).count()

            return {
                "total_emails_logged": total_emails,
                "total_emails_parsed": parsed_emails,
                "pending_quote_requests": pending_quotes,
                "emails_last_24h": recent_emails
            }

        finally:
            db.close()


# Global email monitor instance
email_monitor = EmailMonitorService()
