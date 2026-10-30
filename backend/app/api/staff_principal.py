"""Resolve a staff service key to the user object existing routes already accept.

Human JWTs do not start with ``osk_``. For those tokens this returns None
and the caller keeps its existing JWT checks, unchanged.
"""
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import User
from app.services.auth_service import auth_service
from app.services.staff_permissions import enforce_staff_permission
from app.services.staff_service_keys_service import evaluate, is_staff_service_key

_bearer = HTTPBearer(auto_error=False)


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


def _authenticated_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials],
    db: Session,
    *,
    allow_customer: bool,
) -> User:
    """Staff JWT, staff service key, and (when allowed) a customer JWT.

    No token is 401. A customer login is 403 unless ``allow_customer``.
    """
    if credentials is None or not (credentials.credentials or "").strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    service_user = service_user_if_key(request, credentials, db)
    if service_user is not None:
        return service_user

    payload = auth_service.decode_token(credentials.credentials)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not allow_customer and payload.get("user_type") == "customer":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Staff access required",
        )

    try:
        user_id = int(payload.get("sub"))
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
        )

    user = auth_service.get_user_by_id(db, user_id=user_id)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )
    if not allow_customer and (getattr(user, "user_type", None) or "").upper() == "CUSTOMER":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Staff access required",
        )
    if (getattr(user, "user_type", None) or "").upper() != "CUSTOMER":
        enforce_staff_permission(request, user)
    return user


def require_staff(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    """A logged-in staff person, or a staff service key.

    No token is 401. A customer-portal login is 403. A service key is
    accepted only when the key is allowed to call this route.
    """
    return _authenticated_user(request, credentials, db, allow_customer=False)


def require_staff_or_customer(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    """Staff or customer portal login. Anonymous requests are rejected.

    The shop-drawing preview is called from the staff configurator and from
    the customer portal before a quote is saved. Both are signed in. A
    request with no token is 401.
    """
    return _authenticated_user(request, credentials, db, allow_customer=True)
