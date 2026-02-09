"""
Memory & Learning Service for BC AI Agent
Implements Retrieval-Augmented Generation (RAG) and learning from feedback

Enhanced with:
- Semantic similarity scoring for better example matching
- Pattern extraction from user corrections
- Customer-specific learning preferences
- Confidence calibration based on past performance
"""

import logging
import re
import math
from collections import Counter
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, desc, func

from app.db.models import (
    ParseExample, DomainKnowledge, ParseFeedback, QuoteRequest,
    EmailLog, LearningMetrics, KnowledgeType, FeedbackType
)

logger = logging.getLogger(__name__)


class TextSimilarity:
    """Text similarity utilities for semantic matching"""

    # Domain-specific vocabulary with weights
    DOMAIN_TERMS = {
        # Door models (high importance)
        'tx450': 3.0, 'al976': 3.0, 'al976-swd': 3.0, 'solalite': 3.0,
        'kanata': 3.0, 'craft': 3.0, 'miltown': 3.0, 'bcxl': 3.0,
        # Door specs (medium-high importance)
        'thermopane': 2.5, 'insulated': 2.5, 'polycarbonate': 2.5,
        'galvanized': 2.0, 'powder': 2.0, 'coated': 2.0,
        # Dimensions (medium importance)
        'width': 1.5, 'height': 1.5, 'feet': 1.5, 'inches': 1.5,
        # Business terms
        'quote': 2.0, 'pricing': 2.0, 'urgent': 2.0, 'rush': 2.0,
        'commercial': 1.8, 'residential': 1.8, 'industrial': 1.8,
        # Actions
        'install': 1.5, 'installation': 1.5, 'delivery': 1.5,
    }

    @staticmethod
    def tokenize(text: str) -> List[str]:
        """Tokenize text into lowercase words"""
        if not text:
            return []
        # Remove special chars, lowercase, split
        text = re.sub(r'[^\w\s-]', ' ', text.lower())
        return [w for w in text.split() if len(w) > 2]

    @staticmethod
    def extract_dimensions(text: str) -> List[Tuple[float, float]]:
        """Extract width x height dimensions from text"""
        dimensions = []
        # Pattern: 10'6" x 12' or 10x12 or 10' x 12'
        patterns = [
            r"(\d+)['\"]?\s*[xX×]\s*(\d+)['\"]?",
            r"(\d+)\s*(?:ft|feet)?\s*[xX×]\s*(\d+)\s*(?:ft|feet)?",
        ]
        for pattern in patterns:
            matches = re.findall(pattern, text)
            for m in matches:
                try:
                    dimensions.append((float(m[0]), float(m[1])))
                except ValueError:
                    pass
        return dimensions

    @classmethod
    def calculate_similarity(cls, text1: str, text2: str) -> float:
        """
        Calculate semantic similarity between two texts (0-1)
        Uses weighted term frequency with domain-specific boosting
        """
        tokens1 = cls.tokenize(text1)
        tokens2 = cls.tokenize(text2)

        if not tokens1 or not tokens2:
            return 0.0

        # Calculate weighted term frequencies
        def weighted_freq(tokens: List[str]) -> Counter:
            freq = Counter()
            for token in tokens:
                weight = cls.DOMAIN_TERMS.get(token, 1.0)
                freq[token] += weight
            return freq

        freq1 = weighted_freq(tokens1)
        freq2 = weighted_freq(tokens2)

        # Get all unique terms
        all_terms = set(freq1.keys()) | set(freq2.keys())

        # Calculate cosine similarity
        dot_product = sum(freq1.get(t, 0) * freq2.get(t, 0) for t in all_terms)
        magnitude1 = math.sqrt(sum(v**2 for v in freq1.values()))
        magnitude2 = math.sqrt(sum(v**2 for v in freq2.values()))

        if magnitude1 == 0 or magnitude2 == 0:
            return 0.0

        cosine_sim = dot_product / (magnitude1 * magnitude2)

        # Boost for matching dimensions
        dims1 = cls.extract_dimensions(text1)
        dims2 = cls.extract_dimensions(text2)
        dim_boost = 0.0
        for d1 in dims1:
            for d2 in dims2:
                if d1 == d2:
                    dim_boost += 0.1  # Exact dimension match
                elif abs(d1[0] - d2[0]) <= 1 and abs(d1[1] - d2[1]) <= 1:
                    dim_boost += 0.05  # Close dimension match

        # Boost for matching door models
        models1 = set(t for t in tokens1 if t in ['tx450', 'al976', 'al976-swd', 'solalite', 'kanata', 'craft', 'miltown', 'bcxl'])
        models2 = set(t for t in tokens2 if t in ['tx450', 'al976', 'al976-swd', 'solalite', 'kanata', 'craft', 'miltown', 'bcxl'])
        model_boost = 0.2 if models1 & models2 else 0.0

        return min(1.0, cosine_sim + dim_boost + model_boost)


