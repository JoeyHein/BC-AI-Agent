"""
Tests for PickingActivityService.

The BC picking extension is not deployed yet, so every test here mocks the
client. The point is to pin the aggregation semantics that are easy to get
wrong -- specifically labour-vs-wall-clock and the "empty vs not deployed"
distinction.
"""

from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.services.picking_activity_service import PickingActivityService


@pytest.fixture
def svc():
    return PickingActivityService()


FROM_DATE = date(2026, 7, 1)
TO_DATE = date(2026, 7, 31)


def _log(entry_no, emp_no, name, activity, net, pause=0.0, day="2026-07-15"):
    return {
        "entryNo": entry_no,
        "employeeNo": emp_no,
        "employeeName": name,
        "activityType": activity,
        "netDurationMinutes": net,
        "totalPauseMinutes": pause,
        "activityDate": day,
    }


class TestEmployeeLabour:
    def test_splits_picking_and_loading_per_employee(self, svc):
        logs = [
            _log(1, "343", "Ana Ruiz", "PICKING", 60),
            _log(2, "343", "Ana Ruiz", "LOADING", 30),
            _log(3, "362", "Sam Poon", "PICKING", 45),
        ]
        with patch("app.services.picking_activity_service.bc_client") as bc:
            bc.get_activity_time_logs.return_value = logs
            rows = svc.get_employee_labour(FROM_DATE, TO_DATE)

        assert [r["employeeNo"] for r in rows] == ["343", "362"]  # sorted by total
        ana = rows[0]
        assert ana["pickingMinutes"] == 60
        assert ana["loadingMinutes"] == 30
        assert ana["totalMinutes"] == 90

    def test_skips_rows_with_no_employee_no(self, svc):
        """Loading rows can be created without an employee. They must not be
        aggregated into a phantom blank employee."""
        logs = [
            _log(1, "343", "Ana Ruiz", "PICKING", 60),
            _log(2, "", "", "LOADING", 999),
        ]
        with patch("app.services.picking_activity_service.bc_client") as bc:
            bc.get_activity_time_logs.return_value = logs
            rows = svc.get_employee_labour(FROM_DATE, TO_DATE)

        assert len(rows) == 1
        assert rows[0]["employeeNo"] == "343"

    def test_falls_back_to_elapsed_for_running_activity(self, svc):
        """netDurationMinutes is not stamped until CompleteActivity."""
        running = _log(1, "343", "Ana Ruiz", "PICKING", 0)
        running["elapsedMinutes"] = 25
        with patch("app.services.picking_activity_service.bc_client") as bc:
            bc.get_activity_time_logs.return_value = [running]
            rows = svc.get_employee_labour(FROM_DATE, TO_DATE)

        assert rows[0]["pickingMinutes"] == 25

    def test_days_worked_counts_distinct_dates(self, svc):
        logs = [
            _log(1, "343", "Ana Ruiz", "PICKING", 60, day="2026-07-15"),
            _log(2, "343", "Ana Ruiz", "PICKING", 60, day="2026-07-15"),
            _log(3, "343", "Ana Ruiz", "PICKING", 60, day="2026-07-16"),
        ]
        with patch("app.services.picking_activity_service.bc_client") as bc:
            bc.get_activity_time_logs.return_value = logs
            rows = svc.get_employee_labour(FROM_DATE, TO_DATE)

        assert rows[0]["daysWorked"] == 2
        assert rows[0]["avgMinutesPerDay"] == 90


class TestThroughput:
    def test_reports_labour_and_wall_clock_separately(self, svc):
        """Two pickers x 30 min = 60 labour-minutes but 30 wall-clock minutes.
        Conflating these silently corrupts productivity metrics."""
        session = {
            "entryNo": 1,
            "postingDate": "2026-07-15",
            "customerNo": "C001",
            "pickingStart": "2026-07-15T09:00:00Z",
            "pickingEnd": "2026-07-15T09:30:00Z",
            "pickingDurationMinutes": 60,   # summed across 2 pickers
            "loadingDurationMinutes": 0,
            "orderCount": 3,
        }
        with patch("app.services.picking_activity_service.bc_client") as bc:
            bc.get_posted_picking_sessions.return_value = [session]
            result = svc.get_throughput(FROM_DATE, TO_DATE)

        row = result["sessions"][0]
        assert row["labourMinutes"] == 60
        assert row["wallClockMinutes"] == 30
        assert result["totals"]["avgLabourMinutesPerOrder"] == 20

    def test_wall_clock_none_when_timestamps_missing(self, svc):
        session = {
            "entryNo": 1,
            "postingDate": "2026-07-15",
            "pickingStart": "0001-01-01T00:00:00Z",
            "pickingEnd": None,
            "pickingDurationMinutes": 10,
            "orderCount": 1,
        }
        with patch("app.services.picking_activity_service.bc_client") as bc:
            bc.get_posted_picking_sessions.return_value = [session]
            result = svc.get_throughput(FROM_DATE, TO_DATE)

        assert result["sessions"][0]["wallClockMinutes"] is None


