"""
Email Categorization Learning Service
Learns from user feedback to improve email categorization accuracy over time
"""

import logging
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import and_, desc

from app.db.models import EmailLog
from app.integrations.ai.client import ClaudeAIClient

logger = logging.getLogger(__name__)


class EmailCategorizationService:
    """Service for learning-based email categorization"""

    def __init__(self, db: Session):
        self.db = db
        self.ai_client = ClaudeAIClient()

    def categorize_email(self, subject: str, body: str, from_address: str) -> Dict[str, Any]:
        """
        Categorize email using AI with learning from past examples

        Returns:
            Dict with category, confidence, and reasoning
        """
        # Get learning examples (past categorizations)
        learning_examples = self._get_learning_examples()

        # Build enhanced prompt with examples
        prompt = self._build_categorization_prompt(
            subject, body, from_address, learning_examples
        )

        # Call AI
        result = self.ai_client.analyze_email_category_with_context(
            subject, body, learning_examples
        )

        return result

    def _get_learning_examples(self, max_examples: int = 10) -> List[Dict[str, Any]]:
        """
        Retrieve past categorizations that were verified by users
        Returns examples of both quote requests AND non-quote emails
        """
        # Get verified examples (where user confirmed or corrected AI categorization)
        verified_emails = self.db.query(EmailLog).filter(
            and_(
                EmailLog.user_verified_category.isnot(None),
                EmailLog.categorization_correct.isnot(None)
            )
        ).order_by(desc(EmailLog.received_at)).limit(max_examples * 2).all()

        examples = []
        quote_request_count = 0
        non_quote_count = 0
        max_per_category = max_examples // 2

        for email in verified_emails:
            # Balance examples: get equal numbers of quote requests and non-quotes
            is_quote = email.user_verified_category == "quote_request"

            if is_quote and quote_request_count >= max_per_category:
                continue
            if not is_quote and non_quote_count >= max_per_category:
                continue

            examples.append({
                "subject": email.subject,
                "body": email.body[:500],  # First 500 chars
                "category": email.user_verified_category,
                "was_correct": email.categorization_correct,
                "ai_reasoning": email.ai_category_reasoning
            })

            if is_quote:
                quote_request_count += 1
            else:
                non_quote_count += 1

            if len(examples) >= max_examples:
                break

        logger.info(f"Retrieved {len(examples)} learning examples ({quote_request_count} quote requests, {non_quote_count} non-quotes)")
        return examples

    def _build_categorization_prompt(
        self,
        subject: str,
        body: str,
        from_address: str,
        examples: List[Dict[str, Any]]
    ) -> str:
        """Build enhanced categorization prompt with learning examples"""

        examples_text = ""
        if examples:
            examples_text = "\n**LEARNING EXAMPLES (from past emails):**\n\n"
            for i, ex in enumerate(examples, 1):
                examples_text += f"Example {i}:\n"
                examples_text += f"Subject: {ex['subject']}\n"
                examples_text += f"Body excerpt: {ex['body'][:200]}...\n"
                examples_text += f"Correct Category: {ex['category']}\n"
                if ex.get('ai_reasoning'):
                    examples_text += f"Reasoning: {ex['ai_reasoning']}\n"
                examples_text += "\n"

        prompt = f"""You are analyzing emails for a door manufacturing company.
CRITICAL: Only 20-30% of emails are actual quote requests. Most are general business correspondence.

{examples_text}

**EMAIL TO CATEGORIZE:**
From: {from_address}
Subject: {subject}
Body: {body[:1000]}

**CATEGORIES:**
- "quote_request" - Explicitly requesting a NEW price quote for doors/products (BE STRICT - must clearly ask for pricing)
- "quote_modification" - Modifying/changing an EXISTING quote (references a quote number, asks to change specs, revise dimensions, etc.)
- "order_confirmation" - Confirming an existing order
- "invoice" - Invoice or payment related
- "inquiry" - General question (NOT asking for a quote)
- "complaint" - Issue or complaint
- "shipping" - Shipping/delivery related
- "general" - General business correspondence
- "other" - Doesn't fit above categories

**IMPORTANT GUIDELINES:**
- A quote request must EXPLICITLY ask for pricing/quote for NEW doors
- Questions about products WITHOUT asking for a quote = "inquiry", NOT "quote_request"
- Order updates, confirmations = "order_confirmation"
- Invoices, receipts, payment info = "invoice"
- Be conservative: when unsure, choose "general" or "inquiry" rather than "quote_request"

**QUOTE MODIFICATION DETECTION (CRITICAL):**
- Look for existing quote references: "Q-12345", "quote #", "AI-QR-", "regarding the quote", "revise", "change"
- Phrases that indicate modification: "change the dimensions", "update the quote", "revise to", "correction", "modify"
- Email replies in a thread about an existing quote = likely modification
- If changing specs on an already-requested quote = "quote_modification", NOT "quote_request"

**Output JSON only:**
```json
{{
  "category": "category_name",
  "confidence": 0.0-1.0,
  "reasoning": "Specific reason for this categorization (2-3 sentences)",
  "is_modification": true/false,
  "referenced_quote_number": "quote number if mentioned, or null",
  "modification_type": "dimension_change|color_change|quantity_change|spec_change|cancellation|null"
}}
```
"""
        return prompt

    def record_user_verification(
        self,
        email_id: int,
        user_verified_category: str,
        was_ai_correct: bool
    ) -> None:
        """
        Record when a user verifies or corrects an email categorization
        This builds the learning dataset
        """
        email = self.db.query(EmailLog).filter(EmailLog.id == email_id).first()
        if not email:
            logger.error(f"Email {email_id} not found for verification")
            return

        email.user_verified_category = user_verified_category
        email.categorization_correct = was_ai_correct
        self.db.commit()

        logger.info(
            f"User verified email {email_id}: "
            f"AI said '{email.ai_category}', user says '{user_verified_category}' "
            f"(correct={was_ai_correct})"
        )

    def get_categorization_stats(self) -> Dict[str, Any]:
        """Get statistics on categorization accuracy"""
        # Total emails categorized
        total = self.db.query(EmailLog).filter(
            EmailLog.ai_category.isnot(None)
        ).count()

        # Emails verified by users
        verified = self.db.query(EmailLog).filter(
            EmailLog.user_verified_category.isnot(None)
        ).count()

        # Correct categorizations
        correct = self.db.query(EmailLog).filter(
            and_(
                EmailLog.categorization_correct == True,
                EmailLog.user_verified_category.isnot(None)
            )
        ).count()

        # Accuracy
        accuracy = (correct / verified * 100) if verified > 0 else 0

        # False positives (AI said quote_request, but it wasn't)
        false_positives = self.db.query(EmailLog).filter(
            and_(
                EmailLog.ai_category == "quote_request",
                EmailLog.user_verified_category != "quote_request",
                EmailLog.user_verified_category.isnot(None)
            )
        ).count()

        # False negatives (AI said not quote_request, but it was)
        false_negatives = self.db.query(EmailLog).filter(
            and_(
                EmailLog.ai_category != "quote_request",
                EmailLog.user_verified_category == "quote_request",
                EmailLog.user_verified_category.isnot(None)
            )
        ).count()

        # Calculate rates
        fp_rate = (false_positives / verified * 100) if verified > 0 else 0
        fn_rate = (false_negatives / verified * 100) if verified > 0 else 0
        incorrect = verified - correct

        return {
            "total_emails": total,
            "total_verified": verified,
            "correct_categorizations": correct,
            "incorrect_categorizations": incorrect,
            "accuracy_rate": round(accuracy, 1),
            "false_positive_rate": round(fp_rate, 1),
            "false_negative_rate": round(fn_rate, 1),
            "learning_examples_available": verified
        }


def get_categorization_service(db: Session) -> EmailCategorizationService:
    """Factory function to get categorization service"""
    return EmailCategorizationService(db)
