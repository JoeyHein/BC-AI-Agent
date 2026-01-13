# AI Memory & Learning System Architecture

## Overview

The memory system enables the AI to learn from past parses and user feedback, continuously improving accuracy over time. This transforms the AI from a stateless parser into an adaptive learning system.

## Core Components

### 1. Feedback Storage
**Purpose**: Capture user corrections and approvals

**Database Model**: `ParseFeedback`
```python
- id: UUID
- quote_request_id: FK to QuoteRequest
- user_id: Who provided feedback
- feedback_type: ENUM ['approve', 'correct', 'reject']
- original_parse: JSON (what AI extracted)
- corrected_parse: JSON (user corrections)
- feedback_notes: TEXT
- created_at: TIMESTAMP
```

### 2. Knowledge Base
**Purpose**: Accumulate learned patterns and domain knowledge

**Database Model**: `DomainKnowledge`
```python
- id: UUID
- knowledge_type: ENUM ['door_model', 'customer_preference', 'common_pattern', 'specification']
- entity: VARCHAR (e.g., "TX450", "Company ABC")
- pattern_data: JSON (learned patterns)
- confidence: FLOAT (0.0-1.0)
- usage_count: INT (how often used)
- created_at: TIMESTAMP
- updated_at: TIMESTAMP
```

### 3. Example Library
**Purpose**: Store high-quality parse examples for retrieval

**Database Model**: `ParseExample`
```python
- id: UUID
- quote_request_id: FK to QuoteRequest
- email_text: TEXT (subject + body)
- parsed_result: JSON
- is_verified: BOOL (user approved)
- quality_score: FLOAT (how good an example)
- tags: ARRAY (e.g., ['TX450', 'multi-door', 'complete-specs'])
- created_at: TIMESTAMP
```

### 4. Retrieval-Augmented Generation (RAG)

**How it works:**
1. New email arrives
2. Find 3-5 most similar past examples from `ParseExample`
3. Inject examples into Claude prompt
4. AI uses examples as reference patterns
5. Store new successful parse as example

**Similarity Matching (Simple Version)**:
- Keyword matching (door models, customer names)
- Email length similarity
- Structural similarity (has pricing, has dimensions, etc.)

**Future Enhancement**:
- Semantic embeddings (vector similarity)
- Use Claude to generate embeddings or OpenAI's embedding API

## Data Flow

### Email Processing with Memory
```
1. Email arrives
   ↓
2. Retrieve similar examples (RAG)
   ↓
3. Build enhanced prompt with examples
   ↓
4. Claude parses with context
   ↓
5. Store parse + AI decision
   ↓
6. [User reviews] → Feedback stored
   ↓
7. If approved → Add to example library
   ↓
8. Extract patterns → Update knowledge base
```

### Feedback Loop
```
1. User reviews parsed quote
   ↓
2. User approves/corrects/rejects
   ↓
3. Store feedback in ParseFeedback
   ↓
4. If corrected:
   - Update QuoteRequest with corrected data
   - Mark original parse as corrected
   - Create new ParseExample with corrected version
   ↓
5. Analyze corrections to identify:
   - Common errors (update knowledge base)
   - Missing patterns (improve prompts)
   - Model-specific issues (TX450 always needs X)
```

## API Endpoints

### Feedback Endpoints
```
POST   /api/quotes/{id}/feedback
GET    /api/quotes/pending-review
PATCH  /api/quotes/{id}/correct
GET    /api/feedback/stats
```

### Knowledge Endpoints
```
GET    /api/knowledge/door-models
GET    /api/knowledge/customer-patterns
GET    /api/knowledge/common-specs
POST   /api/knowledge/manual-entry  (admin adds knowledge)
```

### Example Management
```
GET    /api/examples/best           (top quality examples)
POST   /api/examples/{id}/promote   (mark as high quality)
DELETE /api/examples/{id}/demote    (remove from library)
```

