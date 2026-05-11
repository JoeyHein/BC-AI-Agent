"""
Customer Team Management API
============================

Customer-facing endpoints for managing the user roster on a BC customer
account. Mirrors the admin /api/admin/customers/{id}/linked-users router
but the actor is the customer themselves (a CUSTOMER user with
is_customer_admin=True), not an OPENDC admin.

Rules:
  - All endpoints require user_type='CUSTOMER'.
  - List endpoint is open to any team member.
  - Write endpoints (add, update, remove) require is_customer_admin=True.
  - You cannot demote / remove yourself if you'd leave the account with
    zero customer admins — at least one admin must always remain.
  - You cannot remove a user who is on a DIFFERENT BC customer account.
  - OPENDC admins retain override via /api/admin/customers/.../linked-users
    (unchanged from before).
"""

import logging
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from app.api.customer_auth import get_current_customer
from app.db.database import get_db
from app.db.models import User, UserRole
from app.services.auth_service import auth_service

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/customer/portal/team",
    tags=["customer-team"],
)


# ----------------------------------------------------------------------
# Schemas
# ----------------------------------------------------------------------

class TeamMember(BaseModel):
    id: int
    email: str
    name: Optional[str] = None
    is_active: bool
    is_customer_admin: bool
    account_status: Optional[str] = None
    account_type: Optional[str] = None
    last_login_at: Optional[datetime] = None
    created_at: datetime
    is_self: bool = False

    class Config:
        from_attributes = True


class AddTeamMemberRequest(BaseModel):
    email: EmailStr
    name: Optional[str] = None
    password: Optional[str] = None  # required if creating a new user
    is_customer_admin: bool = False


class UpdateTeamMemberRequest(BaseModel):
    is_active: Optional[bool] = None
    is_customer_admin: Optional[bool] = None


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------

def _require_customer_admin(user: User) -> None:
    if not user.is_customer_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only a customer admin can manage team members.",
        )


def _require_bc_link(user: User) -> str:
    if not user.bc_customer_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Your account is not yet linked to a business account. "
                "Contact OPENDC support to link, then add team members."
            ),
        )
    return user.bc_customer_id


def _team_query(db: Session, bc_customer_id: str):
    return (
        db.query(User)
        .filter(
            User.bc_customer_id == bc_customer_id,
            User.user_type == "CUSTOMER",
        )
        .order_by(User.created_at.asc())
    )


def _to_member(u: User, current_user_id: int) -> TeamMember:
    return TeamMember(
        id=u.id,
        email=u.email,
        name=u.name,
        is_active=u.is_active,
        is_customer_admin=u.is_customer_admin,
        account_status=u.account_status,
        account_type=u.account_type,
        last_login_at=u.last_login_at,
        created_at=u.created_at,
        is_self=(u.id == current_user_id),
    )


def _count_active_admins(db: Session, bc_customer_id: str) -> int:
    return (
        db.query(User)
        .filter(
            User.bc_customer_id == bc_customer_id,
            User.user_type == "CUSTOMER",
            User.is_customer_admin.is_(True),
            User.is_active.is_(True),
        )
        .count()
    )


# ----------------------------------------------------------------------
# Endpoints
# ----------------------------------------------------------------------

