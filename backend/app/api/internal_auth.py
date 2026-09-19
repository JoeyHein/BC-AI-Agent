"""Service-to-service auth for the internal read-only quote accuracy API.

Reads ``X-API-Key`` and compares it to ``QUOTE_ACCURACY_API_KEY`` using a
timing-safe digest. Missing, unknown, and forged keys all produce the same
401 so callers cannot distinguish which check failed. The key value is never
logged or echoed.

This is intentionally a dedicated env var, not ``INTEGRATIONS_API_KEY``
(which can POST CRM notes) and not ``X-Service-AI-Key`` (supplier-account
scoped). Unset configuration yields 503 so ops can tell "key not deployed"
from "bad key".
"""
from __future__ import annotations

import hashlib
import hmac
import logging
from typing import Optional

from fastapi import Header, HTTPException, status

from app.config import settings

logger = logging.getLogger(__name__)

_UNAUTHORIZED_DETAIL = "Invalid or missing X-API-Key"


def _digests_match(provided: str, expected: str) -> bool:
    """Length-independent timing-safe compare via SHA-256 then HMAC digest."""
    provided_digest = hashlib.sha256(provided.encode("utf-8")).digest()
    expected_digest = hashlib.sha256(expected.encode("utf-8")).digest()
    return hmac.compare_digest(provided_digest, expected_digest)


def require_quote_accuracy_key(
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
) -> None:
    """Reject unconfigured / missing / wrong keys. Never logs the secret."""
    expected = settings.QUOTE_ACCURACY_API_KEY
    if not expected:
        logger.error("QUOTE_ACCURACY_API_KEY not configured — quote accuracy calls rejected")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Quote accuracy API not configured",
        )
    if not x_api_key or not _digests_match(x_api_key, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_UNAUTHORIZED_DETAIL,
        )
