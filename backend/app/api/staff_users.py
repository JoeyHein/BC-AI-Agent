"""Staff directory routes. auth.py registers these on /api/auth.

Customer team admin stays on /api/customer/portal/team.
"""
from typing import Optional

from fastapi import Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from app.db.models import User
from app.services.auth_service import auth_service
from app.services.staff_directory import (
    accept_reset,
    accept_setup,
    invite_staff,
    list_audit,
    list_staff,
    send_password_reset,
    send_setup_link,
    set_active,
    update_staff,
)
from app.services.staff_permissions import catalog, has_permission, serialize_user


class InviteBody(BaseModel):
    email: EmailStr
    name: str
    role: str = "viewer"
    permissions: Optional[dict] = None
    password: Optional[str] = None


class UpdateBody(BaseModel):
    role: Optional[str] = None
    permissions: Optional[dict] = None
    reset_permissions: bool = False
    is_active: Optional[bool] = None


class PasswordBody(BaseModel):
    token: str
    password: str
    name: Optional[str] = None


def _token_response(user: User) -> dict:
    return {
        "access_token": auth_service.create_access_token(data={"sub": str(user.id)}),
        "token_type": "bearer",
        "user": serialize_user(user),
    }


def register_staff_routes(router, get_db, get_current_user) -> None:
    """Attach directory routes to the auth router so existing mounts keep them."""

    def require_user_admin(current_user: User = Depends(get_current_user)) -> User:
        if not has_permission(current_user, "users.manage"):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
        return current_user

    def require_user_view(current_user: User = Depends(get_current_user)) -> User:
        if not has_permission(current_user, "users.view"):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
        return current_user

    @router.get("/permission-catalog")
    def permission_catalog(_user: User = Depends(require_user_view)):
        return catalog()

    @router.get("/access-audit")
    def access_audit(
        limit: int = 50,
        db: Session = Depends(get_db),
        _user: User = Depends(require_user_view),
    ):
        return list_audit(db, limit)

    @router.get("/users")
    def list_users(
        db: Session = Depends(get_db),
        _user: User = Depends(require_user_view),
    ):
        return list_staff(db)

    @router.post("/users")
    def create_user(
        body: InviteBody,
        db: Session = Depends(get_db),
        actor: User = Depends(require_user_admin),
    ):
        """Invite a staff login. The person sets their own password from the link."""
        if body.password:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Don't type a password. The person sets their own from the setup link.",
            )
        return invite_staff(db, actor, body.email, body.name, body.role, body.permissions)

    @router.patch("/users/{user_id}")
    def patch_user(
        user_id: int,
        body: UpdateBody,
        db: Session = Depends(get_db),
        actor: User = Depends(require_user_admin),
    ):
        return update_staff(
            db,
            actor,
            user_id,
            role=body.role,
            permissions=body.permissions,
            reset_permissions=body.reset_permissions,
            is_active=body.is_active,
        )

    @router.post("/users/{user_id}/disable")
    def disable_user(
        user_id: int,
        db: Session = Depends(get_db),
        actor: User = Depends(require_user_admin),
    ):
        return set_active(db, actor, user_id, False)

    @router.post("/users/{user_id}/enable")
    def enable_user(
        user_id: int,
        db: Session = Depends(get_db),
        actor: User = Depends(require_user_admin),
    ):
        return set_active(db, actor, user_id, True)

    @router.post("/users/{user_id}/setup-link")
    def refresh_setup_link(
        user_id: int,
        db: Session = Depends(get_db),
        actor: User = Depends(require_user_admin),
    ):
        return send_setup_link(db, actor, user_id)

    @router.post("/users/{user_id}/password-reset")
    def reset_password_link(
        user_id: int,
        db: Session = Depends(get_db),
        actor: User = Depends(require_user_admin),
    ):
        return send_password_reset(db, actor, user_id)

    @router.delete("/users/{user_id}")
    def delete_user(
        user_id: int,
        db: Session = Depends(get_db),
        actor: User = Depends(require_user_admin),
    ):
        """Disable the login and keep the row. Staff history stays on the account."""
        user = set_active(db, actor, user_id, False)
        return {"message": f"User {user['email']} disabled", "user": user}

    @router.post("/setup")
    def setup_account(body: PasswordBody, db: Session = Depends(get_db)):
        return _token_response(accept_setup(db, body.token, body.password, body.name))

    @router.post("/reset-password")
    def reset_password(body: PasswordBody, db: Session = Depends(get_db)):
        return _token_response(accept_reset(db, body.token, body.password))
