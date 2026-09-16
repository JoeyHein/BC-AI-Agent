"""Internal read-only sales-quote lookup for quote accuracy review.

GET /api/internal/sales-quotes/{quote_number}
    Headers: X-API-Key: <QUOTE_ACCURACY_API_KEY>

Returns the BC sales quote header plus a page of lines so an authorized
internal caller can compare item numbers, descriptions, quantities,
dimensions/options, prices, discounts, tax, and freight against a portal/AI
draft. No create, update, approve, convert, or send.
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse

from app.api.internal_auth import require_quote_accuracy_key
from app.services.quote_accuracy_service import (
    DEFAULT_LINE_LIMIT,
    MAX_LINE_LIMIT,
    QuoteAccuracyError,
    fetch_sales_quote_for_accuracy,
)

router = APIRouter(prefix="/api/internal", tags=["internal-quote-accuracy"])
logger = logging.getLogger(__name__)

_ERROR_STATUS = {
    "INVALID_REQUEST": 400,
    "NOT_FOUND": 404,
    "UPSTREAM_ERROR": 502,
}


def _error_response(err: QuoteAccuracyError) -> JSONResponse:
    return JSONResponse(
        status_code=_ERROR_STATUS.get(err.code, 500),
        content={
            "ok": False,
            "error": {
                "code": err.code,
                "message": err.message,
                "retryable": err.retryable,
            },
        },
    )


def _audit(request: Request, *, quote_number: str, status_code: int, extra: str = "") -> None:
    rid = getattr(request.state, "request_id", None)
    logger.info(
        "quote_accuracy request quote_number=%s status=%s request_id=%s %s",
        quote_number,
        status_code,
        rid,
        extra,
    )


@router.get("/sales-quotes/{quote_number}")
def get_sales_quote(
    quote_number: str,
    request: Request,
    line_skip: int = Query(0, ge=0, description="Number of lines to skip after BC fetch"),
    line_limit: int = Query(
        DEFAULT_LINE_LIMIT,
        ge=1,
        le=MAX_LINE_LIMIT,
        description="Max lines to return in this page",
    ),
    _: None = Depends(require_quote_accuracy_key),
) -> Dict[str, Any]:
    """Look up one production BC sales quote by document number."""
    try:
        result = fetch_sales_quote_for_accuracy(
            quote_number,
            line_skip=line_skip,
            line_limit=line_limit,
        )
    except QuoteAccuracyError as err:
        _audit(request, quote_number=quote_number, status_code=_ERROR_STATUS.get(err.code, 500), extra=f"code={err.code}")
        return _error_response(err)

    _audit(
        request,
        quote_number=result.quote.get("number") or quote_number,
        status_code=200,
        extra=f"line_count={result.line_count} returned={len(result.lines)} has_more={result.has_more}",
    )
    return {
        "ok": True,
        "data": {
            "quote": result.quote,
            "lines": result.lines,
            "lineCount": result.line_count,
            "lineSkip": result.line_skip,
            "lineLimit": result.line_limit,
            "hasMore": result.has_more,
        },
    }
