"""
Memory & Learning Service for BC AI Agent
Implements Retrieval-Augmented Generation (RAG) and learning from feedback
"""

import logging
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, desc, func

from app.db.models import (
    ParseExample, DomainKnowledge, ParseFeedback, QuoteRequest,
    EmailLog, LearningMetrics, KnowledgeType, FeedbackType
)

logger = logging.getLogger(__name__)


class MemoryService:
    """Service for memory retrieval and learning"""

    def __init__(self, db: Session):
        self.db = db

    # ========================================================================
    # RETRIEVAL-AUGMENTED GENERATION (RAG)
    # ========================================================================

    def retrieve_similar_examples(self, email_subject: str, email_body: str,
                                   max_examples: int = 3) -> List[ParseExample]:
        """Retrieve most similar parse examples for RAG

        Args:
            email_subject: Subject of new email
            email_body: Body of new email
            max_examples: Maximum number of examples to return

        Returns:
            List of ParseExample objects, sorted by relevance
        """
        logger.info(f"Retrieving up to {max_examples} similar examples")

        # Extract keywords from email for matching
        keywords = self._extract_keywords(email_subject, email_body)
        door_models = self._extract_door_models(email_subject + " " + email_body)

        # Build query for verified examples
        query = self.db.query(ParseExample).filter(
            ParseExample.is_verified == True
        )

        # If we identified door models, prioritize examples with same models
        # Note: For SQLite, door_models is stored as JSON string
        # For now, skip filtering by door model and rely on quality/recency sorting
        # TODO: Implement JSON filtering for production PostgreSQL
        # if door_models:
        #     pass  # Filtering by JSON array in SQLite is complex

        # Order by quality score and recency
        query = query.order_by(
            desc(ParseExample.quality_score),
            desc(ParseExample.created_at)
        ).limit(max_examples)

        examples = query.all()

        # Update retrieval stats
        for example in examples:
            example.times_retrieved += 1
            example.last_used_at = datetime.utcnow()

        self.db.commit()

        logger.info(f"Retrieved {len(examples)} examples (quality scores: {[e.quality_score for e in examples]})")
        return examples

    def _extract_keywords(self, subject: str, body: str) -> List[str]:
        """Extract relevant keywords from email text"""
        text = (subject + " " + body).lower()

        # Common door-related keywords
        keywords = []
        keyword_patterns = [
            'quote', 'price', 'pricing', 'cost',
            'door', 'doors', 'overhead',
            'urgent', 'asap', 'rush',
            'project', 'job',
            'installation', 'install',
            'commercial', 'residential'
        ]

        for pattern in keyword_patterns:
            if pattern in text:
                keywords.append(pattern)

        return keywords

    def _extract_door_models(self, text: str) -> List[str]:
        """Extract door model names from text"""
        text_upper = text.upper()
        models = []

        # Known door models
        known_models = [
            'TX450', 'AL976', 'AL976-SWD', 'SOLALITE',
            'KANATA', 'CRAFT', 'MILTOWN', 'BCXL'
        ]

        for model in known_models:
            if model in text_upper:
                models.append(model)

        return models

    def format_examples_for_prompt(self, examples: List[ParseExample]) -> str:
        """Format retrieved examples into prompt text for Claude

        Args:
            examples: List of ParseExample objects

        Returns:
            Formatted string to inject into Claude prompt
        """
        if not examples:
            return ""

        prompt_parts = ["\n\nHere are some examples of successfully parsed quote request emails:\n"]

        for i, example in enumerate(examples, 1):
            prompt_parts.append(f"\n--- Example {i} (Quality: {example.quality_score:.0%}) ---")
            prompt_parts.append(f"Subject: {example.email_subject}")
            prompt_parts.append(f"Body Preview: {example.email_body[:300]}...")
            prompt_parts.append(f"\nExtracted Data:")
            prompt_parts.append(f"```json\n{self._format_json(example.parsed_result)}\n```")

        prompt_parts.append("\n\nUse these examples as reference patterns for parsing the new email.\n")

        return "\n".join(prompt_parts)

    def _format_json(self, data: Dict) -> str:
        """Format JSON data for display"""
        import json
        return json.dumps(data, indent=2)

    # ========================================================================
    # KNOWLEDGE BASE
    # ========================================================================

    def get_knowledge(self, knowledge_type: KnowledgeType,
                     entity: str) -> Optional[DomainKnowledge]:
        """Get knowledge for a specific entity

        Args:
            knowledge_type: Type of knowledge (DOOR_MODEL, CUSTOMER_PREFERENCE, etc.)
            entity: Entity name (e.g., "TX450", "ABC Company")

        Returns:
            DomainKnowledge object or None
        """
        return self.db.query(DomainKnowledge).filter(
            and_(
                DomainKnowledge.knowledge_type == knowledge_type,
                DomainKnowledge.entity == entity
            )
        ).first()

    def add_or_update_knowledge(self, knowledge_type: KnowledgeType, entity: str,
                                pattern_data: Dict, source: str = "auto_extracted",
                                confidence: float = 0.5) -> DomainKnowledge:
        """Add or update domain knowledge

        Args:
            knowledge_type: Type of knowledge
            entity: Entity name
            pattern_data: The knowledge data (JSON)
            source: Source of knowledge (user_feedback, auto_extracted, manual_entry)
            confidence: Confidence in this knowledge (0-1)

        Returns:
            DomainKnowledge object
        """
        knowledge = self.get_knowledge(knowledge_type, entity)

        if knowledge:
            # Update existing
            knowledge.pattern_data = pattern_data
            knowledge.confidence = max(knowledge.confidence, confidence)  # Keep higher confidence
            knowledge.updated_at = datetime.utcnow()
            logger.info(f"Updated knowledge: {knowledge_type.value}/{entity}")
        else:
            # Create new
            knowledge = DomainKnowledge(
                knowledge_type=knowledge_type,
                entity=entity,
                pattern_data=pattern_data,
                confidence=confidence,
                source=source,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            )
            self.db.add(knowledge)
            logger.info(f"Created new knowledge: {knowledge_type.value}/{entity}")

        self.db.commit()
        return knowledge

    def get_all_door_model_knowledge(self) -> List[DomainKnowledge]:
        """Get all door model knowledge"""
        return self.db.query(DomainKnowledge).filter(
            DomainKnowledge.knowledge_type == KnowledgeType.DOOR_MODEL
        ).all()

    # ========================================================================
    # FEEDBACK & LEARNING
    # ========================================================================

    def record_feedback(self, quote_request_id: int, user_id: str,
                       feedback_type: FeedbackType, original_parse: Dict,
                       corrected_parse: Optional[Dict] = None,
                       feedback_notes: Optional[str] = None,
                       review_time_seconds: Optional[int] = None) -> ParseFeedback:
        """Record user feedback on a parse

        Args:
            quote_request_id: ID of quote request
            user_id: User who provided feedback
            feedback_type: APPROVE, CORRECT, or REJECT
            original_parse: Original AI parse
            corrected_parse: Corrected version (if CORRECT)
            feedback_notes: User's explanation
            review_time_seconds: Time spent reviewing

        Returns:
            ParseFeedback object
        """
        feedback = ParseFeedback(
            quote_request_id=quote_request_id,
            user_id=user_id,
            feedback_type=feedback_type,
            original_parse=original_parse,
            corrected_parse=corrected_parse,
            feedback_notes=feedback_notes,
            review_time_seconds=review_time_seconds,
            created_at=datetime.utcnow()
        )

        self.db.add(feedback)
        self.db.commit()

        logger.info(f"Recorded feedback: {feedback_type.value} for quote #{quote_request_id}")

        # Trigger learning from this feedback
        self._learn_from_feedback(feedback)

        return feedback

    def _learn_from_feedback(self, feedback: ParseFeedback):
        """Learn from user feedback - update examples and knowledge

        Args:
            feedback: ParseFeedback object
        """
        quote_request = self.db.query(QuoteRequest).filter(
            QuoteRequest.id == feedback.quote_request_id
        ).first()

        if not quote_request:
            return

        email_log = quote_request.email

        if feedback.feedback_type == FeedbackType.APPROVE:
            # Parse was good - add to example library
            self._add_to_example_library(
                quote_request, email_log, verified=True, quality_boost=0.2
            )
            logger.info(f"Added approved parse to example library")

        elif feedback.feedback_type == FeedbackType.CORRECT:
            # Parse was corrected - use corrected version as example
            if feedback.corrected_parse:
                # Update quote request with corrected data
                quote_request.parsed_data = feedback.corrected_parse
                quote_request.status = "approved"  # Mark as corrected/approved

                # Add corrected version to examples
                self._add_to_example_library(
                    quote_request, email_log, verified=True, quality_boost=0.3
                )

                # Extract patterns from correction
                self._extract_patterns_from_correction(feedback)

                logger.info(f"Updated quote with corrections and added to examples")

        elif feedback.feedback_type == FeedbackType.REJECT:
            # Parse was rejected - don't add to examples, but learn what went wrong
            # Could analyze original_parse to identify common errors
            logger.info(f"Parse rejected - not adding to examples")

        self.db.commit()

    def _add_to_example_library(self, quote_request: QuoteRequest, email_log: EmailLog,
                                verified: bool = False, quality_boost: float = 0.0):
        """Add a parse to the example library

        Args:
            quote_request: QuoteRequest object
            email_log: EmailLog object
            verified: Whether this example is user-verified
            quality_boost: Bonus to quality score (0-1)
        """
        # Check if example already exists
        existing = self.db.query(ParseExample).filter(
            ParseExample.quote_request_id == quote_request.id
        ).first()

        if existing:
            # Update existing example
            import json
            existing.is_verified = verified or existing.is_verified
            existing.quality_score = min(1.0, existing.quality_score + quality_boost)
            existing.parsed_result = quote_request.parsed_data
            # Update tags and door models as JSON
            tags = self._extract_tags(quote_request.parsed_data)
            door_models = self._extract_door_models_from_parse(quote_request.parsed_data)
            existing.tags = json.dumps(tags)
            existing.door_models = json.dumps(door_models)
            logger.info(f"Updated existing example #{existing.id}")
            return existing

        # Calculate quality score
        quality_score = self._calculate_quality_score(quote_request, verified, quality_boost)

        # Extract tags and door models
        tags = self._extract_tags(quote_request.parsed_data)
        door_models = self._extract_door_models_from_parse(quote_request.parsed_data)

        # Create new example
        # Convert lists to JSON for SQLite compatibility
        import json
        tags_json = json.dumps(tags) if tags else json.dumps([])
        door_models_json = json.dumps(door_models) if door_models else json.dumps([])

        example = ParseExample(
            quote_request_id=quote_request.id,
            email_subject=email_log.subject,
            email_body=email_log.body,
            parsed_result=quote_request.parsed_data,
            is_verified=verified,
            quality_score=quality_score,
            completeness_score=self._calculate_completeness(quote_request.parsed_data),
            tags=tags_json,  # Store as JSON string
            door_models=door_models_json,  # Store as JSON string
            customer_name=quote_request.customer_name,
            created_at=datetime.utcnow()
        )

        self.db.add(example)
        logger.info(f"Added new example to library (quality={quality_score:.2f})")

        return example

    def _calculate_quality_score(self, quote_request: QuoteRequest,
                                 verified: bool, quality_boost: float) -> float:
        """Calculate quality score for an example"""
        score = 0.0

        # Base score from AI confidence
        confidence = quote_request.confidence_scores.get("overall", 0.5)
        score += confidence * 0.4  # 40% weight

        # Verified examples get bonus
        if verified:
            score += 0.4  # 40% weight

        # Completeness matters
        completeness = self._calculate_completeness(quote_request.parsed_data)
        score += completeness * 0.2  # 20% weight

        # Add any quality boost
        score += quality_boost

        return min(1.0, score)  # Cap at 1.0

    def _calculate_completeness(self, parsed_data: Dict) -> float:
        """Calculate how complete a parse is (0-1)"""
        if not parsed_data:
            return 0.0

        total_fields = 0
        filled_fields = 0

        # Check customer fields
        customer = parsed_data.get("customer", {})
        customer_fields = ["company_name", "contact_name", "phone", "email"]
        for field in customer_fields:
            total_fields += 1
            if customer.get(field):
                filled_fields += 1

        # Check door fields
        doors = parsed_data.get("doors", [])
        if doors:
            for door in doors:
                door_fields = ["model", "quantity", "width_ft", "height_ft", "color"]
                for field in door_fields:
                    total_fields += 1
                    if door.get(field) is not None:
                        filled_fields += 1

        # Check project fields
        project = parsed_data.get("project", {})
        project_fields = ["name", "delivery_date"]
        for field in project_fields:
            total_fields += 1
            if project.get(field):
                filled_fields += 1

        return filled_fields / total_fields if total_fields > 0 else 0.0

    def _extract_tags(self, parsed_data: Dict) -> List[str]:
        """Extract tags from parsed data for categorization"""
        tags = []

        # Add door models as tags
        doors = parsed_data.get("doors", [])
        if len(doors) > 1:
            tags.append("multi-door")
        elif len(doors) == 1:
            tags.append("single-door")

        for door in doors:
            if door.get("model"):
                tags.append(door["model"])
            if door.get("glazing"):
                tags.append("has-glazing")

        # Completeness tag
        completeness = self._calculate_completeness(parsed_data)
        if completeness >= 0.9:
            tags.append("complete-specs")
        elif completeness >= 0.7:
            tags.append("partial-specs")

        return tags

    def _extract_door_models_from_parse(self, parsed_data: Dict) -> List[str]:
        """Extract list of door models from parsed data"""
        models = []
        doors = parsed_data.get("doors", [])
        for door in doors:
            model = door.get("model")
            if model and model not in models:
                models.append(model)
        return models

    def _extract_patterns_from_correction(self, feedback: ParseFeedback):
        """Extract learning patterns from a correction"""
        # Compare original vs corrected to identify patterns
        # This is a placeholder for more sophisticated pattern extraction
        logger.info(f"Analyzing correction for patterns...")

        # Example: If a specific field is often corrected for a door model,
        # we could store that as knowledge

    # ========================================================================
    # METRICS & ANALYTICS
    # ========================================================================

    def calculate_daily_metrics(self, date: datetime = None) -> LearningMetrics:
        """Calculate learning metrics for a given date

        Args:
            date: Date to calculate metrics for (default: today)

        Returns:
            LearningMetrics object
        """
        if date is None:
            date = datetime.utcnow()

        # Get start and end of day
        start_of_day = date.replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_day = start_of_day + timedelta(days=1)

        # Count feedbacks by type
        feedbacks = self.db.query(ParseFeedback).filter(
            and_(
                ParseFeedback.created_at >= start_of_day,
                ParseFeedback.created_at < end_of_day
            )
        ).all()

        total_parses = len(feedbacks)
        approved = sum(1 for f in feedbacks if f.feedback_type == FeedbackType.APPROVE)
        corrected = sum(1 for f in feedbacks if f.feedback_type == FeedbackType.CORRECT)
        rejected = sum(1 for f in feedbacks if f.feedback_type == FeedbackType.REJECT)

        approval_rate = approved / total_parses if total_parses > 0 else None

        # Count examples and knowledge
        total_examples = self.db.query(ParseExample).count()
        verified_examples = self.db.query(ParseExample).filter(
            ParseExample.is_verified == True
        ).count()
        total_knowledge = self.db.query(DomainKnowledge).count()

        # Create metrics record
        metrics = LearningMetrics(
            metric_date=start_of_day,
            total_parses=total_parses,
            approved_parses=approved,
            corrected_parses=corrected,
            rejected_parses=rejected,
            approval_rate=approval_rate,
            total_examples=total_examples,
            verified_examples=verified_examples,
            total_knowledge_items=total_knowledge,
            model_used="claude-sonnet-4-5-20250929",
            created_at=datetime.utcnow()
        )

        self.db.add(metrics)
        self.db.commit()

        logger.info(f"Calculated metrics for {date.date()}: {approval_rate:.1%} approval rate")

        return metrics


# Global memory service instance (will be initialized with DB session)
def get_memory_service(db: Session) -> MemoryService:
    """Get memory service instance with database session"""
    return MemoryService(db)