class TestDowntime:
    def test_groups_by_reason_and_computes_open_pause_live(self, svc):
        started = datetime.now(timezone.utc) - timedelta(minutes=20)
        pauses = [
            {"activityEntryNo": 1, "reason": "Lunch",
             "durationMinutes": 30, "pauseEnd": "2026-07-15T12:30:00Z"},
            {"activityEntryNo": 1, "reason": "Equipment Issue",
             "durationMinutes": 0, "pauseEnd": None,
             "pauseStart": started.isoformat()},
        ]
        with patch("app.services.picking_activity_service.bc_client") as bc:
            bc.get_activity_time_logs.return_value = [
                _log(1, "343", "Ana Ruiz", "PICKING", 60)
            ]
            bc.get_activity_pause_logs.return_value = pauses
            result = svc.get_downtime_breakdown(FROM_DATE, TO_DATE)

        by_reason = {r["reason"]: r for r in result["byReason"]}
        assert by_reason["Lunch"]["minutes"] == 30
        # Open pause gets a live age rather than being dropped as zero.
        assert 19 <= by_reason["Equipment Issue"]["minutes"] <= 21


class TestAvailabilitySignal:
    """Empty results and an undeployed extension must not look the same."""

    def test_empty_but_deployed_reports_available(self, svc):
        with patch("app.services.picking_activity_service.bc_client") as bc:
            bc.get_picker_sessions.return_value = []
            bc.get_picking_queue.return_value = []
            bc.get_activity_pause_logs.return_value = []
            bc.picking_api_available.return_value = True
            state = svc.get_floor_state()

        assert state["available"] is True
        assert state["summary"]["activePickers"] == 0

    def test_not_deployed_reports_unavailable(self, svc):
        with patch("app.services.picking_activity_service.bc_client") as bc:
            bc.get_picker_sessions.return_value = []
            bc.get_picking_queue.return_value = []
            bc.picking_api_available.return_value = False
            state = svc.get_floor_state()

        assert state["available"] is False

    def test_throughput_reports_unavailable_when_not_deployed(self, svc):
        with patch("app.services.picking_activity_service.bc_client") as bc:
            bc.get_posted_picking_sessions.return_value = []
            bc.picking_api_available.return_value = False
            assert svc.get_throughput(FROM_DATE, TO_DATE)["available"] is False


class TestFloorState:
    def test_only_surfaces_pauses_past_the_warning_threshold(self, svc):
        now = datetime.now(timezone.utc)
        pauses = [
            {"activityEntryNo": 1, "reason": "Break",
             "pauseStart": (now - timedelta(minutes=5)).isoformat()},
            {"activityEntryNo": 2, "reason": "Equipment Issue",
             "pauseStart": (now - timedelta(minutes=50)).isoformat()},
            {"activityEntryNo": 3, "reason": "Other",
             "pauseStart": (now - timedelta(minutes=120)).isoformat()},
        ]
        with patch("app.services.picking_activity_service.bc_client") as bc:
            bc.picking_api_available.return_value = True
            bc.get_picker_sessions.return_value = [
                {"entryNo": 9, "employeeNo": "343", "employeeName": "Ana Ruiz"}
            ]
            bc.get_picking_queue.return_value = []
            bc.get_activity_pause_logs.return_value = pauses
            state = svc.get_floor_state()

        # 5-minute pause is below the 40-minute threshold and is excluded.
        assert len(state["openPauses"]) == 2
        # Sorted oldest first, severity escalates past 90 minutes.
        assert state["openPauses"][0]["severity"] == "critical"
        assert state["openPauses"][1]["severity"] == "warning"
