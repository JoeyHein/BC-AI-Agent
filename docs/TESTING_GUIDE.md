# BC AI Agent - Testing Guide

## 🎯 What We're Testing

1. **Email Monitoring** - AI parses quote request emails
2. **Memory System** - AI learns from past examples
3. **Feedback API** - Review, approve, correct, or reject parses

---

## 📧 Part 1: Test Email Parsing (Cold Start)

### Step 1: Send a Quote Request Email

Send an email to **joey@opendc.ca** or **briand@opendc.ca** with this content:

**Subject:** Quote Request - Warehouse Doors

**Body:**
```
Hi Brian,

We need a quote for our new warehouse project in Calgary.

Requirements:
- 2 doors, model TX450
- Size: 10' x 10' each
- Color: Brown
- Standard 18" panels
- 2" track
- Thermopane glazing

Project deadline: January 15th
Please send quote ASAP.

Thanks,
John Smith
ABC Construction
john@abcconstruction.com
(403) 555-1234
```

### Step 2: Run Email Monitoring

```bash
cd C:\Users\jhein\bc-ai-agent\backend
python scripts/test_email_monitoring.py
```

**Expected Output:**
- ✅ Email categorized as "quote_request"
- ✅ Quote parsed with AI
- ✅ Confidence score (likely 0.6-0.8 for first parse)
- ✅ Using **0 examples** (cold start)
- ✅ Quote saved to database

### Step 3: Check the Parse

Open browser to: **http://localhost:8000/docs**

Or use curl/Postman:
```bash
curl http://localhost:8000/api/quotes/pending-review
```

You should see the parsed quote with extracted data!

---

## ✅ Part 2: Approve the Parse (Add to Memory)

### Option A: Via API (Recommended)

```bash
# Get the quote ID from previous step (e.g., ID=1)

# Approve the parse
curl -X POST http://localhost:8000/api/quotes/1/approve \
  -H "Content-Type: application/json" \
  -d '{"notes": "Looks good!"}'
```

### Option B: Via Swagger UI

1. Go to http://localhost:8000/docs
2. Find `/api/quotes/{quote_id}/approve`
3. Click "Try it out"
4. Enter quote ID (probably 1)
5. Click "Execute"

**What Happens:**
- ✅ Quote status → "approved"
- ✅ Parse added to example library
- ✅ Quality score boosted to ~0.8
- ✅ Marked as verified
- ✅ **Now available for future parses!**

---

## 🧠 Part 3: Test Learning (Second Parse with Memory)

### Step 1: Send Similar Email

Send another quote email (slightly different):

**Subject:** Quote Request - Similar Doors

**Body:**
```
Hi Joey,

Please quote for similar overhead doors:

- 3 doors, TX450 model
- 12' x 10' each
- Brown color
- 18" panels
- 2" track standard
- Thermopane glass

Company: XYZ Builders
Contact: Jane Doe
Phone: (403) 555-5678
Email: jane@xyzbuilders.com

Thanks!
```

### Step 2: Run Monitoring Again

```bash
python scripts/test_email_monitoring.py
```

