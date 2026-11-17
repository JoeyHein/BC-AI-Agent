"""Title and search text for a customer saved quote.

Customers name a quote on the first step of the builder ("Job Name / Tag").
That string is stored on ``SavedQuoteConfig.name``. Some older rows only have
the same label inside ``config_data`` (tagName / jobName / quoteName / tag),
or only a PO / reference. The My Quotes card uses this title and never the
placeholder "No description".
"""
from typing import Any, Optional

# Copies of the job name / tag, when an older save put it in config_data
# instead of the name column.
_TAG_KEYS = ("tagName", "jobName", "quoteName", "tag", "job_name", "quote_name")
# The optional PO / reference typed on the review step.
_REFERENCE_KEYS = ("poNumber", "po_number", "reference", "customerReference")


def _clean(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _config(config_data: Any) -> dict:
    return config_data if isinstance(config_data, dict) else {}


def _first(values) -> str:
    for value in values:
        text = _clean(value)
        if text:
            return text
    return ""


def quote_tag_name(name: Optional[str], config_data: Any = None) -> str:
    """The job name / tag the customer typed, from the column or config_data."""
    config = _config(config_data)
    return _first([name, *(config.get(key) for key in _TAG_KEYS)])


def quote_display_title(
    name: Optional[str],
    description: Optional[str] = None,
    bc_quote_number: Optional[str] = None,
    config_data: Any = None,
) -> str:
    """Card title: job name / tag, then description, then the SQ number.

    A PO / reference is used when that is the only label the customer typed
    and both the name and the description are blank. The result is never the
    placeholder "No description".
    """
    config = _config(config_data)
    title = _first([
        quote_tag_name(name, config),
        description,
        *(config.get(key) for key in _REFERENCE_KEYS),
        bc_quote_number,
    ])
    return title or "Quote"


def quote_search_text(
    name: Optional[str],
    description: Optional[str] = None,
    bc_quote_number: Optional[str] = None,
    config_data: Any = None,
) -> str:
    """Lowercased text the My Quotes search box matches."""
    config = _config(config_data)
    parts = [
        name,
        description,
        bc_quote_number,
        *(config.get(key) for key in _TAG_KEYS),
        *(config.get(key) for key in _REFERENCE_KEYS),
    ]
    return "\n".join(_clean(part).lower() for part in parts if _clean(part))


def quote_matches_search(
    name: Optional[str],
    needle: str,
    description: Optional[str] = None,
    bc_quote_number: Optional[str] = None,
    config_data: Any = None,
) -> bool:
    term = _clean(needle).lower()
    if not term:
        return True
    return term in quote_search_text(name, description, bc_quote_number, config_data)
