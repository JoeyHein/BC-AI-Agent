"""Accept staff service keys on the way into existing staff routes.

If the request presents an ``osk_`` key (Authorization: Bearer, or
X-API-Key when Authorization is absent), verify it and default-deny any
route outside the key's scopes. Human JWTs are left alone.

Usage is written to ``staff_service_key_audit`` (key name, route, time).
The secret is never logged.
"""
from __future__ import annotations

import logging

from fastapi import Request
from fastapi.responses import JSONResponse

from app.services import staff_service_keys_service as staff_keys

logger = logging.getLogger(__name__)


def _promote_x_api_key(request: Request) -> None:
    """Copy X-API-Key into Authorization when the caller did not send a bearer token.

    Staff routes read Authorization via HTTPBearer. Promoting here lets an
    ``X-API-Key: osk_...`` header hit those same routes. A request that
    already has Authorization (a person's JWT) is not rewritten.
    """
    if request.headers.get("authorization"):
        return
    api_key = (request.headers.get("x-api-key") or "").strip()
    if not staff_keys.is_staff_service_key(api_key):
        return
    try:
        encoded = b"Bearer " + api_key.encode("ascii")
    except UnicodeEncodeError:
        return
    headers = list(request.scope.get("headers") or [])
    headers.append((b"authorization", encoded))
    request.scope["headers"] = headers
    if hasattr(request, "_headers"):
        del request._headers


def _bearer(request: Request) -> str:
    header = request.headers.get("authorization") or ""
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return ""


async def staff_service_key_middleware(request: Request, call_next):
    if request.method == "OPTIONS":
        return await call_next(request)

    _promote_x_api_key(request)
    token = _bearer(request)
    if not staff_keys.is_staff_service_key(token):
        return await call_next(request)

    body = b""
    path = staff_keys.normalize_path(request.url.path)
    if request.method.upper() == "POST" and path == "/api/admin/purchasing/generate-po":
        body = await request.body()

    db = staff_keys.new_session()
    try:
        decision = staff_keys.evaluate(db, token, request.method, path, body)
    finally:
        db.close()

    if decision.ok and decision.user is not None:
        request.state.staff_service_user = decision.user
        request.state.staff_service_key_id = decision.key_id
        request.state.staff_service_key_name = decision.key_name
        try:
            response = await call_next(request)
        except Exception:
            _record(decision, request.method, path, 500, "allowed")
            raise
        _record(decision, request.method, path, response.status_code, "allowed")
        logger.info(
            "Staff service key name=%s %s %s -> %s",
            decision.key_name,
            request.method,
            path,
            response.status_code,
        )
        return response

    logger.info(
        "Staff service key rejected name=%s outcome=%s %s %s",
        decision.key_name or "unknown",
        decision.outcome,
        request.method,
        path,
    )
    _record(decision, request.method, path, decision.status_code, decision.outcome)
    return JSONResponse(status_code=decision.status_code, content={"detail": decision.detail})


def _record(decision, method: str, path: str, status_code: int, outcome: str) -> None:
    db = staff_keys.new_session()
    try:
        staff_keys.write_audit(
            db,
            key_id=decision.key_id,
            key_name=decision.key_name,
            key_prefix=decision.key_prefix,
            method=method,
            path=path,
            decision=outcome,
            status_code=status_code,
        )
    except Exception:
        logger.warning("staff service key audit write failed", exc_info=True)
    finally:
        db.close()
