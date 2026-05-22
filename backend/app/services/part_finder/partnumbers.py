"""Domain-tuned model / part / catalog number extraction from manual text.

Two capture strategies, deliberately conservative to keep the search index
high-signal:

  labeled  -- a keyword (Model, Part, Item, Cat, No., Series, SKU, P/N)
              immediately followed by a code. Allows numeric-only codes here
              because the keyword disambiguates them from page numbers.
  alnum    -- standalone tokens carrying BOTH letters and digits
              (e.g. HI1000, AL976, MM372W, INST-4150079, DC2500E, OH1042FG).

Noise filters drop phone numbers, dates, pure measurements, and URLs.
"""

from __future__ import annotations

import re
from collections import defaultdict

# Keyword-led codes (numeric allowed because the label disambiguates).
_LABELED_RE = re.compile(
    r"(?:model|part|item|cat(?:alog(?:ue)?)?|no\.?|series|sku|p/?n|ref)\s*"
    r"[:#.\-]?\s*"
    r"([A-Za-z0-9][A-Za-z0-9./-]{1,19}[A-Za-z0-9])",
    re.IGNORECASE,
)

# Standalone alphanumeric token: must contain a letter and a digit.
_TOKEN_RE = re.compile(r"\b[A-Za-z0-9][A-Za-z0-9./-]{2,19}[A-Za-z0-9]\b")

# Multi-char measurement units that, when they make up the whole token's
# trailing alpha part, mark it as a measurement rather than a part number.
_MEASUREMENT_UNITS = (
    "mm", "cm", "in", "ft", "yd", "lb", "lbs", "kg", "oz", "hz", "khz",
    "psi", "rpm", "vdc", "vac", "ga", "awg", "deg", "pcs", "pc", "pt",
    "mph", "kph", "gal", "ml", "nm",
)

# Phone-number shapes (incl. vanity numbers like 1-800-503-DOOR).
_PHONE_RE = re.compile(r"^\+?\d{1,2}?[-.]?\d{3}[-.]\d{3,4}[-.]?[A-Za-z0-9]{0,4}$")
_TOLLFREE_RE = re.compile(r"^1?[-.]?(800|888|877|866|855|844|833)[-.]", re.I)

# Bare 4-digit years.
_YEAR_RE = re.compile(r"^(19|20)\d{2}$")

# Common English words that pass the labeled filter but are not codes.
_LABELED_STOPWORDS = {
    "tes", "the", "and", "for", "see", "all", "use", "not", "one", "two",
    "kit", "set", "max", "min", "ref", "fig", "page",
}

_MEASUREMENT_RE = re.compile(
    r"^\d+(?:\.\d+)?(?:" + "|".join(_MEASUREMENT_UNITS) + r")$", re.IGNORECASE
)

# Small-magnitude value + single-letter SI/duration unit: voltages, durations,
# forces, metric lengths (240V, 400N, 30SEC, 2.5M, 90S). A genuine model that
# happens to end in such a letter (e.g. LiftMaster 8500W) carries >=4 digits,
# so we only treat <=3-digit values as measurements.
_SHORT_MEASUREMENT_RE = re.compile(
    r"^\d{1,3}(?:\.\d+)?(?:V|N|W|A|M|H|S|SEC|MIN|HR|HRS|HZ|VA|KG|NM|MS|MA|KV)$",
    re.IGNORECASE,
)


def _normalize(token: str) -> str:
    return token.strip(" .,-/").upper()


def _is_noise(token: str) -> bool:
    if _PHONE_RE.match(token) or _TOLLFREE_RE.match(token):
        return True
    if _YEAR_RE.match(token):
        return True
    if _MEASUREMENT_RE.match(token) or _SHORT_MEASUREMENT_RE.match(token):
        return True
    # Slash-joined word noise like "60TIMES/HOUR"; real codes here don't use "/".
    if "/" in token:
        return True
    if "://" in token or token.lower().endswith((".com", ".pdf", ".net")):
        return True
    return False


def _has_letter_and_digit(token: str) -> bool:
    return bool(re.search(r"[A-Za-z]", token)) and bool(re.search(r"\d", token))


def extract_part_numbers(text: str) -> dict[str, dict]:
    """Return {normalized_token: {"raw": str, "kind": str, "freq": int}}.

    `kind` is 'labeled' (keyword-led), 'alnum' (letters+digits), or 'numeric'
    (numeric-only, only ever produced via the labeled path).
    """
    found: dict[str, dict] = defaultdict(lambda: {"raw": "", "kind": "", "freq": 0})

    if not text:
        return {}

    # 1) Labeled codes.
    for m in _LABELED_RE.finditer(text):
        raw = m.group(1)
        norm = _normalize(raw)
        if not norm or norm.lower() in _LABELED_STOPWORDS:
            continue
        if _is_noise(norm):
            continue
        # A labeled code must contain a digit to count (drops "Model Premium").
        if not re.search(r"\d", norm):
            continue
        kind = "numeric" if norm.isdigit() else ("alnum" if _has_letter_and_digit(norm) else "labeled")
        entry = found[norm]
        entry["raw"] = entry["raw"] or raw
        entry["kind"] = "labeled" if not entry["kind"] else entry["kind"]
        # Labeled hits are high-confidence; tag as labeled regardless of shape.
        entry["kind"] = "labeled"
        entry["freq"] += 1

    # 2) Standalone alphanumeric tokens.
    for m in _TOKEN_RE.finditer(text):
        raw = m.group(0)
        if not _has_letter_and_digit(raw):
            continue
        norm = _normalize(raw)
        if len(norm) < 3 or _is_noise(norm):
            continue
        entry = found[norm]
        entry["raw"] = entry["raw"] or raw
        if not entry["kind"]:
            entry["kind"] = "alnum"
        entry["freq"] += 1

    return dict(found)