@router.get("", response_model=List[TeamMember])
def list_team(
    current_user: User = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    """List every staff user on the current customer's BC account."""
    bc_id = _require_bc_link(current_user)
    users = _team_query(db, bc_id).all()
    return [_to_member(u, current_user.id) for u in users]


@router.post("", response_model=TeamMember)
def add_team_member(
    body: AddTeamMemberRequest,
    current_user: User = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    """Add a staff user to the current customer's BC account.

    If a user with the email already exists and is CUSTOMER-typed, they
    are linked into this account (must not already belong to a different
    one). Otherwise a fresh approved user is created.
    """
    _require_customer_admin(current_user)
    bc_id = _require_bc_link(current_user)

    target = db.query(User).filter(User.email == body.email).first()
    if target:
        if target.user_type != "CUSTOMER":
            raise HTTPException(400, "That email belongs to a non-customer account.")
        if target.bc_customer_id and target.bc_customer_id != bc_id:
            raise HTTPException(
                400,
                "That user is already on a different business account. "
                "Ask OPENDC support to move them.",
            )
        target.bc_customer_id = bc_id
        target.account_status = "active"
        target.is_active = True
        if body.name and not target.name:
            target.name = body.name
        if body.password:
            target.password_hash = auth_service.get_password_hash(body.password)
        target.is_customer_admin = bool(body.is_customer_admin)
        db.commit()
        db.refresh(target)
        logger.info(
            f"Customer admin {current_user.email} linked existing user "
            f"{target.email} to BC {bc_id}"
        )
        return _to_member(target, current_user.id)

    # Create a fresh user.
    if not body.password or len(body.password) < 8:
        raise HTTPException(
            400, "Password is required (min 8 chars) when creating a new team member."
        )

    new_user = User(
        email=body.email,
        password_hash=auth_service.get_password_hash(body.password),
        name=body.name,
        role=UserRole.VIEWER,
        user_type="CUSTOMER",
        is_active=True,
        email_verified=True,
        account_type=current_user.account_type or "dealer",
        account_status="active",
        company_name=current_user.company_name,
        bc_customer_id=bc_id,
        is_customer_admin=bool(body.is_customer_admin),
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    logger.info(
        f"Customer admin {current_user.email} created new team member "
        f"{new_user.email} on BC {bc_id}"
    )
    return _to_member(new_user, current_user.id)


@router.patch("/{user_id}", response_model=TeamMember)
def update_team_member(
    user_id: int,
    body: UpdateTeamMemberRequest,
    current_user: User = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    """Activate / deactivate or promote / demote a team member."""
    _require_customer_admin(current_user)
    bc_id = _require_bc_link(current_user)

    target = (
        db.query(User)
        .filter(
            User.id == user_id,
            User.user_type == "CUSTOMER",
            User.bc_customer_id == bc_id,
        )
        .first()
    )
    if not target:
        raise HTTPException(404, "Team member not found on this account.")

    # Block self-demotion if it would leave the account with no admins.
    will_be_admin = (
        target.is_customer_admin if body.is_customer_admin is None
        else bool(body.is_customer_admin)
    )
    will_be_active = (
        target.is_active if body.is_active is None
        else bool(body.is_active)
    )
    losing_admin_powers = (
        target.is_customer_admin and target.is_active
        and not (will_be_admin and will_be_active)
    )
    if losing_admin_powers and _count_active_admins(db, bc_id) <= 1:
        raise HTTPException(
            400,
            "Can't remove the last customer admin on this account. "
            "Promote another team member first.",
        )

    if body.is_active is not None:
        target.is_active = bool(body.is_active)
    if body.is_customer_admin is not None:
        target.is_customer_admin = bool(body.is_customer_admin)
    db.commit()
    db.refresh(target)
    logger.info(
        f"Customer admin {current_user.email} updated team member "
        f"{target.email} on BC {bc_id} (active={target.is_active}, "
        f"admin={target.is_customer_admin})"
    )
    return _to_member(target, current_user.id)


@router.delete("/{user_id}")
def remove_team_member(
    user_id: int,
    current_user: User = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    """Unlink a staff user from the customer's BC account.

    Refuses self-removal (use admin support to leave) and refuses to
    remove the last active customer admin.
    """
    _require_customer_admin(current_user)
    bc_id = _require_bc_link(current_user)

    if user_id == current_user.id:
        raise HTTPException(
            400,
            "You can't remove yourself. Promote another admin first, then "
            "contact OPENDC support if you need to leave the account.",
        )

    target = (
        db.query(User)
        .filter(
            User.id == user_id,
            User.user_type == "CUSTOMER",
            User.bc_customer_id == bc_id,
        )
        .first()
    )
    if not target:
        raise HTTPException(404, "Team member not found on this account.")

    # Block removal if it'd leave zero admins.
    if (
        target.is_customer_admin
        and target.is_active
        and _count_active_admins(db, bc_id) <= 1
    ):
        raise HTTPException(
            400,
            "Can't remove the last customer admin. Promote another team "
            "member first.",
        )

    target.bc_customer_id = None
    db.commit()
    logger.info(
        f"Customer admin {current_user.email} removed team member "
        f"{target.email} from BC {bc_id}"
    )
    return {"message": f"Removed {target.email} from your team."}
