"""Monthly KPI snapshots: the page reads the database, the job writes it."""
from __future__ import annotations

import os
import sys
from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.api import kpi_dashboard as kpi_api
from app.api.auth import get_current_user
from app.api.staff_principal import require_staff
from app.db.database import get_db
from app.db.models import KpiSnapshot, UserRole
from app.services import kpi_snapshot_service as snap
from app.services.kpi_validation import collect_trace, format_validation_report

TODAY = date(2026, 10, 14)


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    KpiSnapshot.__table__.create(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


def _fake_build(amount=12):
    def build(db, start, end, today=None):
        return (
            {
                "sections": {"sales": {"range_total": {"amount": amount}}},
                "coverage": [],
                "generated_at": "2026-10-14T06:10:00Z",
            },
            {"kpis": {"sales": amount}, "sales_invoices": [{"number": "PS-1", "posting_date": str(start), "amount": amount}]},
        )
    return build


class TestMonthWindows:
    def test_current_month_runs_through_today_and_a_closed_month_is_the_full_month(self):
        current = snap.month_window("2026-10", TODAY)
        assert current.start == date(2026, 10, 1)
        assert current.end == TODAY
        assert current.frozen is False
        closed = snap.month_window("2026-09", TODAY)
        assert closed.start == date(2026, 9, 1)
        assert closed.end == date(2026, 9, 30)
        assert closed.frozen is True

    def test_a_future_month_is_rejected(self):
        with pytest.raises(ValueError):
            snap.month_window("2026-11", TODAY)
        with pytest.raises(ValueError):
            snap.month_window("2026-13", TODAY)

    def test_nightly_plan_freezes_last_month_once_and_always_refreshes_this_month(self):
        assert snap.nightly_plan(TODAY, set()) == [("2026-09", True), ("2026-10", False)]
        assert snap.nightly_plan(TODAY, {"2026-09"}) == [("2026-10", False)]
        assert snap.nightly_plan(date(2026, 11, 1), set()) == [("2026-10", True), ("2026-11", False)]


class TestStoredSnapshot:
    def test_read_does_not_call_business_central(self, db, monkeypatch):
        def explode(*args, **kwargs):
            raise AssertionError("the page must not calculate live")

        monkeypatch.setattr(
            "app.services.kpi_dashboard_service.kpi_dashboard_service.build_with_trace",
            explode,
        )
        body = snap.read_snapshot(db, "2026-10", TODAY)
        assert body["snapshot"]["status"] == "missing"
        assert body["sections"] is None
        assert body["snapshot"]["as_of_label"] is None

    def test_nightly_freezes_last_month_and_refreshes_this_month(self, db, monkeypatch):
        calls = []

        def build(db, start, end, today=None):
            calls.append((start, end))
            return _fake_build()(db, start, end, today)

        monkeypatch.setattr(
            "app.services.kpi_dashboard_service.kpi_dashboard_service.build_with_trace",
            build,
        )
        first = snap.run_nightly(db, TODAY)
        assert first == ["2026-09", "2026-10"]
        september = db.query(KpiSnapshot).filter_by(month_key="2026-09").one()
        october = db.query(KpiSnapshot).filter_by(month_key="2026-10").one()
        assert september.frozen is True
        assert september.period_end == date(2026, 9, 30)
        assert september.status == "ready"
        assert october.frozen is False
        assert october.period_end == TODAY
        assert october.trace["sales_invoices"][0]["number"] == "PS-1"

        snap.run_nightly(db, TODAY)
        assert calls == [
            (date(2026, 9, 1), date(2026, 9, 30)),
            (date(2026, 10, 1), TODAY),
            (date(2026, 10, 1), TODAY),
        ]
        stored = snap.read_snapshot(db, "2026-09", TODAY)
        assert stored["sections"]["sales"]["range_total"]["amount"] == 12
        assert stored["snapshot"]["frozen"] is True
        assert stored["snapshot"]["as_of_label"].startswith("As of ")
        assert "trace" not in stored

    def test_recalculate_marks_the_month_running_and_returns_at_once(self, db, monkeypatch):
        started = {}

        class InlineThread:
            def __init__(self, target, args, **kwargs):
                started["args"] = args
            def start(self):
                started["started"] = True

        monkeypatch.setattr(snap.threading, "Thread", InlineThread)
        snap._RUNNING.clear()
        result = snap.request_recalculate(db, "2026-09", TODAY)
        assert result == {"status": "running", "month": "2026-09"}
        assert started["started"] is True
        assert started["args"][0] == "2026-09"
        assert started["args"][2] is True
        row = db.query(KpiSnapshot).filter_by(month_key="2026-09").one()
        assert row.status == "running"

    def test_as_of_uses_edmonton_time(self):
        label = snap.format_as_of(datetime(2026, 10, 15, 6, 10, tzinfo=timezone.utc))
        assert label == "As of Oct 15, 2026, 12:10 a.m. MT"


class TestValidationReport:
    def test_report_prints_the_kpi_and_the_document_numbers(self):
        bundle = {
            "invoices": [
                {"number": "PS-100", "posting_date": "2026-09-05", "amount": 40, "customer_name": "Abe"},
                {"number": "PS-OLD", "posting_date": "2026-08-01", "amount": 9, "customer_name": "Abe"},
            ],
            "sales_orders": [],
            "receipts": [],
            "purchase_invoices": [],
            "open_invoices": [{"number": "PS-OPEN", "due_date": "2026-08-01", "amount": 15, "status": "Open"}],
            "quotes": [{"number": "SQ-000010", "document_date": "2026-09-02", "amount": 80}],
            "shipments": [],
        }
        payload = {
            "sections": {
                "purchasing": {
                    "so_to_po": {
                        "average_days": 4.5,
                        "late_count": 1,
                        "pairs": [{
                            "sales_order": "SO-000101",
                            "purchase_order": "PO-000201",
                            "vendor_name": "Upwardor",
                            "days": 7,
                            "po_sent_date": "2026-09-08",
                        }],
                    },
                    "acknowledgements": {"average_days": 3, "vendors": []},
                    "unacknowledged": {"count": 0, "vendors": []},
                    "on_time": {"rate_pct": 100},
                },
                "sales": {
                    "range_total": {"amount": 40},
                    "month": {
                        "prior_from": "2026-08-01",
                        "prior_to": "2026-08-31",
                        "prior_amount": 9,
                        "prior_delta_pct": 344.4,
                        "year_ago_from": "2025-09-01",
                        "year_ago_to": "2025-09-30",
                        "year_ago_amount": 5,
                        "year_ago_delta_pct": 700,
                    },
                    "quotes": {"conversion_pct": 33.3, "open_quote_value": 80},
                },
                "financial": {
                    "margin": {"margin_pct": 20},
                    "po_variance": {"variance_amount": 0},
                    "ar": {"total": 15},
                    "backlog": {"amount": 0},
                },
                "operations": {
                    "order_to_ship": {"average_days": 3},
                    "inventory": {"value": 100, "below_reorder_count": 1, "below_reorder": [
                        {"item_number": "PN60", "on_hand": 2, "reorder_point": 6},
                    ]},
                    "freight": {"percent": 1.4},
                },
            }
        }
        trace = collect_trace(bundle, date(2026, 9, 1), date(2026, 9, 30), payload)
        text = format_validation_report(trace, month="September 2026", as_of="As of Oct 1, 2026, 12:10 a.m. MT")
        assert "PS-100" in text
        assert "PS-OLD" not in text
        assert "SO-000101" in text
        assert "PO-000201" in text
        assert "SQ-000010" in text
        assert "PS-OPEN" in text
        assert "PN60" in text
        assert "SO to PO days: 4.5" in text
        assert "Sales: $40.00" in text
        assert "Posted sales invoices (1)" in text


class TestRecalculateRoute:
    def _client(self, db, user):
        app = FastAPI()
        app.include_router(kpi_api.router)

        def _db():
            yield db

        app.dependency_overrides[get_db] = _db
        app.dependency_overrides[require_staff] = lambda: user
        app.dependency_overrides[get_current_user] = lambda: user
        return TestClient(app)

    def test_admin_recalculate_is_accepted_and_a_reviewer_is_refused(self, db, monkeypatch):
        class NoThread:
            def __init__(self, target, args, **kwargs):
                self.target = target
            def start(self):
                return None

        monkeypatch.setattr(snap.threading, "Thread", NoThread)
        snap._RUNNING.clear()
        admin = SimpleNamespace(role=UserRole.ADMIN, is_active=True)
        reviewer = SimpleNamespace(role=UserRole.REVIEWER, is_active=True)
        ok = self._client(db, admin).post("/api/kpi/recalculate?month=2026-10")
        assert ok.status_code == 200, ok.text
        assert ok.json()["status"] == "running"
        refused = self._client(db, reviewer).post("/api/kpi/recalculate?month=2026-10")
        assert refused.status_code == 403
