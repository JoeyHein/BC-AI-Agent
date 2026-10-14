"""Staff KPI dashboard. Read-only.

Staff sign-in and a service key with the orders, purchasing, quotes, and
inventory read scopes can call these routes. Nothing here writes to
Business Central.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.staff_principal import require_staff
from app.db.database import get_db
from app.db.models import User
from app.services.kpi_dashboard_service import kpi_dashboard_service, resolve_range

router = APIRouter(prefix="/api/kpi", tags=["kpi"])

SECTIONS = ("purchasing", "sales", "financial", "operations")


def _dashboard(db: Session, start: Optional[date], end: Optional[date], refresh: bool) -> dict:
    try:
        window_start, window_end = resolve_range(start, end)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        return kpi_dashboard_service.get_dashboard(db, window_start, window_end, refresh=refresh)
    except Exception as exc:
        raise HTTPException(status_code=502, detail="The KPI dashboard could not be built.") from exc


@router.get("/dashboard")
def get_kpi_dashboard(
    start: Optional[date] = Query(None, alias="from"),
    end: Optional[date] = Query(None, alias="to"),
    refresh: bool = Query(False),
    db: Session = Depends(get_db),
    _user: User = Depends(require_staff),
):
    """Financial and operations KPIs for the staff home page and the assistant."""
    return _dashboard(db, start, end, refresh)


@router.get("/dashboard/{section}")
def get_kpi_section(
    section: str,
    start: Optional[date] = Query(None, alias="from"),
    end: Optional[date] = Query(None, alias="to"),
    refresh: bool = Query(False),
    db: Session = Depends(get_db),
    _user: User = Depends(require_staff),
):
    """One section: purchasing, sales, financial, or operations."""
    if section not in SECTIONS:
        raise HTTPException(status_code=404, detail="Unknown KPI section")
    payload = _dashboard(db, start, end, refresh)
    return {
        "range": payload.get("range"),
        "generated_at": payload.get("generated_at"),
        "cached": payload.get("cached"),
        "cache_seconds": payload.get("cache_seconds"),
        "section": section,
        "data": (payload.get("sections") or {}).get(section),
        "coverage": [
            note for note in payload.get("coverage") or []
            if note.get("section") == section
        ],
    }
