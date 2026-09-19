"""Read-only BC sales-quote lookup for post-quote accuracy review.

Wraps the existing BC OData client. No create / update / approve / convert /
send. Company id is always the server-configured production company — callers
cannot supply one.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import requests

from app.integrations.bc.client import bc_client

logger = logging.getLogger(__name__)

# SQ-003058, sq-3058, 3058, 003058 — numeric document numbers only.
_QUOTE_NUMBER_RE = re.compile(r"^(?:SQ-)?(\d{1,20})$", re.IGNORECASE)

# Hard cap on lines returned in one response (OData pages are followed first).
MAX_LINE_LIMIT = 500
DEFAULT_LINE_LIMIT = 200

_HEADER_FIELDS = (
    "id",
    "number",
    "status",
    "customerNumber",
    "customerName",
    "billToCustomerNumber",
    "billToName",
    "sellToAddressLine1",
    "sellToCity",
    "sellToState",
    "sellToPostCode",
    "sellToCountry",
    "documentDate",
    "postingDate",
    "dueDate",
    "validUntilDate",
    "sentDate",
    "orderDate",
    "requestedDeliveryDate",
    "salesperson",
    "externalDocumentNumber",
    "currencyCode",
    "paymentTermsId",
    "shipmentMethodId",
    "discountAmount",
    "discountAppliedBeforeTax",
    "totalAmountExcludingTax",
    "totalTaxAmount",
    "totalAmountIncludingTax",
)

_LINE_FIELDS = (
    "id",
    "sequence",
    "lineType",
    "lineObjectNumber",
    "description",
    "description2",
    "quantity",
    "unitOfMeasureCode",
    "unitPrice",
    "discountAmount",
    "discountPercent",
    "discountAppliedBeforeTax",
    "amountExcludingTax",
    "taxCode",
    "taxPercent",
    "totalTaxAmount",
    "amountIncludingTax",
    "invoiceDiscountAllocation",
    "netAmount",
    "netTaxAmount",
    "netAmountIncludingTax",
    "shipmentDate",
    "itemVariantId",
    "locationId",
)


class QuoteAccuracyError(Exception):
    def __init__(self, code: str, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


@dataclass
class QuoteAccuracyResult:
    quote: Dict[str, Any]
    lines: List[Dict[str, Any]]
    line_count: int
    line_skip: int
    line_limit: int
    has_more: bool
    lines_truncated_upstream: bool = False
    extra: Dict[str, Any] = field(default_factory=dict)


def normalize_quote_number(raw: str) -> str:
    """Validate and normalize a BC sales quote document number.

    Accepts ``SQ-003058``, ``sq-3058``, or ``3058`` and returns ``SQ-003058``.
    Raises ``QuoteAccuracyError(INVALID_REQUEST)`` on anything else so OData
    filters never see quotes, spaces, or wildcards.
    """
    if raw is None or not str(raw).strip():
        raise QuoteAccuracyError("INVALID_REQUEST", "Quote number is required")
    candidate = str(raw).strip().upper()
    match = _QUOTE_NUMBER_RE.fullmatch(candidate)
    if not match:
        raise QuoteAccuracyError(
            "INVALID_REQUEST",
            "Quote number must be a BC document number such as SQ-003058",
        )
    digits = match.group(1)
    if len(digits) < 6:
        digits = digits.zfill(6)
    return f"SQ-{digits}"


def _pick(src: Dict[str, Any], keys: Tuple[str, ...]) -> Dict[str, Any]:
    return {key: src.get(key) for key in keys if key in src}


def _line_flags(line: Dict[str, Any]) -> List[str]:
    flags: List[str] = []
    line_type = (line.get("lineType") or "").strip()
    sku = (line.get("lineObjectNumber") or "").strip().upper()
    desc = f"{line.get('description') or ''} {line.get('description2') or ''}".lower()
    if line_type.lower() == "comment":
        flags.append("comment")
    if sku.startswith("FREIGHT") or "freight" in desc:
        flags.append("freight")
    tax_amount = line.get("totalTaxAmount") or line.get("netTaxAmount") or 0
    try:
        tax_val = float(tax_amount)
    except (TypeError, ValueError):
        tax_val = 0.0
    if tax_val or (line.get("taxCode") and str(line.get("taxCode")).strip()):
        flags.append("tax")
    if line_type.lower() in ("account", "g/l account", "gl account"):
        flags.append("gl_account")
    return flags


def _sanitize_dimension_set_lines(raw: Any) -> Optional[List[Dict[str, Any]]]:
    if not raw:
        return None
    rows = raw
    if isinstance(raw, dict) and "value" in raw:
        rows = raw.get("value") or []
    if not isinstance(rows, list):
        return None
    cleaned: List[Dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        cleaned.append(
            {
                "code": row.get("code"),
                "displayName": row.get("displayName"),
                "valueCode": row.get("valueCode"),
                "valueDisplayName": row.get("valueDisplayName"),
            }
        )
    return cleaned or None


def _map_line(raw: Dict[str, Any]) -> Dict[str, Any]:
    mapped = _pick(raw, _LINE_FIELDS)
    mapped["itemNumber"] = raw.get("lineObjectNumber")
    mapped["flags"] = _line_flags(raw)
    dimensions = _sanitize_dimension_set_lines(raw.get("dimensionSetLines"))
    if dimensions:
        mapped["dimensionSetLines"] = dimensions
    return mapped


def fetch_sales_quote_for_accuracy(
    quote_number: str,
    *,
    line_skip: int = 0,
    line_limit: int = DEFAULT_LINE_LIMIT,
    client: Any = None,
) -> QuoteAccuracyResult:
    """Look up a sales quote by document number and return header + lines.

    ``client`` is injectable for tests; production uses the module-level
    ``bc_client``. Pagination applies to the *response* window over the full
    BC line set (OData nextLink is followed first).
    """
    if line_skip < 0:
        raise QuoteAccuracyError("INVALID_REQUEST", "line_skip must be >= 0")
    if line_limit < 1 or line_limit > MAX_LINE_LIMIT:
        raise QuoteAccuracyError(
            "INVALID_REQUEST",
            f"line_limit must be between 1 and {MAX_LINE_LIMIT}",
        )

    normalized = normalize_quote_number(quote_number)
    bc = client or bc_client

    try:
        header = bc.get_sales_quote_by_number(normalized)
    except requests.HTTPError as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        logger.warning(
            "quote_accuracy BC header lookup failed quote_number=%s http_status=%s",
            normalized,
            status,
        )
        if status == 404:
            raise QuoteAccuracyError("NOT_FOUND", "Sales quote not found") from exc
        raise QuoteAccuracyError(
            "UPSTREAM_ERROR",
            "Business Central quote lookup failed",
            retryable=True,
        ) from exc
    except Exception as exc:
        logger.warning(
            "quote_accuracy BC header lookup failed quote_number=%s error_type=%s",
            normalized,
            type(exc).__name__,
        )
        raise QuoteAccuracyError(
            "UPSTREAM_ERROR",
            "Business Central quote lookup failed",
            retryable=True,
        ) from exc

    if not header or not header.get("id"):
        raise QuoteAccuracyError("NOT_FOUND", "Sales quote not found")

    quote_id = header["id"]
    try:
        raw_lines = bc.get_quote_lines(quote_id, expand_dimensions=True)
    except TypeError:
        # Test doubles / older client stubs may not accept expand_dimensions.
        raw_lines = bc.get_quote_lines(quote_id)
    except requests.HTTPError as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        logger.warning(
            "quote_accuracy BC lines lookup failed quote_number=%s http_status=%s",
            normalized,
            status,
        )
        raise QuoteAccuracyError(
            "UPSTREAM_ERROR",
            "Business Central quote lines lookup failed",
            retryable=True,
        ) from exc
    except Exception as exc:
        logger.warning(
            "quote_accuracy BC lines lookup failed quote_number=%s error_type=%s",
            normalized,
            type(exc).__name__,
        )
        raise QuoteAccuracyError(
            "UPSTREAM_ERROR",
            "Business Central quote lines lookup failed",
            retryable=True,
        ) from exc

    if not isinstance(raw_lines, list):
        raw_lines = []

    mapped_lines = [_map_line(row) for row in raw_lines if isinstance(row, dict)]
    window = mapped_lines[line_skip : line_skip + line_limit]
    has_more = (line_skip + len(window)) < len(mapped_lines)

    quote = _pick(header, _HEADER_FIELDS)
    quote["number"] = header.get("number") or normalized

    logger.info(
        "quote_accuracy fetched quote_number=%s line_count=%s returned=%s skip=%s limit=%s has_more=%s",
        normalized,
        len(mapped_lines),
        len(window),
        line_skip,
        line_limit,
        has_more,
    )

    return QuoteAccuracyResult(
        quote=quote,
        lines=window,
        line_count=len(mapped_lines),
        line_skip=line_skip,
        line_limit=line_limit,
        has_more=has_more,
    )