class MemoryService:
    """Service for memory retrieval and learning"""

    def __init__(self, db: Session):
        self.db = db

    # ========================================================================
    # RETRIEVAL-AUGMENTED GENERATION (RAG)
    # ========================================================================

    def retrieve_similar_examples(self, email_subject: str, email_body: str,
                                   max_examples: int = 3,
                                   customer_email: str = None) -> List[ParseExample]:
        """Retrieve most similar parse examples for RAG using semantic similarity

        Args:
            email_subject: Subject of new email
            email_body: Body of new email
            max_examples: Maximum number of examples to return
            customer_email: Optional customer email for preference lookup

        Returns:
            List of ParseExample objects, sorted by relevance
        """
        logger.info(f"Retrieving up to {max_examples} similar examples with semantic matching")

        # Combine subject and body for matching
        new_email_text = f"{email_subject} {email_body}"

        # Get all verified examples (we'll score and rank them)
        all_examples = self.db.query(ParseExample).filter(
            ParseExample.is_verified == True
        ).all()

        if not all_examples:
            logger.info("No verified examples available")
            return []

        # Score each example by semantic similarity
        scored_examples = []
        for example in all_examples:
            example_text = f"{example.email_subject} {example.email_body}"

            # Calculate semantic similarity
            similarity = TextSimilarity.calculate_similarity(new_email_text, example_text)

            # Boost for quality score
            quality_boost = example.quality_score * 0.2

            # Boost for customer match (if same customer, their past quotes are more relevant)
            customer_boost = 0.0
            if customer_email and example.customer_name:
                # Check if this example was from same customer
                quote_req = self.db.query(QuoteRequest).filter(
                    QuoteRequest.id == example.quote_request_id
                ).first()
                if quote_req and quote_req.contact_email == customer_email:
                    customer_boost = 0.15
                    logger.debug(f"Customer match boost for example {example.id}")

            # Recency boost (newer examples slightly preferred)
            days_old = (datetime.utcnow() - example.created_at).days
            recency_boost = max(0, 0.05 * (1 - days_old / 365))  # Decay over 1 year

            # Combined score
            total_score = similarity + quality_boost + customer_boost + recency_boost

            scored_examples.append((example, total_score, similarity))

        # Sort by total score (descending)
        scored_examples.sort(key=lambda x: x[1], reverse=True)

        # Take top N
        top_examples = scored_examples[:max_examples]

        # Update retrieval stats and get examples
        result = []
        for example, total_score, similarity in top_examples:
            example.times_retrieved += 1
            example.last_used_at = datetime.utcnow()
            result.append(example)
            logger.debug(f"Example {example.id}: similarity={similarity:.2f}, total_score={total_score:.2f}")

        self.db.commit()

        logger.info(f"Retrieved {len(result)} examples (scores: {[f'{s[1]:.2f}' for s in top_examples]})")
        return result

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
        """Extract learning patterns from a correction and store as domain knowledge

        Analyzes differences between original and corrected parses to learn:
        - Common field corrections (e.g., always missing phone for certain customers)
        - Door model misidentification patterns
        - Dimension parsing errors
        - Customer preference patterns
        """
        logger.info(f"Analyzing correction for patterns...")

        original = feedback.original_parse or {}
        corrected = feedback.corrected_parse or {}

        if not original or not corrected:
            return

        corrections_found = []

        # Compare customer info
        orig_customer = original.get("customer", {})
        corr_customer = corrected.get("customer", {})
        customer_corrections = self._compare_dicts(orig_customer, corr_customer, "customer")
        corrections_found.extend(customer_corrections)

        # Compare doors
        orig_doors = original.get("doors", [])
        corr_doors = corrected.get("doors", [])

        for i, (orig_door, corr_door) in enumerate(zip(orig_doors, corr_doors)):
            door_corrections = self._compare_dicts(orig_door, corr_door, f"door_{i}")
            corrections_found.extend(door_corrections)

            # Special handling for door model corrections - these are valuable!
            if orig_door.get("model") != corr_door.get("model"):
                self._learn_model_correction(
                    wrong_model=orig_door.get("model"),
                    correct_model=corr_door.get("model"),
                    context=feedback
                )

        # Compare project info
        orig_project = original.get("project", {})
        corr_project = corrected.get("project", {})
        project_corrections = self._compare_dicts(orig_project, corr_project, "project")
        corrections_found.extend(project_corrections)

        # Log and store correction patterns
        if corrections_found:
            logger.info(f"Found {len(corrections_found)} corrections: {corrections_found[:5]}")

            # Store as domain knowledge for future reference
            self._store_correction_patterns(corrections_found, feedback)

    def _compare_dicts(self, orig: Dict, corrected: Dict, prefix: str) -> List[Dict]:
        """Compare two dicts and return list of corrections"""
        corrections = []

        all_keys = set(orig.keys()) | set(corrected.keys())

        for key in all_keys:
            orig_val = orig.get(key)
            corr_val = corrected.get(key)

            if orig_val != corr_val:
                corrections.append({
                    "field": f"{prefix}.{key}",
                    "original": orig_val,
                    "corrected": corr_val,
                    "correction_type": self._classify_correction(orig_val, corr_val)
                })

        return corrections

    def _classify_correction(self, original, corrected) -> str:
        """Classify the type of correction made"""
        if original is None and corrected is not None:
            return "missing_value_added"
        elif original is not None and corrected is None:
            return "incorrect_value_removed"
        elif isinstance(original, (int, float)) and isinstance(corrected, (int, float)):
            return "numeric_correction"
        elif isinstance(original, str) and isinstance(corrected, str):
            if original.lower() == corrected.lower():
                return "case_correction"
            elif original in corrected or corrected in original:
                return "partial_match"
            else:
                return "value_replacement"
        else:
            return "type_change"

    def _learn_model_correction(self, wrong_model: str, correct_model: str, context: ParseFeedback):
        """Learn from door model misidentification"""
        if not wrong_model or not correct_model:
            return

        logger.info(f"Learning model correction: {wrong_model} -> {correct_model}")

        # Store this as domain knowledge
        knowledge_key = f"model_confusion_{wrong_model}_{correct_model}"

        existing = self.db.query(DomainKnowledge).filter(
            and_(
                DomainKnowledge.knowledge_type == KnowledgeType.PARSING_PATTERN,
                DomainKnowledge.entity == knowledge_key
            )
        ).first()

        if existing:
            # Increment confusion count
            pattern_data = existing.pattern_data or {}
            pattern_data["count"] = pattern_data.get("count", 0) + 1
            pattern_data["last_seen"] = datetime.utcnow().isoformat()
            existing.pattern_data = pattern_data
            existing.confidence = min(1.0, existing.confidence + 0.1)
        else:
            # Create new knowledge entry
            self.add_or_update_knowledge(
                knowledge_type=KnowledgeType.PARSING_PATTERN,
                entity=knowledge_key,
                pattern_data={
                    "wrong_model": wrong_model,
                    "correct_model": correct_model,
                    "count": 1,
                    "first_seen": datetime.utcnow().isoformat(),
                    "last_seen": datetime.utcnow().isoformat()
                },
                source="correction_learning",
                confidence=0.3
            )

    def _store_correction_patterns(self, corrections: List[Dict], feedback: ParseFeedback):
        """Store correction patterns as domain knowledge for future use"""
        # Group corrections by field
        field_corrections = {}
        for corr in corrections:
            field = corr["field"]
            if field not in field_corrections:
                field_corrections[field] = []
            field_corrections[field].append(corr)

        # For fields with multiple corrections, store the pattern
        for field, corrs in field_corrections.items():
            knowledge_key = f"field_correction_{field}"

            existing = self.db.query(DomainKnowledge).filter(
                and_(
                    DomainKnowledge.knowledge_type == KnowledgeType.PARSING_PATTERN,
                    DomainKnowledge.entity == knowledge_key
                )
            ).first()

            if existing:
                pattern_data = existing.pattern_data or {}
                pattern_data["correction_count"] = pattern_data.get("correction_count", 0) + len(corrs)
                pattern_data["last_corrections"] = corrs[:3]  # Keep last 3 examples
                pattern_data["last_seen"] = datetime.utcnow().isoformat()
                existing.pattern_data = pattern_data
            else:
                self.add_or_update_knowledge(
                    knowledge_type=KnowledgeType.PARSING_PATTERN,
                    entity=knowledge_key,
                    pattern_data={
                        "field": field,
                        "correction_count": len(corrs),
                        "correction_types": list(set(c["correction_type"] for c in corrs)),
                        "last_corrections": corrs[:3],
                        "first_seen": datetime.utcnow().isoformat(),
                        "last_seen": datetime.utcnow().isoformat()
                    },
                    source="correction_learning",
                    confidence=0.2
                )

    # ========================================================================
    # CUSTOMER-SPECIFIC LEARNING
    # ========================================================================

    def learn_customer_preferences(self, customer_email: str, customer_name: str,
                                   quote_request: QuoteRequest):
        """Learn preferences for a specific customer from their quote requests

        Args:
            customer_email: Customer's email address
            customer_name: Customer's company name
            quote_request: Completed/approved quote request
        """
        if not customer_email:
            return

        logger.info(f"Learning preferences for customer: {customer_email}")

        # Get or create customer knowledge entry
        knowledge = self.get_knowledge(KnowledgeType.CUSTOMER_PREFERENCE, customer_email)

        parsed_data = quote_request.parsed_data or {}
        doors = parsed_data.get("doors", [])

        if knowledge:
            # Update existing preferences
            prefs = knowledge.pattern_data or {}
        else:
            prefs = {
                "customer_name": customer_name,
                "first_seen": datetime.utcnow().isoformat(),
                "quote_count": 0,
                "preferred_models": {},
                "common_sizes": [],
                "typical_quantities": [],
                "preferred_colors": {},
                "common_glazing": {},
                "usually_needs_installation": None
            }

        # Update quote count
        prefs["quote_count"] = prefs.get("quote_count", 0) + 1
        prefs["last_quote"] = datetime.utcnow().isoformat()

        # Track door model preferences
        for door in doors:
            model = door.get("model")
            if model:
                model_counts = prefs.get("preferred_models", {})
                model_counts[model] = model_counts.get(model, 0) + 1
                prefs["preferred_models"] = model_counts

            # Track colors
            color = door.get("color")
            if color:
                color_counts = prefs.get("preferred_colors", {})
                color_counts[color] = color_counts.get(color, 0) + 1
                prefs["preferred_colors"] = color_counts

            # Track glazing
            glazing = door.get("glazing")
            if glazing:
                glazing_counts = prefs.get("common_glazing", {})
                glazing_counts[glazing] = glazing_counts.get(glazing, 0) + 1
                prefs["common_glazing"] = glazing_counts

            # Track sizes
            if door.get("width_ft") and door.get("height_ft"):
                size = f"{door['width_ft']}x{door['height_ft']}"
                sizes = prefs.get("common_sizes", [])
                if size not in sizes:
                    sizes.append(size)
                    prefs["common_sizes"] = sizes[-10:]  # Keep last 10

        # Track installation preference
        project = parsed_data.get("project", {})
        if project.get("installation_required") is not None:
            prefs["usually_needs_installation"] = project["installation_required"]

        # Save updated preferences
        self.add_or_update_knowledge(
            knowledge_type=KnowledgeType.CUSTOMER_PREFERENCE,
            entity=customer_email,
            pattern_data=prefs,
            source="quote_learning",
            confidence=min(0.9, 0.3 + prefs["quote_count"] * 0.1)  # Confidence grows with more quotes
        )

        logger.info(f"Updated preferences for {customer_email}: {prefs['quote_count']} quotes, "
                   f"preferred models: {list(prefs.get('preferred_models', {}).keys())}")

    def get_customer_context(self, customer_email: str) -> Optional[str]:
        """Get customer-specific context to inject into parsing prompt

        Args:
            customer_email: Customer's email address

        Returns:
            Formatted string with customer preferences, or None
        """
        if not customer_email:
            return None

        knowledge = self.get_knowledge(KnowledgeType.CUSTOMER_PREFERENCE, customer_email)
        if not knowledge:
            return None

        prefs = knowledge.pattern_data or {}

        if prefs.get("quote_count", 0) < 2:
            return None  # Not enough history

        context_parts = [f"\n**Known Customer: {prefs.get('customer_name', customer_email)}**"]
        context_parts.append(f"- Previous quotes: {prefs.get('quote_count', 0)}")

        # Add preferred models
        preferred_models = prefs.get("preferred_models", {})
        if preferred_models:
            top_models = sorted(preferred_models.items(), key=lambda x: x[1], reverse=True)[:3]
            context_parts.append(f"- Usually orders: {', '.join(m[0] for m in top_models)}")

        # Add common sizes
        common_sizes = prefs.get("common_sizes", [])
        if common_sizes:
            context_parts.append(f"- Common sizes: {', '.join(common_sizes[-5:])}")

        # Add installation preference
        if prefs.get("usually_needs_installation") is not None:
            install_text = "usually requires" if prefs["usually_needs_installation"] else "usually doesn't need"
            context_parts.append(f"- {install_text} installation")

        context_parts.append("")
        return "\n".join(context_parts)

    # ========================================================================
    # CONFIDENCE CALIBRATION
    # ========================================================================

    def get_calibrated_confidence(self, raw_confidence: float, door_model: str = None,
                                  customer_email: str = None) -> float:
        """Calibrate AI confidence based on historical performance

        Args:
            raw_confidence: AI's raw confidence score (0-1)
            door_model: Door model being parsed (optional)
            customer_email: Customer email (optional)

        Returns:
            Calibrated confidence score (0-1)
        """
        adjustments = []

        # Check historical accuracy for this door model
        if door_model:
            model_knowledge = self.get_knowledge(KnowledgeType.DOOR_MODEL, door_model)
            if model_knowledge:
                model_data = model_knowledge.pattern_data or {}
                historical_accuracy = model_data.get("parse_accuracy", None)
                if historical_accuracy is not None:
                    # If we historically do poorly on this model, lower confidence
                    if historical_accuracy < 0.7:
                        adjustments.append(-0.15)
                    elif historical_accuracy > 0.9:
                        adjustments.append(0.05)

        # Check if we have correction patterns for common fields
        common_correction_patterns = self.db.query(DomainKnowledge).filter(
            and_(
                DomainKnowledge.knowledge_type == KnowledgeType.PARSING_PATTERN,
                DomainKnowledge.entity.like("field_correction_%")
            )
        ).all()

        # If we have many correction patterns, we might be overconfident
        if len(common_correction_patterns) > 10:
            adjustments.append(-0.05)

        # Customer familiarity bonus
        if customer_email:
            customer_knowledge = self.get_knowledge(KnowledgeType.CUSTOMER_PREFERENCE, customer_email)
            if customer_knowledge:
                quote_count = (customer_knowledge.pattern_data or {}).get("quote_count", 0)
                if quote_count >= 5:
                    adjustments.append(0.1)  # We know this customer well
                elif quote_count >= 2:
                    adjustments.append(0.05)

        # Apply adjustments
        calibrated = raw_confidence + sum(adjustments)

        # Clamp to valid range
        calibrated = max(0.1, min(0.95, calibrated))

        if adjustments:
            logger.debug(f"Calibrated confidence: {raw_confidence:.2f} -> {calibrated:.2f} "
                        f"(adjustments: {adjustments})")

        return calibrated

    def update_model_accuracy(self, door_model: str, was_correct: bool):
        """Update historical accuracy tracking for a door model

        Args:
            door_model: The door model
            was_correct: Whether the parse was correct
        """
        if not door_model:
            return

        knowledge = self.get_knowledge(KnowledgeType.DOOR_MODEL, door_model)

        if knowledge:
            data = knowledge.pattern_data or {}
        else:
            data = {
                "model_name": door_model,
                "parse_count": 0,
                "correct_count": 0,
                "parse_accuracy": None
            }

        data["parse_count"] = data.get("parse_count", 0) + 1
        if was_correct:
            data["correct_count"] = data.get("correct_count", 0) + 1

        # Calculate rolling accuracy
        if data["parse_count"] > 0:
            data["parse_accuracy"] = data["correct_count"] / data["parse_count"]

        self.add_or_update_knowledge(
            knowledge_type=KnowledgeType.DOOR_MODEL,
            entity=door_model,
            pattern_data=data,
            source="accuracy_tracking",
            confidence=min(0.9, 0.5 + data["parse_count"] * 0.05)
        )

    # ========================================================================
    # LEARNING ANALYTICS
    # ========================================================================

    def get_learning_summary(self) -> Dict[str, Any]:
        """Get a comprehensive summary of the learning system's state

        Returns:
            Dict with learning statistics and insights
        """
        # Count examples
        total_examples = self.db.query(ParseExample).count()
        verified_examples = self.db.query(ParseExample).filter(
            ParseExample.is_verified == True
        ).count()

        # Count knowledge items by type
        knowledge_by_type = {}
        for kt in KnowledgeType:
            count = self.db.query(DomainKnowledge).filter(
                DomainKnowledge.knowledge_type == kt
            ).count()
            knowledge_by_type[kt.value] = count

        # Get recent feedback stats
        week_ago = datetime.utcnow() - timedelta(days=7)
        recent_feedback = self.db.query(ParseFeedback).filter(
            ParseFeedback.created_at >= week_ago
        ).all()

        approved = sum(1 for f in recent_feedback if f.feedback_type == FeedbackType.APPROVE)
        corrected = sum(1 for f in recent_feedback if f.feedback_type == FeedbackType.CORRECT)
        rejected = sum(1 for f in recent_feedback if f.feedback_type == FeedbackType.REJECT)
        total = len(recent_feedback)

        # Get top correction patterns
        top_corrections = self.db.query(DomainKnowledge).filter(
            DomainKnowledge.entity.like("field_correction_%")
        ).order_by(desc(DomainKnowledge.confidence)).limit(5).all()

        correction_insights = []
        for c in top_corrections:
            data = c.pattern_data or {}
            correction_insights.append({
                "field": data.get("field", c.entity),
                "correction_count": data.get("correction_count", 0),
                "types": data.get("correction_types", [])
            })

        # Get customer stats
        customer_count = self.db.query(DomainKnowledge).filter(
            DomainKnowledge.knowledge_type == KnowledgeType.CUSTOMER_PREFERENCE
        ).count()

        repeat_customers = self.db.query(DomainKnowledge).filter(
            and_(
                DomainKnowledge.knowledge_type == KnowledgeType.CUSTOMER_PREFERENCE,
                DomainKnowledge.confidence >= 0.5  # Have had multiple quotes
            )
        ).count()

        return {
            "examples": {
                "total": total_examples,
                "verified": verified_examples,
                "unverified": total_examples - verified_examples
            },
            "knowledge": knowledge_by_type,
            "recent_week": {
                "total_feedback": total,
                "approved": approved,
                "corrected": corrected,
                "rejected": rejected,
                "approval_rate": (approved / total * 100) if total > 0 else None
            },
            "top_correction_patterns": correction_insights,
            "customers": {
                "total_known": customer_count,
                "repeat_customers": repeat_customers
            },
            "generated_at": datetime.utcnow().isoformat()
        }

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
