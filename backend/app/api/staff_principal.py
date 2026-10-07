"""Resolve a staff service key to the user object existing routes already accept.

Human JWTs do not start with ``osk_``. For those tokens this returns None
and the caller keeps its existing JWT checks, unchanged.
"""
from typing import Optional

from fastapi import HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.db.models import User
from app.services.staff_service_keys_service import evaluate, is_staff_service_key


def service_user_if_key(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials],
    db: Session,
) -> Optional[User]:
    """Return the service identity when ``credentials`` is a staff service key.

    The request gate normally verifies the key first and stashes the identity
    on ``request.state``. This repeats the check when that did not happen
    (tests, or a route reached without the gate) so a key cannot skip scopes.
    """
    token = credentials.credentials if credentials is not None else ""
    if not is_staff_service_key(token):
        return None
    cached = getattr(request.state, "staff_service_user", None)
    if cached is not None:
        return cached
    body = getattr(request, "_body", b"") or b""
    decision = evaluate(db, token, request.method, request.url.path, body)
    if not decision.ok:
        raise HTTPException(status_code=decision.status_code, detail=decision.detail)
    return decision.user
