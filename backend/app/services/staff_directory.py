"""Invite, update, disable, and reset staff logins.

Customer team admin is a different router. This module only touches
internal staff. The automation identity is not a person and is not listed.
"""
from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import datetime, timedelta
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import StaffAccessAudit, User, UserRole
from app.services.auth_service import auth_service
from app.services.staff_permissions import (
    ASSIGNABLE_ROLES,
    SERVICE_USER_EMAIL,
    effective_permissions,
    permissions_for_storage,
    role_name,
    serialize_user,
)

logger = logging.getLogger(__name__)

INVITE_HOURS = 24 * 7
RESET_HOURS = 1
MIN_PASSWORD = 8


def _staff_filter(query):
    return query.filter(func.lower(User.email) != SERVICE_USER_EMAIL).filter(
        func.upper(func.coalesce(User.user_type, "INTERNAL")).notin_(["CUSTOMER", "SERVICE"])
    )


def list_staff(db: Session) -> list:
    rows = _staff_filter(db.query(User)).order_by(User.name.asc(), User.email.asc()).all()
    return [serialize_user(row) for row in rows]


def get_staff(db: Session, user_id: int) -> User:
    row = _staff_filter(db.query(User)).filter(User.id == user_id).first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Staff user not found")
    return row


def _role_enum(role: str) -> UserRole:
    key = (role or "").strip().lower()
    if key not in ASSIGNABLE_ROLES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unknown role. Choose a preset.",
        )
    return UserRole[key.upper()]


def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _issue_token(user: User, hours: int) -> str:
    raw = secrets.token_urlsafe(32)
    user.password_reset_token = _hash_token(raw)
    user.password_reset_expires = datetime.utcnow() + timedelta(hours=hours)
    return raw


def _clear_token(user: User) -> None:
    user.password_reset_token = None
    user.password_reset_expires = None


def _active_owners(db: Session, exclude_id: Optional[int] = None) -> int:
    query = db.query(User).filter(User.role == UserRole.OWNER, User.is_active.is_(True))
    if exclude_id is not None:
        query = query.filter(User.id != exclude_id)
    return query.count()


def _snapshot(user: User) -> dict:
    raw = user.permissions if isinstance(user.permissions, dict) else user.permissions
    return {
        "role": role_name(user),
        "is_active": bool(user.is_active),
        "invite_pending": bool(user.invite_pending),
        "permissions": raw,
        "effective": effective_permissions(user),
    }


def _audit(db: Session, actor: Optional[User], target: User, action: str, detail: dict) -> None:
    db.add(StaffAccessAudit(
        actor_user_id=getattr(actor, "id", None),
        actor_email=getattr(actor, "email", None),
        target_user_id=target.id,
        target_email=target.email,
        action=action,
        detail=detail,
        created_at=datetime.utcnow(),
    ))


def _portal_links(raw: str, kind: str) -> dict:
    from app.config import settings

    path = "/setup" if kind == "invite" else "/reset-password"
    base = (settings.ADMIN_PORTAL_URL or "http://localhost:3001").rstrip("/")
    route = f"{path}?token={raw}"
    return {"setup_path": route, "setup_url": f"{base}{route}"}


def _email_link(email: str, name: Optional[str], url: str, kind: str) -> bool:
    subject = "Set up your OpenDC portal login" if kind == "invite" else "Reset your OpenDC portal password"
    who = name or email
    intro = (
        "An administrator created a portal login for you. Choose a password to finish setup."
        if kind == "invite"
        else "An administrator asked to reset your portal password. Choose a new one with the button below."
    )
    body = f"""
    <html><body style="font-family: Arial, sans-serif; line-height: 1.5;">
      <p>Hi {who},</p>
      <p>{intro}</p>
      <p><a href="{url}">{url}</a></p>
      <p>If you were not expecting this, you can ignore the email.</p>
    </body></html>
    """
    try:
        from app.services.notification_service import notification_service
        return bool(notification_service.send_email([email], subject, body))
    except Exception:
        logger.warning("Staff access email failed for %s", email, exc_info=True)
        return False


