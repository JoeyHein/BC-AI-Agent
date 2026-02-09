"""
Anthropic Claude AI Client for BC AI Agent
Used for email parsing and quote data extraction
"""

import logging
from typing import Optional, Dict, List, Any
import json
from anthropic import Anthropic

from app.config import settings

logger = logging.getLogger(__name__)


class ClaudeAIClient:
    """Claude AI client for email parsing and data extraction"""

    def __init__(self):
        self.api_key = settings.ANTHROPIC_API_KEY
        self.client: Optional[Anthropic] = None

        if self.api_key:
            self.client = Anthropic(api_key=self.api_key)
            logger.info("Claude AI client initialized")
        else:
            logger.warning("Anthropic API key not configured. AI features will not work.")

    def parse_email_for_quote(self, email_subject: str, email_body: str,
                              sender_info: Dict[str, str],
                              example_context: Optional[str] = None) -> Dict[str, Any]:
        """Parse email to extract quote request information

        Args:
            email_subject: Email subject line
            email_body: Email body content (HTML or plain text)
            sender_info: Dict with 'name' and 'email'
            example_context: Optional RAG examples to inject into prompt

        Returns:
            Dict with extracted data and confidence scores
        """
        if not self.client:
            return {
                "success": False,
                "error": "AI client not initialized",
                "confidence": 0.0
            }

        prompt = f"""You are an AI assistant helping a garage door manufacturer (Open Distribution Company) process quote requests from emails.

Analyze the following email and extract structured quote request information.

{example_context if example_context else ""}

**Email From:** {sender_info.get('name')} <{sender_info.get('email')}>
**Subject:** {email_subject}
**Body:**
{email_body}

---

**Extract the following information:**

1. **Customer Information:**
   - Company name
   - Contact person name
   - Phone number
   - Email address

2. **Door Specifications (for EACH door requested):**
   - Door model (TX450, AL976, AL976-SWD, Solalite, Kanata, Craft, etc.)
   - Quantity (number of doors)
   - Width (feet and inches)
   - Height (feet and inches)
   - Color/finish
   - Glazing type (if applicable: thermopane, single glass, polycarbonate, etc.)
   - Panel configuration (18", 21", 24" sections)
   - Track type (2" or 3")
   - Any special features or notes

3. **Project Information:**
   - Project name/location
   - Delivery date or deadline
   - Installation required? (yes/no)
   - Any special requirements

4. **Confidence Assessment:**
   - Overall confidence (0.0 to 1.0) - how confident are you that you extracted all critical information correctly?
   - Per-field confidence - rate each major field
   - Missing information - what critical fields are missing?

**Output Format:** JSON only, no additional text. Use this structure:

```json
{{
  "customer": {{
    "company_name": "Company Name or null",
    "contact_name": "Contact Person or null",
    "phone": "Phone Number or null",
    "email": "Email or null",
    "confidence": 0.0-1.0
  }},
  "doors": [
    {{
      "model": "Door Model or null",
      "quantity": number or null,
      "width_ft": number or null,
      "width_in": number or null,
      "height_ft": number or null,
      "height_in": number or null,
      "color": "Color or null",
      "glazing": "Glazing type or null",
      "panel_config": "Panel configuration or null",
      "track_type": "2 or 3 or null",
      "special_features": "Any notes or null",
      "confidence": 0.0-1.0
    }}
  ],
  "project": {{
    "name": "Project name or null",
    "delivery_date": "Date or null",
    "installation_required": true/false/null,
    "special_requirements": "Notes or null",
    "confidence": 0.0-1.0
  }},
  "overall_confidence": 0.0-1.0,
  "missing_critical_fields": ["list of missing fields"],
  "parsing_notes": "Any important observations or ambiguities"
}}
```

**Important:**
- Use null for fields you cannot find
- Be conservative with confidence scores
- If door specifications are incomplete, mark confidence low
- If dimensions are unclear, note it in parsing_notes
"""

        try:
            response = self.client.messages.create(
                model="claude-sonnet-4-5-20250929",
                max_tokens=4000,
                messages=[{
                    "role": "user",
                    "content": prompt
                }]
            )

            # Extract text content
            content = response.content[0].text

            # Try to parse JSON from response
            # Sometimes Claude wraps JSON in markdown code blocks
            if "```json" in content:
                json_start = content.find("```json") + 7
                json_end = content.find("```", json_start)
                content = content[json_start:json_end].strip()
            elif "```" in content:
                json_start = content.find("```") + 3
                json_end = content.find("```", json_start)
                content = content[json_start:json_end].strip()

            parsed_data = json.loads(content)

            # Add token usage info
            result = {
                "success": True,
                "data": parsed_data,
                "confidence": parsed_data.get("overall_confidence", 0.5),
                "model": "claude-sonnet-4-5-20250929",
                "tokens": {
                    "input": response.usage.input_tokens,
                    "output": response.usage.output_tokens
                }
            }

            logger.info(f"Email parsed successfully. Confidence: {result['confidence']:.2f}")
            return result

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse AI response as JSON: {e}")
            logger.error(f"AI Response: {content if 'content' in locals() else 'N/A'}")
            return {
                "success": False,
                "error": f"JSON parsing error: {str(e)}",
                "confidence": 0.0,
                "raw_response": content if 'content' in locals() else None
            }
        except Exception as e:
            logger.error(f"AI parsing failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "confidence": 0.0
            }

    def analyze_email_category(self, email_subject: str, email_body: str) -> Dict[str, Any]:
        """Determine if email is a quote request or something else

        Returns:
            Dict with category and confidence
        """
        if not self.client:
            return {
                "success": False,
                "error": "AI client not initialized"
            }

        prompt = f"""Analyze this email and categorize it.

**Subject:** {email_subject}
**Body:** {email_body[:1000]}  # First 1000 chars

**Categories:**
- "quote_request" - Email is requesting a NEW quote for doors/products
- "quote_modification" - Email is MODIFYING/CHANGING an existing quote (mentions quote number, says "revise", "change", "update the quote", etc.)
- "order_confirmation" - Confirming an order
- "inquiry" - General question or inquiry
- "invoice" - Invoice or payment related
- "complaint" - Issue or complaint
- "other" - Doesn't fit above categories

**IMPORTANT for quote_modification detection:**
- Look for references to existing quote numbers (e.g., "Q-12345", "quote #123")
- Look for phrases like "revise the quote", "change the dimensions", "update the door size", "modify the order"
- Look for email reply chains that reference previous quotes
- If they're asking for changes to specs on a quote they already requested, it's a modification NOT a new quote

**Output JSON only:**
```json
{{
  "category": "category_name",
  "confidence": 0.0-1.0,
  "reasoning": "Brief explanation"
}}
```
"""

        try:
            response = self.client.messages.create(
                model="claude-sonnet-4-5-20250929",
                max_tokens=500,
                messages=[{"role": "user", "content": prompt}]
            )

            content = response.content[0].text

            # Extract JSON
            if "```json" in content:
                json_start = content.find("```json") + 7
                json_end = content.find("```", json_start)
                content = content[json_start:json_end].strip()
            elif "```" in content:
                json_start = content.find("```") + 3
                json_end = content.find("```", json_start)
                content = content[json_start:json_end].strip()

            result = json.loads(content)
            result["success"] = True

            return result

        except Exception as e:
            logger.error(f"Email categorization failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "category": "unknown",
                "confidence": 0.0
            }



    def analyze_email_category_with_context(self, email_subject: str, email_body: str, 
                                            learning_examples: List[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Determine if email is a quote request, using learning examples for context
        
        Args:
            email_subject: Email subject line
            email_body: Email body text
            learning_examples: Past verified categorizations for learning
            
        Returns:
            Dict with category, confidence, and reasoning
        """
        if not self.client:
            return {
                "success": False,
                "error": "AI client not initialized"
            }

        # Build examples section
        examples_text = ""
        if learning_examples:
            examples_text = "\n\n**Examples from past categorizations:**\n"
            for i, ex in enumerate(learning_examples[:5], 1):
                examples_text += f"\nExample {i}:\n- Subject: {ex.get('subject', 'N/A')}\n- Category: {ex.get('category', 'N/A')}\n- Was correct: {ex.get('was_correct', 'N/A')}\n"

        prompt = f"""Analyze this email and categorize it.
{examples_text}

**Email to categorize:**
**Subject:** {email_subject}
**Body:** {email_body[:2000]}

**Categories:**
- "quote_request" - Email is requesting a NEW quote for doors/overhead doors/garage doors with specifications
- "quote_modification" - Email is CHANGING/REVISING an existing quote (mentions existing quote number, asks to change specs, update dimensions, etc.)
- "order_confirmation" - Confirming an existing order
- "inquiry" - General question, sample request, or information request (NOT a quote request)
- "invoice" - Invoice or payment related
- "internal" - Internal company communication
- "other" - Doesn't fit above categories

**IMPORTANT for quote_modification detection:**
- Look for references to existing quote numbers (e.g., "Q-12345", "quote #123", "AI-QR-xxx")
- Look for phrases like: "revise the quote", "change the door", "update the dimensions", "modify", "correction"
- Email replies that reference a previous quote request are likely modifications
- If changing specs on an already-requested quote = modification, NOT new quote

**Important:** A quote request must include intent to get pricing for NEW doors.
Sample requests, color chart requests, and general inquiries are NOT quote requests.

**Output JSON only:**
```json
{{
  "category": "category_name",
  "confidence": 0.0-1.0,
  "reasoning": "Brief explanation",
  "is_quote_request": true/false,
  "is_modification": true/false,
  "referenced_quote_number": "quote number if mentioned, or null",
  "modification_type": "dimension_change|color_change|quantity_change|spec_change|cancellation|null"
}}
```
"""

        try:
            response = self.client.messages.create(
                model="claude-sonnet-4-5-20250929",
                max_tokens=500,
                messages=[{"role": "user", "content": prompt}]
            )

            content = response.content[0].text

            # Extract JSON
            if "```json" in content:
                json_start = content.find("```json") + 7
                json_end = content.find("```", json_start)
                content = content[json_start:json_end].strip()
            elif "```" in content:
                json_start = content.find("```") + 3
                json_end = content.find("```", json_start)
                content = content[json_start:json_end].strip()

            result = json.loads(content)
            result["success"] = True

            return result

        except Exception as e:
            logger.error(f"Email categorization with context failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "category": "unknown",
                "confidence": 0.0,
                "is_quote_request": False
            }


# Global AI client instance
ai_client = ClaudeAIClient()