## Learning Mechanisms

### 1. Immediate Learning (Real-time)
- User corrects parse → Example library updated instantly
- Next similar email uses corrected version as reference

### 2. Pattern Extraction (Batch)
- Nightly job analyzes all feedback from past 24 hours
- Identifies common corrections
- Updates domain knowledge base
- Improves prompt templates

### 3. Quality Scoring
Every parse example gets scored on:
- User approval (verified = +1.0)
- AI confidence score (0.0-1.0)
- Completeness (all fields filled = +0.5)
- Consistency (matches other examples = +0.3)
- **Final score**: weighted average → stored in `quality_score`

### 4. Knowledge Types

**Door Model Knowledge**:
```json
{
  "model": "TX450",
  "common_widths": [8, 9, 10, 12, 16],
  "common_heights": [7, 8, 9, 10],
  "default_panel_config": "18\"",
  "default_track": "2\"",
  "common_colors": ["White", "Almond", "Brown"],
  "requires_glazing": false
}
```

**Customer Pattern Knowledge**:
```json
{
  "customer": "ABC Construction",
  "typical_order_size": 5,
  "preferred_models": ["TX450", "AL976"],
  "always_requests": ["3\" track", "brown color"],
  "contact_person": "John Smith",
  "email_pattern": "subject always includes project name"
}
```

## Prompt Engineering with Memory

### Before (Static Prompt)
```
"Extract quote request information from this email..."
```

### After (Dynamic Prompt with Memory)
```
"Extract quote request information from this email.

Here are 3 similar examples of successfully parsed emails:

Example 1:
Email: [similar email text]
Extracted: [verified parse result]

Example 2:
Email: [similar email text]
Extracted: [verified parse result]

Example 3:
Email: [similar email text]
Extracted: [verified parse result]

Known patterns for this type of request:
- TX450 doors typically use 18" panel configuration
- This customer (ABC Construction) usually requests brown color
- When email mentions 'standard', it means 2" track

Now extract from the new email below..."
```

## Implementation Phases

### Phase 1: Foundation (Week 2)
✅ Database models for feedback, knowledge, examples
✅ Basic retrieval (keyword matching)
✅ Feedback API endpoints
✅ Enhanced prompts with examples

### Phase 2: Intelligence (Week 3+)
- Pattern extraction job
- Quality scoring algorithm
- Knowledge base auto-population
- Analytics dashboard showing learning progress

### Phase 3: Advanced (Week 4+)
- Semantic embeddings (vector search)
- A/B testing different prompts
- Confidence calibration
- Automated retraining triggers

## Success Metrics

Track these to measure learning effectiveness:

1. **Parse Accuracy Over Time**
   - % of parses approved without corrections
   - Target: 50% → 80% → 95% over 3 months

2. **Average Confidence Score**
   - Mean confidence of AI parses
   - Target: 0.65 → 0.75 → 0.85

3. **Feedback Response Time**
   - Time from parse to user feedback
   - Target: < 1 hour (automated workflow)

4. **Knowledge Base Growth**
   - Number of patterns learned
   - Target: 50 patterns in first month

5. **Example Library Quality**
   - % of examples marked as verified
   - Target: > 80% verified examples

## Technical Considerations

### Performance
- Cache retrieved examples (Redis)
- Index ParseExample.tags for fast lookup
- Limit retrieval to top 5 examples max

### Privacy
- Anonymize customer data in examples (optional)
- Retention policy: delete old examples after 2 years
- User consent for storing corrections

### Scalability
- As example library grows (>10,000), need vector search
- Partition by date/model type
- Archive old examples to cold storage

## Next Steps

1. Create Alembic migration for new tables
2. Implement models in `app/db/models.py`
3. Build retrieval service in `app/services/memory_service.py`
4. Update `ai/client.py` to use memory
5. Create feedback API in `app/api/feedback.py`
6. Build admin dashboard to view learning progress
