"""Staff KPI dashboard. Read-only.

The page and these routes read the stored monthly snapshot. They do not
call Business Central. A nightly job and the admin recalculate button
are what refresh the snapshot.

Staff sign-in and a service key with the orders, purchasing, quotes, and
inventory read scopes can read. Recalculate is an admin sign-in only.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.auth import require_admin
from app.api.staff_principal import require_staff
from app.db.database import get_db
from app.db.models import User
from app.services.kpi_snapshot_service import read_snapshot, request_recalculate

router = APIRouter(prefix="/api/kpi", tags=["kpi"])

SECTIONS = ("purchasing", "sales", "financial", "operations")


def _read(db: Session, month: Optional[str]) -> dict:
    try:
        return read_snapshot(db, month)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/dashboard")
def get_kpi_dashboard(
    month: Optional[str] = Query(None, description="YYYY-MM. Defaults to the current month."),
    db: Session = Depends(get_db),
    _user: User = Depends(require_staff),
):
    """Saved financial and operations KPIs for one month."""
    return _read(db, month)


@router.get("/dashboard/{section}")
def get_kpi_section(
    section: str,
    month: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    _user: User = Depends(require_staff),
):
    """One section of the saved snapshot: purchasing, sales, financial, or operations."""
    if section not in SECTIONS:
        raise HTTPException(status_code=404, detail="Unknown KPI section")
    payload = _read(db, month)
    return {
        "range": payload.get("range"),
        "generated_at": payload.get("generated_at"),
        "snapshot": payload.get("snapshot"),
        "cached": True,
        "section": section,
        "data": (payload.get("sections") or {}).get(section) if payload.get("sections") else None,
        "coverage": [
            note for note in payload.get("coverage") or []
            if note.get("section") == section
        ],
    }


@router.post("/recalculate")
def recalculate_kpi_month(
    month: Optional[str] = Query(None, description="YYYY-MM. Defaults to the current month."),
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    """Admin only. Calculates this month in the background from Business Central."""
    try:
        return request_recalculate(db, month)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