def _owner_authority(db: Session, actor: User) -> bool:
    """Owners can change owners. If the portal has none yet, an admin can create the first one."""
    if role_name(actor) == "owner":
        return True
    return role_name(actor) == "admin" and _active_owners(db) == 0


def _guard_owner_change(db: Session, actor: User, target: User, new_role: str, new_active: bool) -> None:
    actor_role = role_name(actor)
    if role_name(target) == "owner" and actor_role != "owner":
        raise HTTPException(status_code=403, detail="Only an owner can change an owner's access")
    if new_role == "owner" and not _owner_authority(db, actor):
        raise HTTPException(status_code=403, detail="Only an owner can assign the owner role")
    if actor.id == target.id and not new_active:
        raise HTTPException(status_code=400, detail="You cannot disable your own login")
    was_active_owner = role_name(target) == "owner" and bool(target.is_active)
    stays = new_role == "owner" and new_active
    if was_active_owner and not stays and _active_owners(db, exclude_id=target.id) == 0:
        raise HTTPException(status_code=400, detail="The portal needs at least one active owner")
    if actor.id == target.id and new_role not in ("owner", "admin"):
        raise HTTPException(
            status_code=400,
            detail="Ask another owner to change your own access",
        )


def invite_staff(
    db: Session,
    actor: User,
    email: str,
    name: str,
    role: str,
    permissions: Optional[dict],
) -> dict:
    email = email.strip().lower()
    name = (name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name is required")
    role_key = (role or "viewer").strip().lower()
    _role_enum(role_key)
    if role_key == "owner" and not _owner_authority(db, actor):
        raise HTTPException(status_code=403, detail="Only an owner can assign the owner role")
    existing = db.query(User).filter(func.lower(User.email) == email).first()
    if existing is not None:
        raise HTTPException(status_code=400, detail="That email already has an account")
    try:
        stored = permissions_for_storage(role_key, permissions)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    user = User(
        email=email,
        password_hash=auth_service.get_password_hash(secrets.token_urlsafe(32)),
        name=name,
        role=_role_enum(role_key),
        is_active=False,
        user_type="INTERNAL",
        invite_pending=True,
        permissions=stored,
        is_customer_admin=False,
    )
    raw = _issue_token(user, INVITE_HOURS)
    db.add(user)
    db.flush()
    links = _portal_links(raw, "invite")
    emailed = _email_link(email, name, links["setup_url"], "invite")
    _audit(db, actor, user, "invite", {
        "role": role_key,
        "permissions_custom": stored is not None,
        "email_sent": emailed,
    })
    db.commit()
    db.refresh(user)
    return {**links, "email_sent": emailed, "user": serialize_user(user)}


def update_staff(
    db: Session,
    actor: User,
    user_id: int,
    role: Optional[str],
    permissions: Optional[dict],
    reset_permissions: bool,
    is_active: Optional[bool],
) -> dict:
    target = get_staff(db, user_id)
    before = _snapshot(target)
    new_role = (role or role_name(target)).strip().lower()
    _role_enum(new_role)
    new_active = target.is_active if is_active is None else bool(is_active)
    _guard_owner_change(db, actor, target, new_role, new_active)

    if actor.id == target.id and permissions is not None:
        try:
            from app.services.staff_permissions import normalize_permissions
            proposed = normalize_permissions(permissions)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not proposed.get("users.manage"):
            raise HTTPException(status_code=400, detail="Ask another owner to change your own access")

    if is_active is True and target.invite_pending:
        raise HTTPException(
            status_code=400,
            detail="Send the setup link. This person has not chosen a password yet.",
        )
    try:
        if permissions is not None:
            stored = permissions_for_storage(new_role, permissions)
        elif reset_permissions or role is not None:
            stored = None
        else:
            stored = target.permissions if isinstance(target.permissions, dict) else None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    target.role = _role_enum(new_role)
    target.permissions = stored
    if is_active is False:
        # A person who never chose a password stays invite-pending, so
        # re-enable cannot turn on a login that still has a random password.
        _clear_token(target)
        target.is_active = False
    elif is_active is True:
        target.is_active = True
    _audit(db, actor, target, "update", {"before": before, "after": _snapshot(target)})
    db.commit()
    db.refresh(target)
    return serialize_user(target)


def set_active(db: Session, actor: User, user_id: int, active: bool) -> dict:
    return update_staff(
        db, actor, user_id,
        role=None, permissions=None, reset_permissions=False, is_active=active,
    )


def send_setup_link(db: Session, actor: User, user_id: int) -> dict:
    target = get_staff(db, user_id)
    if target.is_active and not target.invite_pending:
        raise HTTPException(
            status_code=400,
            detail="This person already has a password. Send a password reset instead.",
        )
    if role_name(target) == "owner" and role_name(actor) != "owner":
        raise HTTPException(status_code=403, detail="Only an owner can change an owner's access")
    raw = _issue_token(target, INVITE_HOURS)
    target.invite_pending = True
    target.is_active = False
    links = _portal_links(raw, "invite")
    emailed = _email_link(target.email, target.name, links["setup_url"], "invite")
    _audit(db, actor, target, "setup_link", {"email_sent": emailed})
    db.commit()
    db.refresh(target)
    return {**links, "email_sent": emailed, "user": serialize_user(target)}


def send_password_reset(db: Session, actor: User, user_id: int) -> dict:
    target = get_staff(db, user_id)
    if role_name(target) == "owner" and role_name(actor) != "owner" and actor.id != target.id:
        raise HTTPException(status_code=403, detail="Only an owner can change an owner's access")
    if target.invite_pending or not target.is_active:
        raise HTTPException(
            status_code=400,
            detail="This person has not finished setup. Send the setup link instead.",
        )
    raw = _issue_token(target, RESET_HOURS)
    links = _portal_links(raw, "reset")
    emailed = _email_link(target.email, target.name, links["setup_url"], "reset")
    _audit(db, actor, target, "password_reset", {"email_sent": emailed})
    db.commit()
    return {**links, "email_sent": emailed, "user": serialize_user(target)}


def _user_for_token(db: Session, raw: str) -> User:
    if not raw or not raw.strip():
        raise HTTPException(status_code=400, detail="This link is invalid or has expired")
    digest = _hash_token(raw.strip())
    user = db.query(User).filter(User.password_reset_token == digest).first()
    if user is None or user.password_reset_expires is None or user.password_reset_expires < datetime.utcnow():
        raise HTTPException(status_code=400, detail="This link is invalid or has expired")
    if (user.user_type or "").upper() == "CUSTOMER":
        raise HTTPException(status_code=400, detail="This link is invalid or has expired")
    return user


def _check_password(password: str) -> None:
    if password is None or len(password) < MIN_PASSWORD:
        raise HTTPException(
            status_code=400,
            detail=f"Password must be at least {MIN_PASSWORD} characters",
        )


def accept_setup(db: Session, token: str, password: str, name: Optional[str]) -> User:
    user = _user_for_token(db, token)
    if not user.invite_pending:
        raise HTTPException(status_code=400, detail="This link is invalid or has expired")
    _check_password(password)
    if name and name.strip():
        user.name = name.strip()
    user.password_hash = auth_service.get_password_hash(password)
    user.is_active = True
    user.invite_pending = False
    _clear_token(user)
    user.last_login_at = datetime.utcnow()
    _audit(db, user, user, "setup_complete", {})
    db.commit()
    db.refresh(user)
    return user


def accept_reset(db: Session, token: str, password: str) -> User:
    user = _user_for_token(db, token)
    if user.invite_pending or not user.is_active:
        raise HTTPException(status_code=400, detail="This link is invalid or has expired")
    _check_password(password)
    user.password_hash = auth_service.get_password_hash(password)
    _clear_token(user)
    user.last_login_at = datetime.utcnow()
    _audit(db, user, user, "password_reset_complete", {})
    db.commit()
    db.refresh(user)
    return user


def list_audit(db: Session, limit: int = 50) -> list:
    limit = max(1, min(limit, 200))
    rows = (
        db.query(StaffAccessAudit)
        .order_by(StaffAccessAudit.created_at.desc(), StaffAccessAudit.id.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": row.id,
            "actor_email": row.actor_email,
            "target_email": row.target_email,
            "action": row.action,
            "detail": row.detail,
            "created_at": row.created_at,
        }
        for row in rows
    ]
