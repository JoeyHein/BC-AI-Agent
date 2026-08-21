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
   - Project tag/reference - the customer's identifier for this project, often found in the email subject line (e.g., "Smith Warehouse", "Project 2025-44", "Lot 12 Calgary"). This is how the customer refers to the quote. If no clear tag exists, use null.
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
    "tag": "Customer's project tag/reference from subject or body, or null",
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

    def extract_invoice_from_pdf(self, pdf_bytes: bytes, filename: str) -> Dict[str, Any]:
        """Extract structured data from a vendor invoice PDF (base64 document
        content block — Claude reads PDFs natively, no separate OCR step).

        Args:
            pdf_bytes: Raw PDF file content
            filename: Original filename, for logging/context only

        Returns:
            Dict with extracted data and confidence scores, same shape as
            parse_email_for_quote (success/data/confidence/model/tokens).
        """
        if not self.client:
            return {
                "success": False,
                "error": "AI client not initialized",
                "confidence": 0.0
            }

        import base64
        pdf_b64 = base64.standard_b64encode(pdf_bytes).decode("utf-8")

        prompt = """You are an AI assistant helping a garage door manufacturer (Open Distribution Company) process incoming vendor invoices.

Read the attached PDF and extract structured invoice data.

**Extract:**

1. **Vendor Information:**
   - Vendor/supplier name (as printed on the invoice)
   - Vendor address (if present)

2. **Invoice Header:**
   - Invoice number (the VENDOR's own invoice number, not any internal reference)
   - Invoice date
   - Due date
   - Purchase order number referenced on the invoice, if any (customers/vendors often print "PO#" or "Order #" — extract exactly as printed)
   - Currency (CAD/USD/etc.)

3. **Line Items** (each line on the invoice):
   - Description (as printed)
   - Vendor's own part/item number, if printed
   - Quantity
   - Unit price
   - Line total

4. **Totals:**
   - Subtotal (before tax)
   - Tax amount
   - Total amount due

5. **Confidence Assessment:**
   - Overall confidence (0.0 to 1.0)
   - Per-field confidence for vendor name, invoice number, and total (these three matter most for matching)
   - Anything ambiguous, handwritten, or hard to read (common on scanned paper invoices) — note it explicitly

**Output Format:** JSON only, no additional text. Use this structure:

```json
{
  "vendor": {
    "name": "Vendor Name or null",
    "address": "Address or null",
    "confidence": 0.0-1.0
  },
  "invoice_number": "Vendor's invoice number or null",
  "invoice_number_confidence": 0.0-1.0,
  "invoice_date": "YYYY-MM-DD or null",
  "due_date": "YYYY-MM-DD or null",
  "po_number_referenced": "PO number printed on the invoice, or null",
  "currency": "CAD or USD or null",
  "line_items": [
    {
      "description": "Line description",
      "vendor_item_number": "Vendor's part number or null",
      "quantity": number or null,
      "unit_price": number or null,
      "line_total": number or null
    }
  ],
  "subtotal": number or null,
  "tax_amount": number or null,
  "total_amount": number or null,
  "total_confidence": 0.0-1.0,
  "overall_confidence": 0.0-1.0,
  "parsing_notes": "Any important observations, ambiguities, or scan-quality issues"
}
```

**Important:**
- Use null for fields you cannot find — never guess a number you cannot read clearly
- Be conservative with confidence scores, especially on scanned/handwritten paper invoices
- Extract numbers exactly as printed (don't round or reformat beyond standard decimal notation)
"""

        try:
            response = self.client.messages.create(
                model="claude-opus-5",
                max_tokens=4000,
                # Straightforward single-shot extraction — no need for the
                # deeper (slower, pricier) reasoning Claude Opus 5 runs by
                # default. Disabling thinking also means response.content[0]
                # is reliably the text block, not a ThinkingBlock.
                thinking={"type": "disabled"},
                messages=[{
                    "role": "user",
                    "content": [
                        {
                            "type": "document",
                            "source": {
                                "type": "base64",
                                "media_type": "application/pdf",
                                "data": pdf_b64,
                            },
                        },
                        {"type": "text", "text": prompt},
                    ],
                }],
            )

            content = next(b.text for b in response.content if b.type == "text")

            if "```json" in content:
                json_start = content.find("```json") + 7
                json_end = content.find("```", json_start)
                content = content[json_start:json_end].strip()
            elif "```" in content:
                json_start = content.find("```") + 3
                json_end = content.find("```", json_start)
                content = content[json_start:json_end].strip()

            parsed_data = json.loads(content)

            result = {
                "success": True,
                "data": parsed_data,
                "confidence": parsed_data.get("overall_confidence", 0.5),
                "model": "claude-opus-5",
                "tokens": {
                    "input": response.usage.input_tokens,
                    "output": response.usage.output_tokens
                }
            }

            logger.info(f"Invoice PDF '{filename}' parsed. Confidence: {result['confidence']:.2f}")
            return result

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse AI response as JSON for '{filename}': {e}")
            return {
                "success": False,
                "error": f"JSON parsing error: {str(e)}",
                "confidence": 0.0,
                "raw_response": content if 'content' in locals() else None
            }
        except Exception as e:
            logger.error(f"Invoice PDF extraction failed for '{filename}': {e}")
            return {
                "success": False,
                "error": str(e),
                "confidence": 0.0
            }

    def map_email_to_configurator(
        self,
        parsed_data: Dict[str, Any],
        email_subject: str,
        email_body: str,
    ) -> Dict[str, Any]:
        """Map AI-parsed email data into the door configurator's schema.

        The configurator (POST /api/door-config/generate-quote) is the
        authoritative quote engine. Its `DoorConfigRequest` needs far more
        fields than a raw RFQ email contains (panelDesign, trackRadius,
        liftType, hardware map, etc.). This step uses Claude to fill those
        gaps intelligently and emit configurator-ready door configs so the
        email flow produces the SAME parts and BC SalesPriceLists pricing as
        the interactive configurator.

        It also classifies the request:
          - "door_quote"    -> full doors that can run through the configurator
          - "parts_request" -> replacement parts (e.g. replacement panels,
                                springs, sections). The portal has no
                                replacement-product costing yet, so these are
                                routed to manual pricing rather than guessed.

        Returns:
            {
              "success": bool,
              "request_kind": "door_quote" | "parts_request" | "unknown",
              "doors": [ {<DoorConfigRequest fields>}, ... ],
              "notes": str,
              "confidence": float,
            }
        """
        if not self.client:
            return {
                "success": False,
                "error": "AI client not initialized",
                "request_kind": "unknown",
                "doors": [],
                "confidence": 0.0,
            }

        doors_json = json.dumps(parsed_data.get("doors", []), indent=2)
        project_json = json.dumps(parsed_data.get("project", {}), indent=2)

        prompt = f"""You convert a parsed garage-door RFQ into the exact JSON \
schema used by Open Distribution Company's door CONFIGURATOR. The configurator \
is the single source of truth for parts and pricing, so your output MUST be a \
valid configurator door config. Fill in any field the email did not specify \
using the rules below.

PARSED EMAIL DOORS:
{doors_json}

PROJECT INFO:
{project_json}

ORIGINAL EMAIL (for context/disambiguation):
Subject: {email_subject}
Body:
{email_body[:4000]}

---

STEP 1 — CLASSIFY the request as one of:
- "door_quote": one or more COMPLETE doors are being requested (has at least a
  size or a clear door model). These can run through the configurator.
- "parts_request": the customer wants REPLACEMENT PARTS only (e.g. "need 2
  replacement panels", "bottom section", "torsion springs", "new struts") —
  NOT a complete new door. We cannot price these yet, so do NOT fabricate door
  configs for them.
- "unknown": cannot tell.

STEP 2 — If "door_quote", map EACH door to this configurator schema. Output
EVERY field, using the defaults shown when the email is silent:

{{
  "doorType": "commercial",        // "residential" | "commercial" | "aluminium". DEFAULT "commercial" unless the email clearly indicates a residential/house door or an aluminium/full-view glass door.
  "doorSeries": "TX450",           // commercial: TX450 (default), TX450-20, TX500, TX500-20. residential: KANATA (default) or CRAFT. aluminium: AL976 (default), SWD, Solalite, Panorama.
  "doorWidth": 0,                   // INTEGER inches (feet*12 + inches). REQUIRED.
  "doorHeight": 0,                  // INTEGER inches. REQUIRED.
  "doorCount": 1,                   // quantity of identical doors
  "panelColor": "WHITE",           // WHITE (default), BLACK, NEW_BROWN, SANDTONE, BRONZE, STEEL_GREY, IRON_ORE, NEW_ALMOND, WALNUT, HAZELWOOD, ENGLISH_CHESTNUT
  "panelDesign": "FLUSH",          // commercial DEFAULT "FLUSH"; residential DEFAULT "SHXL"; others: UDC, BCXL, TRAFALGAR. Use what the email implies.
  "hasWindows": false,
  "windowQty": 0,                   // commercial window/section count if windows requested
  "glazingType": null,              // e.g. "THERMOPANE", "SINGLE", "POLYCARBONATE" if mentioned
  "trackThickness": "2",           // "2" (default) or "3"
  "trackRadius": "15",             // "15" (default, for 2\" track) or "12" (for 3\" track)
  "trackMount": "bracket",
  "liftType": "standard",          // "standard" (default), "low_headroom", "high_lift", "vertical"
  "highLiftInches": null,           // integer if liftType is high_lift
  "hardware": {{"tracks": true, "springs": true, "shafts": true, "struts": true, "hardwareKits": true, "weatherStripping": true, "bottomRetainer": true}},
  "operator": null,                 // operator/opener model if explicitly requested
  "targetCycles": 10000,
  "notes": ""                       // anything the configurator should know (special requests, ambiguities)
}}

RULES:
- doorWidth/doorHeight are INTEGER INCHES. Convert feet+inches: 12'2\" -> 146.
- If a door's size is entirely missing, still emit the door but set its size to
  0 and add a note "size missing"; the caller will route it to manual review.
- Keep doorSeries consistent with doorType (don't put TX450 on a residential door).
- Do NOT invent windows, operators, or high-lift unless the email mentions them.
- Be conservative: if unsure about a value, use the default and mention it in notes.

OUTPUT FORMAT — JSON only, no prose:
{{
  "request_kind": "door_quote" | "parts_request" | "unknown",
  "doors": [ {{...configurator door...}} ],   // [] for parts_request/unknown
  "notes": "short summary of assumptions/defaults you applied",
  "confidence": 0.0-1.0
}}
"""

        try:
            response = self.client.messages.create(
                model="claude-sonnet-4-5-20250929",
                max_tokens=4000,
                messages=[{"role": "user", "content": prompt}],
            )
            content = response.content[0].text

            if "```json" in content:
                json_start = content.find("```json") + 7
                json_end = content.find("```", json_start)
                content = content[json_start:json_end].strip()
            elif "```" in content:
                json_start = content.find("```") + 3
                json_end = content.find("```", json_start)
                content = content[json_start:json_end].strip()

            mapped = json.loads(content)
            doors = self._normalize_configurator_doors(mapped.get("doors", []))

            return {
                "success": True,
                "request_kind": mapped.get("request_kind", "unknown"),
                "doors": doors,
                "notes": mapped.get("notes", ""),
                "confidence": float(mapped.get("confidence", 0.5) or 0.5),
                "tokens": {
                    "input": response.usage.input_tokens,
                    "output": response.usage.output_tokens,
                },
            }

        except json.JSONDecodeError as e:
            logger.error(f"map_email_to_configurator JSON parse error: {e}")
            return {
                "success": False,
                "error": f"JSON parsing error: {str(e)}",
                "request_kind": "unknown",
                "doors": [],
                "confidence": 0.0,
            }
        except Exception as e:
            logger.error(f"map_email_to_configurator failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "request_kind": "unknown",
                "doors": [],
                "confidence": 0.0,
            }

    @staticmethod
    def _normalize_configurator_doors(doors: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Coerce LLM-emitted door configs to valid configurator values.

        Guarantees required fields exist and enum-ish fields hold known values.
        The configurator still does the final authoritative validation
        (validate_panel_combo + BC part-number checks); this just removes the
        easy ways an LLM can drift (e.g. "2 inch" instead of "2", lowercase
        colors, residential series on a commercial door).
        """
        VALID_TYPES = {"residential", "commercial", "aluminium"}
        COLOR_MAP = {
            "WHITE": "WHITE", "BLACK": "BLACK", "BROWN": "NEW_BROWN",
            "NEW_BROWN": "NEW_BROWN", "ALMOND": "NEW_ALMOND",
            "NEW_ALMOND": "NEW_ALMOND", "SANDTONE": "SANDTONE", "SAND": "SANDTONE",
            "TAN": "SANDTONE", "BRONZE": "BRONZE", "GREY": "STEEL_GREY",
            "GRAY": "STEEL_GREY", "STEEL_GREY": "STEEL_GREY",
            "STEEL_GRAY": "STEEL_GREY", "WALNUT": "WALNUT", "IRON_ORE": "IRON_ORE",
            "HAZELWOOD": "HAZELWOOD", "ENGLISH_CHESTNUT": "ENGLISH_CHESTNUT",
            "CHESTNUT": "ENGLISH_CHESTNUT",
        }
        COMMERCIAL_SERIES = {"TX450", "TX450-20", "TX500", "TX500-20"}
        RESIDENTIAL_SERIES = {"KANATA", "CRAFT"}
        ALUMINIUM_SERIES = {"AL976", "SWD", "SOLALITE", "PANORAMA"}

        normalized = []
        for raw in doors:
            d = dict(raw or {})

            door_type = str(d.get("doorType", "commercial")).lower().strip()
            if door_type not in VALID_TYPES:
                door_type = "commercial"

            series = str(d.get("doorSeries", "")).upper().strip().replace(" ", "")
            if door_type == "commercial" and series not in COMMERCIAL_SERIES:
                series = "TX450"
            elif door_type == "residential" and series not in RESIDENTIAL_SERIES:
                series = "KANATA"
            elif door_type == "aluminium" and series not in ALUMINIUM_SERIES:
                series = "AL976"

            def _to_int(v):
                try:
                    return int(round(float(v)))
                except (TypeError, ValueError):
                    return 0

            color_key = str(d.get("panelColor", "WHITE")).upper().replace(" ", "_")
            panel_color = COLOR_MAP.get(color_key, color_key if color_key else "WHITE")

            design = str(d.get("panelDesign", "") or "").upper().strip()
            if not design:
                design = "FLUSH" if door_type == "commercial" else "SHXL"

            track_thickness = str(d.get("trackThickness", "2")).strip()
            track_thickness = "3" if track_thickness.startswith("3") else "2"
            track_radius = str(d.get("trackRadius", "") or "").strip()
            if track_radius not in {"12", "15"}:
                track_radius = "12" if track_thickness == "3" else "15"

            hardware = d.get("hardware")
            if not isinstance(hardware, dict) or not hardware:
                hardware = {
                    "tracks": True, "springs": True, "shafts": True,
                    "struts": True, "hardwareKits": True,
                    "weatherStripping": True, "bottomRetainer": True,
                }

            normalized.append({
                "doorType": door_type,
                "doorSeries": series,
                "doorWidth": _to_int(d.get("doorWidth")),
                "doorHeight": _to_int(d.get("doorHeight")),
                "doorCount": max(1, _to_int(d.get("doorCount")) or 1),
                "panelColor": panel_color,
                "panelDesign": design,
                "hasWindows": bool(d.get("hasWindows", False)),
                "windowQty": _to_int(d.get("windowQty")),
                "glazingType": d.get("glazingType") or None,
                "trackThickness": track_thickness,
                "trackRadius": track_radius,
                "trackMount": str(d.get("trackMount", "bracket") or "bracket"),
                "liftType": str(d.get("liftType", "standard") or "standard"),
                "highLiftInches": _to_int(d.get("highLiftInches")) or None,
                "hardware": hardware,
                "operator": d.get("operator") or None,
                "targetCycles": _to_int(d.get("targetCycles")) or 10000,
                "notes": str(d.get("notes", "") or ""),
            })
        return normalized

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


    def find_closest_bc_item(
        self,
        part_number: str,
        description: str,
        available_items: List[Dict]
    ) -> Optional[Dict]:
        """
        Use Claude to find the closest matching BC inventory item for a part
        that was not found in Business Central.

        Args:
            part_number: The generated part number that doesn't exist in BC
            description: Human-readable description of the part
            available_items: List of BC items (each with 'number', 'displayName')

        Returns:
            The best-matching item dict, or None if no reasonable match found
        """
        if not self.client or not available_items:
            return None

        items_text = "\n".join(
            f"- {item.get('number', '')}: {item.get('displayName', '')}"
            for item in available_items[:60]
        )

        prompt = f"""You are helping match a garage door component to the closest available inventory item in Business Central.

Part not found:
- Part Number: {part_number}
- Description: {description}

Available inventory items in the same category:
{items_text}

Find the single best matching item based on similar specs (dimensions, function, type).
For springs: match wire size, coil size, and wind direction as closely as possible.
For panels: match height, color, and width as closely as possible.
For tracks: match track size (2" vs 3") and lift type.

Respond with ONLY valid JSON — no explanation, no markdown:
{{"number": "ITEM-NUMBER", "displayName": "Item Name"}}

If no item is a reasonable match:
{{"number": null}}"""

        try:
            response = self.client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=100,
                messages=[{"role": "user", "content": prompt}]
            )
            result = json.loads(response.content[0].text.strip())

            if result.get("number"):
                # Return the full item details if available
                for item in available_items:
                    if item.get("number") == result["number"]:
                        return item
                return {"number": result["number"], "displayName": result.get("displayName", "")}

            return None

        except Exception as e:
            logger.error(f"AI item matching failed: {e}")
            return None

    def analyze_quote_diff(
        self,
        diff: Dict[str, Any],
        door_configs: Optional[List[Dict]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Analyze a single quote diff to explain why staff made changes.

        Returns:
            {changes_analysis: [{part_number, change_type, likely_reason, is_configurator_issue, severity, suggested_fix}], summary}
        """
        if not self.client:
            return {"error": "AI client not initialized"}

        ctx = context or {}
        prompt = f"""You are analyzing changes made to a garage door quote generated by an automated configurator.
Staff manually edited the quote in Business Central after the configurator created it.
Your job is to explain each change and identify potential configurator bugs.

**Quote Context:**
- Quote number: {ctx.get('bc_quote_number', 'N/A')}
- Pricing tier: {ctx.get('pricing_tier', 'N/A')}
- Source: {ctx.get('source', 'N/A')}
- Door configurations: {json.dumps(door_configs or [], indent=2)}

**Changes detected:**
- Added parts (not in original): {json.dumps(diff.get('added', []), indent=2)}
- Removed parts (were in original): {json.dumps(diff.get('removed', []), indent=2)}
- Modified parts (qty or price changed): {json.dumps(diff.get('modified', []), indent=2)}
- Unchanged parts: {diff.get('unchanged_count', 0)}

For each change, analyze:
1. **likely_reason**: Why did staff make this change? (e.g., "wrong spring size", "missing weatherstrip", "customer requested upgrade")
2. **is_configurator_issue**: Is this a bug in the configurator's logic? (true/false)
3. **severity**: low / medium / high
4. **suggested_fix**: If it's a configurator issue, what should be fixed in the code?

Output JSON only:
```json
{{
  "changes_analysis": [
    {{
      "part_number": "PART-123",
      "change_type": "added|removed|modified",
      "likely_reason": "explanation",
      "is_configurator_issue": true/false,
      "severity": "low|medium|high",
      "suggested_fix": "description or null"
    }}
  ],
  "summary": "Brief overall assessment"
}}
```"""

        try:
            response = self.client.messages.create(
                model="claude-sonnet-4-5-20250929",
                max_tokens=4000,
                messages=[{"role": "user", "content": prompt}],
            )

            content = response.content[0].text
            if "```json" in content:
                json_start = content.find("```json") + 7
                json_end = content.find("```", json_start)
                content = content[json_start:json_end].strip()
            elif "```" in content:
                json_start = content.find("```") + 3
                json_end = content.find("```", json_start)
                content = content[json_start:json_end].strip()

            return json.loads(content)
        except Exception as e:
            logger.error(f"Quote diff analysis failed: {e}")
            return {"error": str(e), "changes_analysis": [], "summary": "Analysis failed"}

    def analyze_quote_patterns(
        self,
        reviews_data: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Cross-quote pattern analysis across multiple reviews.
        Identifies top recurring issues and suggests configurator code changes.

        Returns:
            {patterns: [{pattern, frequency, severity, suggestion}], code_suggestions, summary}
        """
        if not self.client:
            return {"error": "AI client not initialized"}

        prompt = f"""You are analyzing patterns across {len(reviews_data)} quote reviews for a garage door configurator.
Each review shows changes that staff made to configurator-generated quotes.
Identify recurring patterns that indicate systematic configurator issues.

**Reviews data:**
{json.dumps(reviews_data, indent=2)}

Analyze and identify:
1. **Top 5 recurring patterns** — parts frequently added/removed/modified
2. **Root causes** — which configurator logic is likely wrong
3. **Code suggestions** — specific files/functions to fix (the configurator code is in backend/app/services/part_number_service.py and backend/app/api/door_configurator.py)

Output JSON only:
```json
{{
  "patterns": [
    {{
      "pattern": "description of the recurring issue",
      "frequency": number_of_occurrences,
      "severity": "low|medium|high",
      "affected_parts": ["PART-1", "PART-2"],
      "suggestion": "what to fix"
    }}
  ],
  "code_suggestions": [
    {{
      "file": "backend/app/services/...",
      "function": "function_name",
      "issue": "what's wrong",
      "fix": "what to change"
    }}
  ],
  "summary": "Overall assessment of configurator accuracy"
}}
```"""

        try:
            response = self.client.messages.create(
                model="claude-sonnet-4-5-20250929",
                max_tokens=4000,
                messages=[{"role": "user", "content": prompt}],
            )

            content = response.content[0].text
            if "```json" in content:
                json_start = content.find("```json") + 7
                json_end = content.find("```", json_start)
                content = content[json_start:json_end].strip()
            elif "```" in content:
                json_start = content.find("```") + 3
                json_end = content.find("```", json_start)
                content = content[json_start:json_end].strip()

            return json.loads(content)
        except Exception as e:
            logger.error(f"Quote pattern analysis failed: {e}")
            return {"error": str(e), "patterns": [], "summary": "Analysis failed"}


# Global AI client instance
ai_client = ClaudeAIClient()

