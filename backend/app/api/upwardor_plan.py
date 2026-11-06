"""Staff page: Upwardor payable balance down to $500K by Christmas 2026.

Reads Business Central. Lever status and a staff actuals fallback are stored
locally. This router does not post payments or change purchase orders.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.staff_principal import require_staff
from app.db.database import get_db
from app.db.models import User
from app.services.staff_permissions import has_permission
from app.services.upwardor_plan import (
    GNB_STATUSES,
    PLAN_BY_WEEK,
    RETURN_CREDIT_STATUSES,
    STOCK_STATUSES,
)
from app.services.upwardor_plan_service import build_report, read_overrides, write_overrides

router = APIRouter(prefix="/api/metrics", tags=["metrics"])

_MAX_AMOUNT = 5_000_000
_LEVER_STATUSES = {
    "return_credit": RETURN_CREDIT_STATUSES,
    "gnb_january": GNB_STATUSES,
    "stock_po_holds": STOCK_STATUSES,
}


class LeverUpdate(BaseModel):
    id: str
    status: Optional[str] = None
    note: Optional[str] = Field(default=None, max_length=500)


class ActualsUpdate(BaseModel):
    week_of: str
    invoices: Optional[float] = None
    payments: Optional[float] = None
    credits: Optional[float] = None
    clear: bool = False


def _report(db: Session, user: User) -> dict:
    report = build_report(db)
    report["can_edit"] = has_permission(user, "users.manage")
    return report


@router.get("/upwardor-plan")
def get_upwardor_plan(
    db: Session = Depends(get_db),
    user: User = Depends(require_staff),
):
    """Week-by-week plan, actuals, and the Christmas reforecast."""
    return _report(db, user)


@router.patch("/upwardor-plan/levers")
def update_upwardor_lever(
    body: LeverUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_staff),
):
    """Admin status for a plan lever. December's buy cap is computed, so only its note is saved."""
    if not has_permission(user, "users.manage"):
        raise HTTPException(status_code=403, detail="Admin access required")
    if body.id not in _LEVER_STATUSES and body.id != "dec_buy_cap":
        raise HTTPException(status_code=400, detail="Unknown lever")
    if body.id == "dec_buy_cap" and body.status not in (None, ""):
        raise HTTPException(status_code=400, detail="The December buy cap is calculated from invoices")
    allowed = _LEVER_STATUSES.get(body.id)
    if allowed is not None and body.status is not None and body.status not in allowed:
        raise HTTPException(status_code=400, detail="Unknown lever status")

    saved = read_overrides(db)
    levers = dict(saved.get("levers") or {})
    current = dict(levers.get(body.id) or {})
    if body.status:
        current["status"] = body.status
    if body.note is not None:
        current["note"] = body.note.strip()
    levers[body.id] = current
    saved = {**saved, "levers": levers}
    write_overrides(db, saved, user.id)
    return _report(db, user)


@router.patch("/upwardor-plan/actuals")
def update_upwardor_actuals(
    body: ActualsUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_staff),
):
    """Admin figures used when Business Central does not have the week."""
    if not has_permission(user, "users.manage"):
        raise HTTPException(status_code=403, detail="Admin access required")
    try:
        from datetime import date
        week = date.fromisoformat(body.week_of)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="week_of must be YYYY-MM-DD") from exc
    if week not in PLAN_BY_WEEK:
        raise HTTPException(status_code=400, detail="week_of is not a plan week")

    saved = read_overrides(db)
    weeks = dict(saved.get("weeks") or {})
    key = week.isoformat()
    if body.clear:
        weeks.pop(key, None)
    else:
        current = dict(weeks.get(key) or {})
        for field in ("invoices", "payments", "credits"):
            if field not in body.model_fields_set:
                continue
            value = getattr(body, field)
            if value is None:
                current.pop(field, None)
                continue
            if value < 0 or value > _MAX_AMOUNT:
                raise HTTPException(status_code=400, detail=f"{field} must be between 0 and {_MAX_AMOUNT}")
            current[field] = round(value)
        if current:
            weeks[key] = current
        else:
            weeks.pop(key, None)
    saved = {**saved, "weeks": weeks}
    write_overrides(db, saved, user.id)
    return _report(db, user)
