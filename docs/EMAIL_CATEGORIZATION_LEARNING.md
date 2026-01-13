# Email Categorization Learning System

## Problem
Only 20-30% of incoming emails are actual quote requests. The AI needs to learn to distinguish between:
- **Quote requests** (20-30%) - Explicitly asking for pricing/quotes
- **General emails** (70-80%) - Invoices, order confirmations, inquiries, shipping updates, etc.

## Solution Built

### 1. Database Schema Enhancement ✅
Added fields to `email_logs` table to track AI learning:
- `ai_category` - What the AI categorized it as
- `ai_category_confidence` - Confidence score (0.0-1.0)
- `ai_category_reasoning` - Why the AI chose this category
- `user_verified_category` - What the user says it actually is (ground truth)
- `categorization_correct` - Boolean if AI was correct

**Migration created**: `6fa0461410ad_add_email_categorization_learning_fields.py` ✅ **Applied**

### 2. Email Categorization Service ✅
Created `app/services/email_categorization_service.py` with:

**Key Features:**
- `categorize_email()` - Categorizes with learning from past examples
- `_get_learning_examples()` - Retrieves verified past categorizations (balanced: 50% quote requests, 50% non-quotes)
- `record_user_verification()` - Stores user feedback for learning
- `get_categorization_stats()` - Returns accuracy metrics

**Learning Mechanism:**
1. Retrieves up to 10 past categorizations that users verified
2. Balances examples (50% quote requests, 50% non-quotes)
3. Includes these in AI prompt as "LEARNING EXAMPLES"
4. AI learns patterns from correct/incorrect past categorizations

### 3. Enhanced AI Client Method ✅
Added `analyze_email_category_with_context()` to `app/integrations/ai/client.py`:

**Key Improvements:**
- Includes strict guidelines: "Only 20-30% are quote requests"
- Shows learning examples in prompt
- Emphasizes: "Must EXPLICITLY ask for pricing = quote_request"
- Conservative bias: "When unsure, choose 'general' or 'inquiry'"

### 4. Categories Defined
- `quote_request` - **STRICT**: Must explicitly request pricing/quote
- `order_confirmation` - Confirming existing orders
- `invoice` - Invoices, payments, receipts
- `inquiry` - General questions (NOT asking for quote)
- `shipping` - Delivery, tracking, shipping updates
- `general` - General business correspondence
- `other` - Miscellaneous

## Integration Steps (TODO)

### Step 1: Update Email Monitor
File: `app/services/email_monitor.py`

```python
# Add import at top:
from app.services.email_categorization_service import get_categorization_service

# In process_email method, replace categorization section:
# CURRENT CODE (around line 208-211):
category_result = self.ai_client.analyze_email_category(subject, body)
category = category_result.get("category", "unknown") if category_result.get("success") else "unknown"
is_quote_request = category == "quote_request"

# REPLACE WITH:
categorization_service = get_categorization_service(db)
category_result = categorization_service.categorize_email(subject, body, from_address)
category = category_result.get("category", "unknown")
confidence = category_result.get("confidence", 0.0)
reasoning = category_result.get("reasoning", "")
is_quote_request = category == "quote_request"

# Update EmailLog creation (around line 213-222) to include new fields:
email_log = EmailLog(
    message_id=internet_message_id,
    received_at=datetime.fromisoformat(received_at.replace('Z', '+00:00')) if received_at else datetime.utcnow(),
    from_address=from_address,
    subject=subject,
    body=body,
    attachments=None,
    status="pending" if is_quote_request else "informational",
    # NEW FIELDS FOR LEARNING:
    ai_category=category,
    ai_category_confidence=confidence,
    ai_category_reasoning=reasoning
)
```

### Step 2: Create User Feedback API
File: `app/api/email_feedback.py` (NEW FILE)

