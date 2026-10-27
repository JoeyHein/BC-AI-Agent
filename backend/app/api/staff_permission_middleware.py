"""Second gate for staff routes on the running app.

Dependencies call the same check. This catches a staff route that forgot
the dependency. Service keys are skipped: the allow-list middleware is the
outer gate and already decided.
"""
from fastapi import HTTPException
from fastapi.responses import JSONResponse

from app.services import staff_service_keys_service as staff_keys
from app.services.auth_service import auth_service
from app.services.staff_permissions import (
    enforce_staff_permission,
    permission_for,
)


def _bearer(request) -> str:
    header = request.headers.get("authorization") or ""
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return ""


async def staff_permission_middleware(request, call_next):
    if request.method == "OPTIONS":
        return await call_next(request)
    requirement = permission_for(request.method, request.url.path)
    if requirement is None:
        return await call_next(request)

    token = _bearer(request)
    if staff_keys.is_staff_service_key(token):
        return await call_next(request)
    if not token:
        return JSONResponse(
            status_code=401,
            content={"detail": "Not authenticated"},
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = auth_service.decode_token(token)
    if not payload:
        return JSONResponse(status_code=401, content={"detail": "Invalid authentication credentials"})
    if payload.get("user_type") == "customer":
        return JSONResponse(status_code=403, content={"detail": "Staff access required"})

    try:
        user_id = int(payload.get("sub"))
    except (TypeError, ValueError):
        return JSONResponse(status_code=401, content={"detail": "Invalid authentication credentials"})

    db = staff_keys.new_session()
    try:
        user = auth_service.get_user_by_id(db, user_id=user_id)
        if user is None:
            return JSONResponse(status_code=401, content={"detail": "User not found"})
        if not user.is_active:
            return JSONResponse(status_code=403, content={"detail": "User is inactive"})
        try:
            enforce_staff_permission(request, user)
        except HTTPException as exc:
            return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
    finally:
        db.close()
    return await call_next(request)
