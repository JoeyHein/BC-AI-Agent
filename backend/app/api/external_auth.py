"""
External API key auth dependency (SQB-04 / SQB-05).

Reads the `X-Service-AI-Key` header, verifies it against the
`external_api_keys` table, and exposes the matched row to the route
handler so endpoints can compare the bound `supplier_account_code`
against the request body.

Unknown / revoked / malformed keys produce a structured 401. Cross-key
probes (where the header is valid but the body's supplierAccountCode
doesn't match what the key is bound to) produce 404 NOT_FOUND so the
caller cannot infer the existence of another tenant's account code.

Response envelope on failure is the standard
`{ ok: false, error: { code, message } }` per Service.AI conventions —
mirrors what the bc-ai-agent's own client expects to receive.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.api.auth import get_db
from app.db.models import ExternalApiKey
from app.services.external_api_keys_service import verify

logger = logging.getLogger(__name__)


def require_external_key(
    x_service_ai_key: Optional[str] = Header(default=None, alias="X-Service-AI-Key"),
    db: Session = Depends(get_db),
) -> ExternalApiKey:
    """Resolve the X-Service-AI-Key header to an active `ExternalApiKey`
    row, raising 401 UNAUTHORIZED on any failure.

    Callers that need to validate the body's `supplier_account_code`
    against the key's binding should call `assert_account_code()`
    below — keeping the check explicit at the route layer makes the
    404-not-403 semantics easy to read.
    """
    if not x_service_ai_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "ok": False,
                "error": {
                    "code": "UNAUTHORIZED",
                    "message": "X-Service-AI-Key header required",
                },
            },
        )
    row = verify(db, x_service_ai_key)
    if row is None:
        # Same response for unknown / revoked / forged — never leak
        # which side of the check failed.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "ok": False,
                "error": {
                    "code": "UNAUTHORIZED",
                    "message": "Invalid or revoked API key",
                },
            },
        )
    return row


def assert_account_code(api_key: ExternalApiKey, body_account_code: str) -> None:
    """Raise 404 NOT_FOUND when the body's account_code doesn't match
    the key's binding. The 404 (not 403) prevents leaking the
    existence of other tenants' account codes."""
    if api_key.supplier_account_code != body_account_code:
        logger.warning(
            "External API key id=%s tried to access account_code=%s (bound to %s)",
            api_key.id, body_account_code, api_key.supplier_account_code,
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "ok": False,
                "error": {
                    "code": "NOT_FOUND",
                    "message": "Supplier account not found",
                },
            },
        )