```python
"""
API endpoints for users to provide feedback on email categorizations
This feedback trains the AI to improve over time
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.db.database import SessionLocal
from app.services.email_categorization_service import get_categorization_service

router = APIRouter(prefix="/api/email-feedback", tags=["email-feedback"])

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

class EmailFeedbackRequest(BaseModel):
    email_id: int
    correct_category: str  # What it should be
    comment: str = None

@router.post("/categorization/{email_id}")
def provide_categorization_feedback(
    email_id: int,
    feedback: EmailFeedbackRequest,
    db: Session = Depends(get_db)
):
    """
    User provides feedback on email categorization
    This trains the AI to improve accuracy
    """
    categorization_service = get_categorization_service(db)

    # Get the email to check what AI said
    from app.db.models import EmailLog
    email = db.query(EmailLog).filter(EmailLog.id == email_id).first()
    if not email:
        raise HTTPException(status_code=404, detail="Email not found")

    # Record if AI was correct
    was_correct = (email.ai_category == feedback.correct_category)

    categorization_service.record_user_verification(
        email_id=email_id,
        user_verified_category=feedback.correct_category,
        was_ai_correct=was_correct
    )

    return {
        "message": "Feedback recorded - AI will learn from this",
        "ai_was_correct": was_correct,
        "learning_examples_count": categorization_service._get_learning_examples().__len__()
    }

@router.get("/stats")
def get_categorization_stats(db: Session = Depends(get_db)):
    """Get AI categorization accuracy statistics"""
    categorization_service = get_categorization_service(db)
    return categorization_service.get_categorization_stats()
```

### Step 3: Add to main.py
```python
# In app/main.py, add:
from app.api import feedback, auth, email_connections, email_feedback

app.include_router(email_feedback.router)
```

### Step 4: Frontend - Add Feedback UI
Create a component in Review Queue to let users mark emails as "Not a quote request":

```jsx
// In ReviewQueue.jsx or QuoteDetail.jsx
<button onClick={() => markAsNotQuote(email.id)}>
  ❌ Not a Quote Request
</button>

const markAsNotQuote = async (emailId) => {
  await axios.post(`${API_URL}/api/email-feedback/categorization/${emailId}`, {
    correct_category: "inquiry", // or show dropdown
    comment: "This was just a question, not requesting a quote"
  })
  // Refresh list
}
```

## How It Learns

### Initial State (No Learning Data)
- AI uses basic categorization prompt
- May be overly aggressive (false positives)
- Accuracy unknown

### After 10-20 User Corrections
- AI has 10-20 verified examples
- Learns patterns: what IS and ISN'T a quote request
- Starts seeing context clues (e.g., "just wondering" vs "need a quote")

### After 50+ User Corrections
- Strong learning dataset
- AI understands company-specific patterns
- Accuracy improves to 85-90%+
- False positive rate drops significantly

## Metrics to Track

Dashboard should show:
1. **Total Emails Processed**: Count
2. **Categorization Accuracy**: % correct (of verified emails)
3. **False Positive Rate**: Emails marked as quote_request but weren't
4. **False Negative Rate**: Missed quote requests
5. **Learning Examples Available**: Number of verified categorizations

## Example Learning Cycle

1. **Email arrives**: "Hi, do you have doors in stock?"
2. **AI categorizes**: "quote_request" (confidence: 0.6)
3. **User reviews**: Marks as "inquiry" (not asking for price)
4. **System records**: AI was wrong, adds to learning examples
5. **Next similar email**: AI sees past example, categorizes as "inquiry" (confidence: 0.8)
6. **Improvement**: AI learned product questions ≠ quote requests

## Files Created

1. ✅ `alembic/versions/6fa0461410ad_add_email_categorization_learning_fields.py`
2. ✅ `app/services/email_categorization_service.py`
3. ✅ `app/integrations/ai/client.py` (added method)
4. ✅ `docs/EMAIL_CATEGORIZATION_LEARNING.md` (this file)

## Files to Update

1. ⏳ `app/services/email_monitor.py` - Use new categorization service
2. ⏳ `app/api/email_feedback.py` - Create new feedback API
3. ⏳ `app/main.py` - Add email_feedback router
4. ⏳ `frontend/src/components/ReviewQueue.jsx` - Add feedback buttons
5. ⏳ `frontend/src/components/Dashboard.jsx` - Show categorization stats

## Testing Plan

1. **Baseline**: Check current false positive rate
2. **Provide feedback**: Mark 20 emails (10 quote requests, 10 non-quotes)
3. **Test new email**: Send test emails, verify improved accuracy
4. **Monitor metrics**: Track accuracy over 1 week, 1 month
5. **Goal**: Achieve 85%+ accuracy, <10% false positive rate

## Future Enhancements

1. **Confidence Threshold**: Only create quote_request if confidence > 0.7
2. **Active Learning**: AI asks user to verify low-confidence categorizations
3. **Sender Patterns**: Learn that certain senders never send quotes
4. **Subject Line Patterns**: Learn keywords that indicate quote requests
5. **Multi-Model Ensemble**: Use multiple AI models, vote on category
