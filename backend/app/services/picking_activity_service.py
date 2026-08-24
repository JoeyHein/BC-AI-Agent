"""
Picking Activity Service

Turns the raw BC picking/activity feed into operational metrics: per-employee
labour, downtime by reason, throughput, and live floor state.

Backed by the custom AL API pages 70134-70140 (source vendored at
bc-extension/picking-api/). Until that extension is deployed to the BC
environment every read returns empty and the service reports available=False.

KNOWN LIMITS OF THE UNDERLYING DATA - read before building on this:

  * Timing granularity is (employee x customer batch x activity type x date).
    The AL call sites write sourceNo=''/sourceLineNo=0, so time CANNOT be
    attributed to a sales order or line. Per-order cycle time is not derivable.
  * Managers/admins log NO time at all. PICKING activities only start when
    SessionEntryNo <> 0, and manager sign-ins get 0. Any labour total here
    excludes supervisors by design.
  * Loading is ONE activity row per customer regardless of crew size, so
    loading minutes cannot be split between loaders.
  * postedPickingSessions.pickingDurationMinutes is LABOUR-minutes summed across
    pickers. Wall-clock is pickingEnd - pickingStart. They differ whenever more
    than one picker works a batch.
  * Employee identity in the posted archive is a free-text NAME string, not
    employeeNo, so archive-to-employee joins are string matches. Only the
    activity log carries a real employeeNo.

The one exception to the "not attributable to an order" limits above:
pickingEntries (page 70141, backed by table "Picking Entry") IS keyed by
Sales Order No. + Sales Line No. — it's the live, line-by-line "what's still
outstanding to pick" checklist, not a time log. See get_remaining_to_pick().
"""

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from app.integrations.bc.client import bc_client

logger = logging.getLogger(__name__)

ACTIVITY_PICKING = "PICKING"
ACTIVITY_LOADING = "LOADING"

# Mirrors the hard-coded thresholds in DashboardDataBuilder.BuildAlerts so the
# portal and the warehouse wall display agree. If those AL constants change,
# change these too - there is no setup table backing them.
LONG_PAUSE_WARNING_MIN = 40
LONG_PAUSE_CRITICAL_MIN = 90