**Expected Output (THE MAGIC!):**
- ✅ Email categorized as "quote_request"
- ✅ **Using 1 example** (your approved parse from Email #1!)
- ✅ AI sees the pattern from first email
- ✅ Higher confidence score (0.75-0.9)
- ✅ More accurate extraction
- ✅ Follows same format as first parse

### Step 3: Compare Results

```bash
# Get all quote requests
curl http://localhost:8000/api/quotes/pending-review
```

Compare parse #1 vs parse #2:
- Parse #2 should have higher confidence
- Parse #2 should match field patterns from parse #1
- Parse #2 benefited from AI "memory"

---

## 🔧 Part 4: Test Corrections

### Scenario: AI Makes a Mistake

Let's say the AI incorrectly parsed the door model as "AL976" instead of "TX450".

```bash
# Correct the parse
curl -X POST http://localhost:8000/api/quotes/2/correct \
  -H "Content-Type: application/json" \
  -d '{
    "corrected_data": {
      "customer": {
        "company_name": "XYZ Builders",
        "contact_name": "Jane Doe",
        "phone": "(403) 555-5678",
        "email": "jane@xyzbuilders.com"
      },
      "doors": [
        {
          "model": "TX450",
          "quantity": 3,
          "width_ft": 12,
          "height_ft": 10,
          "color": "Brown",
          "panel_config": "18\"",
          "track_type": "2\"",
          "glazing": "Thermopane"
        }
      ]
    },
    "notes": "Corrected model from AL976 to TX450"
  }'
```

**What Happens:**
- ✅ Quote updated with correct data
- ✅ Correction added to example library (quality boost +30%)
- ✅ AI learns: "When email says TX450, it means TX450"
- ✅ Future similar emails will be more accurate

---

## 📊 Part 5: View Learning Progress

### Check Statistics

```bash
curl http://localhost:8000/api/quotes/stats/learning-progress
```

**Expected Response:**
```json
{
  "total_examples": 2,
  "verified_examples": 2,
  "total_knowledge_items": 0,
  "pending_reviews": 0,
  "latest_metrics": null
}
```

### Database Inspection

```bash
cd backend
python scripts/check_database.py
```

Or use SQL directly:
```sql
-- View example library
SELECT id, quality_score, is_verified, customer_name, times_retrieved
FROM parse_examples
ORDER BY quality_score DESC;

-- View feedback history
SELECT pf.id, pf.feedback_type, pf.created_at, qr.customer_name
FROM parse_feedback pf
JOIN quote_requests qr ON pf.quote_request_id = qr.id
ORDER BY pf.created_at DESC;
```

---

## 🧪 Advanced Testing Scenarios

### Test 1: High Volume Learning

Send 5-10 quote emails over a few days:
- Mix of different door models (TX450, AL976, BCXL)
- Different customers
- Various configurations

**Expected:** Approval rate should increase from ~60% to ~85%+

### Test 2: Customer Pattern Learning

Send 3 emails from the same customer:
- AI should start recognizing customer preferences
- Confidence should increase for that customer
- Common patterns should be identified

### Test 3: Door Model Patterns

Send multiple TX450 quotes:
- AI should learn common TX450 configurations
- Default values should emerge (18" panels, 2" track)
- Confidence for TX450 quotes should be high

---

## 🐛 Troubleshooting

### Email Not Parsing
**Problem:** Email categorized as "other" or "inquiry"
**Solution:** Check email contains door models, quantities, dimensions

### Low Confidence Scores
**Problem:** Parse confidence < 0.5
**Solution:** Approve it anyway - AI will learn and improve

### No Examples Retrieved
**Problem:** "Using 0 examples" even after approving
**Solution:**
- Check `parse_examples` table has records
- Ensure `is_verified = True`
- Check door models match between emails

### API Returns 404
**Problem:** Endpoint not found
**Solution:** Ensure FastAPI server running on port 8000

---

## ✅ Success Criteria

After testing, you should observe:

**Day 1 (Cold Start):**
- [ ] First email parsed with 0 examples
- [ ] Confidence ~0.6-0.7
- [ ] Parse approved → Added to library

**Day 1 (After Approval):**
- [ ] Second email uses first as example
- [ ] Confidence ~0.75-0.85
- [ ] More consistent field extraction

**Week 1:**
- [ ] 10+ examples in library
- [ ] Approval rate ~70%
- [ ] Average confidence ~0.75

**Month 1 (Expected):**
- [ ] 50+ verified examples
- [ ] Approval rate ~85%
- [ ] Average confidence ~0.85+
- [ ] Rare corrections needed

---

## 📝 API Endpoints Quick Reference

**Base URL:** `http://localhost:8000`

### Quote Review
```
GET    /api/quotes/pending-review          # List quotes needing review
GET    /api/quotes/{id}                     # Get specific quote
```

### Feedback
```
POST   /api/quotes/{id}/approve             # Quick approve
POST   /api/quotes/{id}/correct             # Provide corrections
POST   /api/quotes/{id}/reject              # Reject parse
POST   /api/quotes/{id}/feedback            # Full feedback (all types)
```

### Analytics
```
GET    /api/quotes/stats/learning-progress  # View learning metrics
```

### Documentation
```
GET    /docs                                # Swagger UI (interactive)
GET    /redoc                               # ReDoc (documentation)
```

---

## 🎓 Learning Validation Tests

### Test: Does RAG Work?

1. Approve parse #1
2. Check database: `SELECT * FROM parse_examples WHERE id = 1`
3. Send similar email #2
4. Check logs: Should say "Using 1 example"
5. ✅ **PASS** if example retrieved

### Test: Does Quality Improve?

1. Compare confidence scores over time
2. Track approval rate daily
3. ✅ **PASS** if trends upward

### Test: Do Corrections Work?

1. Correct a parse
2. Send similar email
3. Check if AI avoids same mistake
4. ✅ **PASS** if correction applied

---

## 🚀 Next Steps After Testing

Once testing is complete and memory system works:

1. **Build Admin Dashboard** - Visualize learning progress
2. **Add Domain Knowledge** - Manually seed door model patterns
3. **Implement Scheduled Monitoring** - Auto-run every 15 minutes
4. **Add Email Notifications** - Alert on new quote requests
5. **Integrate with BC** - Auto-create quotes in Business Central

---

## 📞 Need Help?

If something isn't working:
1. Check FastAPI server logs: `bd54b41.output`
2. Check email monitoring logs
3. Inspect database: `python scripts/check_database.py`
4. Review this guide's troubleshooting section

**Your AI is learning - give it a few examples and watch it improve!** 🧠✨
