"""Saved KPI months.

The dashboard reads these rows and does not call Business Central.
A nightly job (and an admin recalculate) is what fills them.
"""
from __future__ import annotations

import logging
import threading
from calendar import monthrange
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.db.database import SessionLocal
from app.db.models import KpiSnapshot

logger = logging.getLogger(__name__)

EDMONTON = ZoneInfo("America/Edmonton")
STALE_AFTER = timedelta(minutes=45)
_RUN_LOCK = threading.Lock()
_RUNNING: set[str] = set()


@dataclass(frozen=True)
class MonthWindow:
    month_key: str
    start: date
    end: date
    frozen: bool

    @property
    def label(self) -> str:
        return self.start.strftime("%B %Y")


def edmonton_today(now: Optional[datetime] = None) -> date:
    moment = now or datetime.now(EDMONTON)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=EDMONTON)
    return moment.astimezone(EDMONTON).date()


def current_month_key(today: Optional[date] = None) -> str:
    day = today or edmonton_today()
    return day.strftime("%Y-%m")


def parse_month(value: str) -> tuple[int, int]:
    text = (value or "").strip()
    if len(text) != 7 or text[4] != "-" or not text[:4].isdigit() or not text[5:].isdigit():
        raise ValueError("Month must look like 2026-10.")
    year, month = int(text[:4]), int(text[5:])
    if month < 1 or month > 12:
        raise ValueError("Month must look like 2026-10.")
    return year, month


def month_window(month_key: Optional[str], today: Optional[date] = None) -> MonthWindow:
    """Current month runs through today. A finished month is the full month."""
    day = today or edmonton_today()
    key = month_key or day.strftime("%Y-%m")
    year, month = parse_month(key)
    start = date(year, month, 1)
    last = date(year, month, monthrange(year, month)[1])
    current = day.replace(day=1)
    if start > current:
        raise ValueError("That month has not started.")
    if start == current:
        return MonthWindow(key, start, day, frozen=False)
    return MonthWindow(key, start, last, frozen=True)