def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    """Parse a BC OData datetime. Returns None for null/zero-date sentinels."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
    # BC emits 0001-01-01 for an unset DateTime rather than null.
    if parsed.year <= 1:
        return None
    return parsed


def _parse_date(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    try:
        parsed = date.fromisoformat(value[:10])
    except (ValueError, TypeError):
        return None
    return None if parsed.year <= 1 else parsed


@dataclass
class EmployeeLabour:
    """Aggregated labour for one employee over the requested window."""
    employee_no: str
    employee_name: str = ""
    picking_minutes: float = 0.0
    loading_minutes: float = 0.0
    pause_minutes: float = 0.0
    activity_count: int = 0
    days_worked: int = 0

    @property
    def total_minutes(self) -> float:
        return self.picking_minutes + self.loading_minutes

    def to_dict(self) -> Dict[str, Any]:
        return {
            "employeeNo": self.employee_no,
            "employeeName": self.employee_name,
            "pickingMinutes": round(self.picking_minutes, 1),
            "loadingMinutes": round(self.loading_minutes, 1),
            "totalMinutes": round(self.total_minutes, 1),
            "pauseMinutes": round(self.pause_minutes, 1),
            "activityCount": self.activity_count,
            "daysWorked": self.days_worked,
            "avgMinutesPerDay": (
                round(self.total_minutes / self.days_worked, 1)
                if self.days_worked else 0.0
            ),
        }


@dataclass
class FloorState:
    """Point-in-time snapshot of the warehouse floor."""
    captured_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    available: bool = True
    active_pickers: List[Dict[str, Any]] = field(default_factory=list)
    queue: List[Dict[str, Any]] = field(default_factory=list)
    open_pauses: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "capturedAt": self.captured_at.isoformat(),
            "available": self.available,
            "summary": {
                "activePickers": len(self.active_pickers),
                "queuedOrders": len(self.queue),
                "openPauses": len(self.open_pauses),
            },
            "activePickers": self.active_pickers,
            "queue": self.queue,
            "openPauses": self.open_pauses,
        }


class PickingActivityService:
    """Read-only operational view over BC picking data."""

    def get_employee_labour(
        self,
        from_date: date,
        to_date: date,
        employee_no: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Per-employee labour and downtime for a date window.

        Excludes managers/admins - see module docstring. Only rows with a real
        employeeNo are counted; loading rows created without one are skipped
        rather than silently attributed to a blank employee.
        """
        logs = bc_client.get_activity_time_logs(
            from_date=from_date, to_date=to_date, employee_no=employee_no
        )
        if not logs:
            return []

        by_employee: Dict[str, EmployeeLabour] = {}
        days_seen: Dict[str, set] = defaultdict(set)

        for row in logs:
            emp_no = (row.get("employeeNo") or "").strip()
            if not emp_no:
                continue

            rec = by_employee.get(emp_no)
            if rec is None:
                rec = EmployeeLabour(
                    employee_no=emp_no,
                    employee_name=(row.get("employeeName") or "").strip(),
                )
                by_employee[emp_no] = rec

            # Prefer the stamped value; fall back to the live-computed one for
            # activities that are still running.
            minutes = row.get("netDurationMinutes") or 0
            if not minutes:
                minutes = row.get("elapsedMinutes") or 0
            minutes = float(minutes)

            if row.get("activityType") == ACTIVITY_LOADING:
                rec.loading_minutes += minutes
            else:
                rec.picking_minutes += minutes

            rec.pause_minutes += float(row.get("totalPauseMinutes") or 0)
            rec.activity_count += 1

            activity_date = _parse_date(row.get("activityDate"))
            if activity_date:
                days_seen[emp_no].add(activity_date)

        for emp_no, rec in by_employee.items():
            rec.days_worked = len(days_seen[emp_no])

        return [
            r.to_dict()
            for r in sorted(
                by_employee.values(), key=lambda x: x.total_minutes, reverse=True
            )
        ]

    def get_downtime_breakdown(
        self, from_date: date, to_date: date
    ) -> Dict[str, Any]:
        """Pause minutes grouped by reason code.

        Separating 'Equipment Issue' from 'Break'/'Lunch' is the operationally
        useful cut - the first is a fixable process problem, the others are not.
        """
        logs = bc_client.get_activity_time_logs(from_date=from_date, to_date=to_date)
        if not logs:
            return {
                "available": bc_client.picking_api_available(),
                "totalPauseMinutes": 0.0,
                "byReason": [],
            }

        entry_nos = [r["entryNo"] for r in logs if r.get("entryNo") is not None]
        entry_to_employee = {
            r.get("entryNo"): (r.get("employeeName") or "").strip() for r in logs
        }

        pauses: List[Dict[str, Any]] = []
        # OData $filter has a practical URL length limit, so chunk the id list.
        for i in range(0, len(entry_nos), 50):
            pauses.extend(
                bc_client.get_activity_pause_logs(
                    activity_entry_nos=entry_nos[i:i + 50]
                )
            )

        by_reason: Dict[str, Dict[str, Any]] = {}
        total = 0.0

        for p in pauses:
            reason = p.get("reason") or "Unknown"
            minutes = float(p.get("durationMinutes") or 0)

            # An open pause has no stamped duration - compute live age instead.
            if not minutes and not _parse_dt(p.get("pauseEnd")):
                started = _parse_dt(p.get("pauseStart"))
                if started:
                    minutes = (
                        datetime.now(timezone.utc) - started
                    ).total_seconds() / 60.0

            bucket = by_reason.setdefault(
                reason, {"reason": reason, "minutes": 0.0, "count": 0, "employees": set()}
            )
            bucket["minutes"] += minutes
            bucket["count"] += 1
            emp = entry_to_employee.get(p.get("activityEntryNo"))
            if emp:
                bucket["employees"].add(emp)
            total += minutes

        rows = [
            {
                "reason": b["reason"],
                "minutes": round(b["minutes"], 1),
                "count": b["count"],
                "employeeCount": len(b["employees"]),
                "pctOfTotal": round(b["minutes"] / total * 100, 1) if total else 0.0,
            }
            for b in by_reason.values()
        ]
        rows.sort(key=lambda r: r["minutes"], reverse=True)

        return {
            "available": True,
            "fromDate": from_date.isoformat(),
            "toDate": to_date.isoformat(),
            "totalPauseMinutes": round(total, 1),
            "byReason": rows,
        }

    def get_throughput(self, from_date: date, to_date: date) -> Dict[str, Any]:
        """Batch throughput from the posted archive.

        Reports labour-minutes and wall-clock minutes separately and explicitly,
        because the underlying field name ('Picking Duration (Min.)') reads like
        wall-clock and is not.
        """
        sessions = bc_client.get_posted_picking_sessions(
            from_date=from_date, to_date=to_date
        )
        if not sessions:
            return {
                "available": bc_client.picking_api_available(),
                "sessions": [],
                "totals": {},
            }

        rows: List[Dict[str, Any]] = []
        total_labour = 0.0
        total_orders = 0

        for s in sessions:
            start = _parse_dt(s.get("pickingStart"))
            end = _parse_dt(s.get("loadingEnd")) or _parse_dt(s.get("pickingEnd"))
            wall_clock = (
                (end - start).total_seconds() / 60.0 if start and end else None
            )

            labour = float(s.get("pickingDurationMinutes") or 0) + float(
                s.get("loadingDurationMinutes") or 0
            )
            orders = int(s.get("orderCount") or 0)

            total_labour += labour
            total_orders += orders

            rows.append({
                "entryNo": s.get("entryNo"),
                "postingDate": s.get("postingDate"),
                "customerNo": s.get("customerNo"),
                "customerName": s.get("customerName"),
                "shipmentNo": s.get("shipmentNo"),
                "pickers": s.get("pickers"),
                "orderCount": orders,
                "loadMethod": s.get("loadMethod"),
                "labourMinutes": round(labour, 1),
                "wallClockMinutes": round(wall_clock, 1) if wall_clock else None,
                "pauseMinutes": round(
                    float(s.get("pickingPauseMinutes") or 0)
                    + float(s.get("loadingPauseMinutes") or 0), 1
                ),
            })

        return {
            "available": True,
            "fromDate": from_date.isoformat(),
            "toDate": to_date.isoformat(),
            "totals": {
                "batches": len(rows),
                "orders": total_orders,
                "labourMinutes": round(total_labour, 1),
                "avgLabourMinutesPerOrder": (
                    round(total_labour / total_orders, 1) if total_orders else 0.0
                ),
            },
            "sessions": rows,
        }

    def get_floor_state(self) -> Dict[str, Any]:
        """Live snapshot: who is picking, what is queued, what is stalled."""
        state = FloorState()

        sessions = bc_client.get_picker_sessions(active_only=True)
        queue = bc_client.get_picking_queue()

        # An empty floor and an undeployed extension look identical in the data,
        # so ask the client which one it actually was.
        state.available = bc_client.picking_api_available()
        if not state.available:
            return state.to_dict()

        state.active_pickers = [
            {
                "entryNo": s.get("entryNo"),
                "employeeNo": s.get("employeeNo"),
                "employeeName": s.get("employeeName"),
                "customerNo": s.get("customerNo"),
                "startedAt": s.get("startedAt"),
            }
            for s in sessions
        ]

        state.queue = [
            {
                "salesOrderNo": q.get("salesOrderNo"),
                "customerNo": q.get("customerNo"),
                "customerName": q.get("customerName"),
                "status": q.get("status"),
                "shipmentDate": q.get("shipmentDate"),
                "pickingDate": q.get("pickingDate"),
                "pickerName": q.get("pickerName"),
            }
            for q in queue
        ]

        now = datetime.now(timezone.utc)
        for p in bc_client.get_activity_pause_logs(open_only=True):
            started = _parse_dt(p.get("pauseStart"))
            if not started:
                continue
            age = (now - started).total_seconds() / 60.0
            if age <= LONG_PAUSE_WARNING_MIN:
                continue
            state.open_pauses.append({
                "activityEntryNo": p.get("activityEntryNo"),
                "reason": p.get("reason"),
                "pauseStart": p.get("pauseStart"),
                "ageMinutes": round(age, 1),
                "severity": (
                    "critical" if age > LONG_PAUSE_CRITICAL_MIN else "warning"
                ),
            })

        state.open_pauses.sort(key=lambda x: x["ageMinutes"], reverse=True)
        return state.to_dict()

    def get_remaining_to_pick(
        self, so_numbers: Optional[List[str]] = None
    ) -> Dict[str, Dict[str, Any]]:
        """Live remaining-to-pick summary per sales order, from pickingEntries
        (page 70141) — the only picking-extension table attributed to a real
        sales order/line (see module docstring: activity TIME logs are NOT
        order-attributable, this is a different table).

        remaining = outstandingQuantity ("Order Qty", despite the field name)
        minus qtyPicked. Comment lines and fully-picked lines are excluded.

        Returns {} both when nothing is outstanding AND when the extension
        isn't deployed — callers that need to tell those apart should check
        bc_client.picking_api_available() themselves after calling this.
        """
        entries = bc_client.get_picking_entries()
        if not entries:
            return {}

        by_so: Dict[str, Dict[str, Any]] = {}
        for e in entries:
            so_no = e.get("salesOrderNo")
            if not so_no or (so_numbers is not None and so_no not in so_numbers):
                continue
            if e.get("isCommentLine"):
                continue
            remaining = (e.get("outstandingQuantity") or 0) - (e.get("qtyPicked") or 0)
            if remaining <= 0:
                continue
            bucket = by_so.setdefault(so_no, {"lines_remaining": 0, "qty_remaining": 0.0, "items": []})
            bucket["lines_remaining"] += 1
            bucket["qty_remaining"] += remaining
            bucket["items"].append({
                "itemNo": e.get("itemNo"),
                "description": e.get("description"),
                "remaining": remaining,
                "unitOfMeasureCode": e.get("unitOfMeasureCode"),
            })

        for bucket in by_so.values():
            bucket["qty_remaining"] = round(bucket["qty_remaining"], 2)
        return by_so

    def get_weekly_summary(self, weeks_back: int = 4) -> Dict[str, Any]:
        """Labour and throughput for the trailing N weeks.

        Built from postedPickingSessions rather than the AL Dashboard Week Day
        table - that table's Pending Count reads Picking Selection, whose rows
        are deleted on post, so it is structurally always 0 for past days and is
        not a valid historical series.
        """
        today = date.today()
        from_date = today - timedelta(weeks=weeks_back)

        throughput = self.get_throughput(from_date, today)
        if not throughput.get("available"):
            return {"available": False, "weeks": []}
        if not throughput.get("sessions"):
            return {"available": True, "weeks": []}

        by_week: Dict[date, Dict[str, Any]] = {}
        for s in throughput["sessions"]:
            posting = _parse_date(s.get("postingDate"))
            if not posting:
                continue
            week_start = posting - timedelta(days=posting.weekday())
            bucket = by_week.setdefault(
                week_start,
                {
                    "weekStarting": week_start.isoformat(),
                    "batches": 0,
                    "orders": 0,
                    "labourMinutes": 0.0,
                },
            )
            bucket["batches"] += 1
            bucket["orders"] += s.get("orderCount") or 0
            bucket["labourMinutes"] += s.get("labourMinutes") or 0.0

        weeks = sorted(by_week.values(), key=lambda w: w["weekStarting"])
        for w in weeks:
            w["labourMinutes"] = round(w["labourMinutes"], 1)
            w["avgLabourMinutesPerOrder"] = (
                round(w["labourMinutes"] / w["orders"], 1) if w["orders"] else 0.0
            )

        return {"available": True, "weeks": weeks}


picking_activity_service = PickingActivityService()
