"""Claude Vision product identification.

Takes a user photo of a garage-door / dock product and asks Claude to identify
the category, most-likely brand(s), and family/model, grounded in the set of
brands actually present in the Part Finder index. The structured guess is then
matched back to indexed documents so the user gets real manuals to confirm.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
from typing import Optional

from .metadata import normalize_brand
from .store import PartFinderStore

logger = logging.getLogger(__name__)

# Sonnet balances vision accuracy and cost for this task; override via env.
VISION_MODEL = os.environ.get("PARTFINDER_VISION_MODEL", "claude-sonnet-4-6")

SUPPORTED_MEDIA = {"image/jpeg", "image/png", "image/webp", "image/gif"}

_SYSTEM = (
    "You are an expert technician who identifies garage doors, garage door "
    "operators (openers), springs, hardware, dock levelers, dock seals, and "
    "related loading-dock equipment from photographs. You reason from visible "
    "design cues: panel profile and embossing, window/glass layout, slat shape, "
    "operator head-unit shape and button layout, label/data-plate text, color, "
    "mounting style, and any visible logos or model markings."
)


def _build_prompt(brand_block: str, hint_category: Optional[str], note: Optional[str]) -> str:
    cat_line = f"\nThe user believes this is in the category: {hint_category}." if hint_category else ""
    note_line = f"\nUser note: {note}" if note else ""
    return f"""Identify the product in the image.{cat_line}{note_line}

These are the brands available in our catalog (use these names when a match is plausible; you may also name a brand not listed if the evidence is strong):
{brand_block}

Respond with ONLY a JSON object, no prose, in exactly this shape:
{{
  "category": "one of: Garage Door Panels | Garage Door Hardware | Garage Door Springs | Dock Equipment | Dock Seals & Shelters | Garage Door Operators | Unknown",
  "product_summary": "one sentence describing what the item is",
  "visible_features": ["short cues you used, e.g. 'long-panel raised profile', 'arched window inserts'"],
  "readable_text": ["any model numbers / words legible on labels or the product, else empty"],
  "candidates": [
    {{"brand": "BrandName", "family_or_model": "best guess or null", "confidence": 0.0, "reasoning": "why"}}
  ],
  "advice": "what photo or detail would most help narrow it further"
}}
Order candidates most-likely first; include up to 4. Confidence is 0..1."""


def _extract_json(text: str) -> dict:
    """Pull the first JSON object from the model output, tolerating fences."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            return json.loads(m.group(0))
        raise


def _match_documents(store: PartFinderStore, brand: str, category_label: Optional[str],
                     limit: int = 6) -> list[dict]:
    """Find indexed manuals for a guessed brand (normalized match)."""
    target = normalize_brand(brand)
    if not target:
        return []
    docs = []
    for b in store.brands():
        if normalize_brand(b["brand"]) == target:
            res = store.list_documents(brand=b["brand"], limit=limit)
            docs.extend(res["documents"])
    # De-dup by doc_id.
    seen, out = set(), []
    for d in docs:
        if d["doc_id"] not in seen:
            seen.add(d["doc_id"])
            out.append(d)
    return out[:limit]


def identify_image(
    image_bytes: bytes,
    media_type: str,
    store: PartFinderStore,
    api_key: Optional[str],
    hint_category: Optional[str] = None,
    note: Optional[str] = None,
) -> dict:
    if media_type not in SUPPORTED_MEDIA:
        return {"error": f"unsupported image type: {media_type}",
                "supported": sorted(SUPPORTED_MEDIA)}
    if not api_key:
        return {"error": "vision_unavailable",
                "detail": "ANTHROPIC_API_KEY not configured on the server."}

    from anthropic import Anthropic

    client = Anthropic(api_key=api_key)
    brand_block = store.brand_summaries() if store.available else "(catalog index unavailable)"
    prompt = _build_prompt(brand_block, hint_category, note)
    b64 = base64.standard_b64encode(image_bytes).decode("ascii")

    try:
        resp = client.messages.create(
            model=VISION_MODEL,
            max_tokens=1024,
            system=_SYSTEM,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "image",
                         "source": {"type": "base64", "media_type": media_type, "data": b64}},
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
        )
    except Exception as e:
        logger.exception("Vision API call failed")
        return {"error": "vision_call_failed", "detail": str(e)}

    raw = "".join(block.text for block in resp.content if getattr(block, "type", "") == "text")
    try:
        parsed = _extract_json(raw)
    except Exception:
        return {"error": "parse_failed", "raw": raw[:2000]}

    # Attach indexed manuals to each brand candidate.
    cat_label = parsed.get("category")
    for cand in parsed.get("candidates", []):
        cand["catalog_matches"] = _match_documents(store, cand.get("brand", ""), cat_label)

    parsed["model"] = VISION_MODEL
    return parsed