def nightly_plan(today: date, frozen_months: set[str]) -> list[tuple[str, bool]]:
    """Previous month once it has closed, then the open month to date.

    A month already marked frozen is not computed again.
    """
    previous = (today.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
    current = today.strftime("%Y-%m")
    jobs: list[tuple[str, bool]] = []
    if previous not in frozen_months:
        jobs.append((previous, True))
    jobs.append((current, False))
    return jobs


def _as_utc(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _utc_now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


def format_as_of(value: Optional[datetime]) -> Optional[str]:
    moment = _as_utc(value)
    if moment is None:
        return None
    local = moment.astimezone(EDMONTON)
    hour = int(local.strftime("%I"))
    ampm = "a.m." if local.hour < 12 else "p.m."
    return f"As of {local.strftime('%b')} {local.day}, {local.year}, {hour}:{local.strftime('%M')} {ampm} MT"


def _snapshot_meta(window: MonthWindow, row: Optional[KpiSnapshot], today: date) -> dict:
    status = "missing"
    as_of = None
    error = None
    frozen = window.frozen
    if row is not None:
        status = row.status or "missing"
        as_of = _as_utc(row.generated_at)
        error = row.error
        if row.frozen:
            frozen = True
        if status == "running" and row.payload:
            status = "running"
    return {
        "month": window.month_key,
        "label": window.label,
        "period_start": window.start.isoformat(),
        "period_end": window.end.isoformat(),
        "frozen": frozen,
        "status": status,
        "as_of": as_of.replace(microsecond=0).isoformat().replace("+00:00", "Z") if as_of else None,
        "as_of_label": format_as_of(row.generated_at) if row is not None else None,
        "error": error,
        "current_month": today.strftime("%Y-%m"),
        "weekly": not frozen,
    }


def read_snapshot(db: Session, month_key: Optional[str] = None, today: Optional[date] = None) -> dict:
    """The dashboard payload. No Business Central call."""
    day = today or edmonton_today()
    window = month_window(month_key, day)
    row = db.query(KpiSnapshot).filter(KpiSnapshot.month_key == window.month_key).one_or_none()
    if row is not None and row.payload:
        body = dict(row.payload)
    else:
        body = {"sections": None, "coverage": [], "generated_at": None}
    body.pop("trace", None)
    body["snapshot"] = _snapshot_meta(window, row, day)
    body["cached"] = True
    return body


def _row_for(db: Session, window: MonthWindow) -> KpiSnapshot:
    row = db.query(KpiSnapshot).filter(KpiSnapshot.month_key == window.month_key).one_or_none()
    if row is None:
        row = KpiSnapshot(
            month_key=window.month_key,
            period_start=window.start,
            period_end=window.end,
            frozen=False,
            status="missing",
        )
        db.add(row)
        db.flush()
    return row


def claim(db: Session, window: MonthWindow) -> str:
    """Mark a month running. Returns 'running' when a fresh run already owns it."""
    row = _row_for(db, window)
    started = _as_utc(row.started_at)
    fresh = started is not None and datetime.now(timezone.utc) - started < STALE_AFTER
    if row.status == "running" and fresh:
        db.commit()
        return "running"
    row.status = "running"
    row.started_at = _utc_now_naive()
    row.error = None
    row.period_start = window.start
    row.period_end = window.end
    db.commit()
    return "claimed"


def compute_window(db: Session, window: MonthWindow, *, freeze: bool) -> KpiSnapshot:
    """Fetch Business Central and store the month. Caller must already have claimed it."""
    from app.services.kpi_dashboard_service import kpi_dashboard_service

    row = _row_for(db, window)
    try:
        payload, trace = kpi_dashboard_service.build_with_trace(
            db, window.start, window.end, today=window.end,
        )
    except Exception as exc:
        logger.exception("KPI snapshot failed for %s", window.month_key)
        row.status = "failed"
        row.error = "The snapshot could not be calculated."
        row.generated_at = row.generated_at
        db.commit()
        raise exc
    row.period_start = window.start
    row.period_end = window.end
    row.frozen = True if freeze or window.frozen else False
    row.status = "ready"
    row.error = None
    row.generated_at = _utc_now_naive()
    row.payload = payload
    row.trace = trace
    db.commit()
    logger.info(
        "KPI snapshot stored for %s (%s to %s, frozen=%s)",
        window.month_key, window.start.isoformat(), window.end.isoformat(), row.frozen,
    )
    return row


def run_nightly(db: Session, today: Optional[date] = None) -> list[str]:
    """Freeze last month when it is still open, then refresh the current month."""
    day = today or edmonton_today()
    frozen = {
        row.month_key
        for row in db.query(KpiSnapshot).filter(KpiSnapshot.frozen.is_(True)).all()
    }
    done = []
    for month_key, freeze in nightly_plan(day, frozen):
        window = month_window(month_key, day)
        if claim(db, window) == "running":
            logger.info("KPI snapshot for %s is already running", month_key)
            continue
        try:
            compute_window(db, window, freeze=freeze)
        except Exception:
            logger.exception("KPI nightly snapshot failed for %s", month_key)
            continue
        done.append(month_key)
    return done


def _compute_in_background(month_key: str, today: date, freeze: bool) -> None:
    db = SessionLocal()
    try:
        window = month_window(month_key, today)
        compute_window(db, window, freeze=freeze)
    except Exception:
        logger.exception("Background KPI recalculate failed for %s", month_key)
    finally:
        with _RUN_LOCK:
            _RUNNING.discard(month_key)
        db.close()


def request_recalculate(db: Session, month_key: Optional[str] = None, today: Optional[date] = None) -> dict:
    """Start a background recalculation. Returns immediately."""
    day = today or edmonton_today()
    window = month_window(month_key, day)
    state = claim(db, window)
    if state == "claimed":
        with _RUN_LOCK:
            already = window.month_key in _RUNNING
            if not already:
                _RUNNING.add(window.month_key)
                thread = threading.Thread(
                    target=_compute_in_background,
                    args=(window.month_key, day, window.frozen),
                    name=f"kpi-{window.month_key}",
                    daemon=True,
                )
                thread.start()
    return {"status": "running", "month": window.month_key}


def current_snapshot_ready(today: Optional[date] = None) -> bool:
    day = today or edmonton_today()
    db = SessionLocal()
    try:
        row = (
            db.query(KpiSnapshot)
            .filter(KpiSnapshot.month_key == day.strftime("%Y-%m"), KpiSnapshot.status == "ready")
            .one_or_none()
        )
        return row is not None and bool(row.payload)
    finally:
        db.close()
