"""Upwardor $500K plan: published baseline, reforecast, and staff access."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.api import auth as auth_api
from app.api.staff_permission_middleware import staff_permission_middleware
from app.api.upwardor_plan import router as upwardor_router
from app.db.database import get_db
from app.db.models import AppSettings, User, UserRole
from app.services import staff_service_keys_service as staff_keys
from app.services.auth_service import AuthService
from app.services.staff_permissions import permission_for
from app.services.upwardor_plan import (
    EDMONTON,
    GNB_INVOICE_AMOUNT,
    OPENING_BALANCE,
    PLAN_CHRISTMAS,
    PLAN_INVOICES_TOTAL,
    PLAN_PAYMENTS_TOTAL,
    PLAN_WEEKS,
    STATUS_QUO_CHRISTMAS,
    TARGET,
    build_forecast,
    merge_actuals,
    resolve_lever_choices,
    week_state,
)
from app.services import upwardor_plan_service as plan_service
from app.services.upwardor_plan_service import empty_snapshot

NOON = datetime(2026, 11, 6, 12, 0, tzinfo=EDMONTON)
WEEK_CLOSED = datetime(2026, 11, 10, 0, 0, tzinfo=EDMONTON)
LEVERS = {
    "gnb_january": {"status": "in_plan", "source": "baseline", "note": ""},
    "return_credit": {"status": "planned", "source": "baseline", "note": ""},
    "stock_po_holds": {"status": "not_started", "source": "baseline", "note": ""},
    "dec_buy_cap_note": "",
}


def _forecast(moment, actuals=None, levers=None, **kwargs):
    return build_forecast(moment, actuals or {}, levers or LEVERS, **kwargs)


def _week(report, iso):
    return next(row for row in report["weeks"] if row["week_of"] == iso)


class TestBaseline:
    def test_published_schedule_and_totals(self):
        assert PLAN_WEEKS[0]["plan_end"] == 851639
        assert PLAN_WEEKS[0]["status_quo_end"] == 909922
        assert PLAN_CHRISTMAS == 570328
        assert STATUS_QUO_CHRISTMAS == 961100
        assert PLAN_PAYMENTS_TOTAL == 428157
        assert PLAN_INVOICES_TOTAL == 246978
        assert PLAN_WEEKS[3]["invoices"] == GNB_INVOICE_AMOUNT
        assert PLAN_WEEKS[3]["credits"] == 79901

    def test_no_actuals_stays_on_the_published_plan(self):
        report = _forecast(NOON)
        assert report["status"] == "on_track"
        assert report["live_christmas"] == PLAN_CHRISTMAS
        assert report["stretch_christmas"] == PLAN_CHRISTMAS
        assert report["current_balance"] == OPENING_BALANCE
        assert report["current_balance_source"] == "statement_nov_3"
        assert report["gap_to_target"] == OPENING_BALANCE - TARGET
        assert report["invoice_target_reduction"] == 0
        assert report["ahead_on_both"] is False
        assert [row["live_end"] for row in report["weeks"]] == [row["plan_end"] for row in report["weeks"]]
        assert report["status_vs_target"] == "above"

    def test_week_starts_monday_edmonton(self):
        late_sunday = datetime(2026, 11, 9, 23, 59, tzinfo=EDMONTON)
        monday = datetime(2026, 11, 10, 0, 0, tzinfo=EDMONTON)
        assert week_state(PLAN_WEEKS[0]["week_of"], late_sunday) == "open"
        assert week_state(PLAN_WEEKS[0]["week_of"], monday) == "closed"
        assert week_state(PLAN_WEEKS[1]["week_of"], monday) == "open"
        # UTC-6, not a fall-back to UTC-7. 06:00 UTC is still Sunday evening in Edmonton.
        utc_monday_morning = datetime(2026, 11, 9, 6, 30, tzinfo=timezone.utc)
        assert week_state(PLAN_WEEKS[0]["week_of"], utc_monday_morning) == "open"


class TestReforecast:
    def test_lower_purchasing_and_higher_payments_are_ahead_once(self):
        actuals = {
            "2026-11-03": {"invoices": 70664, "payments": 80431, "credits": 0},
        }
        report = _forecast(WEEK_CLOSED, actuals)
        week = _week(report, "2026-11-03")
        assert week["hit"] == "ahead"
        assert week["variance"] == -30000
        assert report["ahead_on_both"] is True
        assert report["bought_less_than_plan"] is True
        assert report["paid_more_than_plan"] is True
        assert report["status"] == "ahead"
        assert report["live_christmas"] == PLAN_CHRISTMAS - 30000
        assert report["invoice_target_reduction"] == 20000
        assert report["targets_auto_reduced"] is True
        # The $20k purchasing save is in the balance. It is not also cut from Christmas.
        assert report["live_christmas"] != PLAN_CHRISTMAS - 50000
        reduced = [row for row in report["weeks"] if row["target_auto_reduced"]]
        assert reduced
        assert sum(row["planned_invoices"] - row["adjusted_invoice_target"] for row in report["weeks"] if row["state"] != "closed") == 20000

    def test_open_week_below_pace_improves_christmas_without_counting_payment_timing(self):
        actuals = {
            "2026-11-03": {"invoices": 20000, "payments": 50000, "credits": 0},
        }
        report = _forecast(NOON, actuals)
        assert report["ahead_on_both"] is True
        assert report["status"] == "ahead"
        assert report["this_week"]["pace_shortfall"] == 25332
        assert report["this_week"]["invoice_forecast"] == 65332
        assert report["this_week"]["payment_forecast"] == 70431
        assert report["live_christmas"] == PLAN_CHRISTMAS - 25332
        assert "higher" in report["reforecast_note"]
        assert "lower" in report["reforecast_note"]

    def test_payments_above_the_full_week_plan_stay_in_the_forecast(self):
        actuals = {
            "2026-11-03": {"invoices": 20000, "payments": 80431, "credits": 0},
        }
        report = _forecast(NOON, actuals)
        assert report["live_christmas"] == PLAN_CHRISTMAS - 25332 - 10000
        assert report["ahead_on_both"] is True

    def test_buying_more_than_plan_is_behind_and_does_not_raise_future_targets(self):
        actuals = {
            "2026-11-03": {"invoices": 100664, "payments": 70431, "credits": 0},
        }
        report = _forecast(WEEK_CLOSED, actuals)
        assert report["status"] == "behind"
        assert report["live_christmas"] == PLAN_CHRISTMAS + 10000
        assert report["invoice_target_reduction"] == 0
        assert _week(report, "2026-11-03")["hit"] == "miss"

    def test_unknown_actuals_are_not_zeros(self):
        report = _forecast(WEEK_CLOSED, {})
        assert report["live_christmas"] == PLAN_CHRISTMAS
        assert report["status"] == "on_track"
        assert _week(report, "2026-11-03")["hit"] == "pending"
        assert _week(report, "2026-11-03")["actual_invoices"] is None

    def test_monday_morning_does_not_call_an_empty_week_ahead(self):
        monday = datetime(2026, 11, 3, 12, 0, tzinfo=EDMONTON)
        actuals = {"2026-11-03": {"invoices": 0, "payments": 0, "credits": 0}}
        report = _forecast(monday, actuals)
        assert report["status"] == "on_track"
        assert report["live_christmas"] == PLAN_CHRISTMAS
        assert report["ahead_on_both"] is False

    def test_gnb_move_lands_near_493k(self):
        levers = {
            **LEVERS,
            "gnb_january": {"status": "moved", "source": "staff", "note": ""},
        }
        report = _forecast(NOON, {}, levers)
        assert report["live_christmas"] == PLAN_CHRISTMAS - GNB_INVOICE_AMOUNT
        assert report["live_christmas"] == 493293
        assert report["status"] == "ahead"
        assert report["status_vs_target"] == "under"
        assert _week(report, "2026-11-24")["adjusted_invoice_target"] == 0
        assert report["ahead_on_both"] is False

    def test_missed_return_credit_worsens_christmas(self):
        levers = {
            **LEVERS,
            "return_credit": {"status": "missed", "source": "staff", "note": ""},
        }
        report = _forecast(NOON, {}, levers)
        assert report["live_christmas"] == PLAN_CHRISTMAS + 60000
        assert report["status"] == "behind"

    def test_chart_carries_plan_status_quo_target_and_live(self):
        report = _forecast(NOON)
        point = report["chart"][0]
        assert point["plan"] == 851639
        assert point["status_quo"] == 909922
        assert point["target"] == TARGET
        assert point["live"] == 851639
        assert point["actual"] == OPENING_BALANCE
        assert report["chart"][-1]["live"] == PLAN_CHRISTMAS
        assert report["chart"][-1]["actual"] is None


class TestActualsMerge:
    def test_balance_implies_this_weeks_payments_when_the_ledger_is_missing(self):
        bc = {
            "2026-11-03": {"invoices": 20000, "invoices_source": "business_central"},
        }
        merged = merge_actuals(bc, {}, balance=811405, as_of=NOON)
        row = merged["2026-11-03"]
        assert row["payments"] == 40000
        assert row["payments_source"] == "derived_from_balance"
        report = _forecast(NOON, merged, balance=811405, balance_source="business_central")
        assert report["current_balance"] == 811405
        assert report["current_balance_source"] == "business_central"

    def test_staff_override_covers_business_central(self):
        bc = {"2026-11-03": {"invoices": 1000, "invoices_source": "business_central"}}
        overrides = {"weeks": {"2026-11-03": {"invoices": 5000}}}
        merged = merge_actuals(bc, overrides, balance=None, as_of=NOON)
        assert merged["2026-11-03"]["invoices"] == 5000
        assert merged["2026-11-03"]["invoices_source"] == "staff_override"

    def test_january_receipt_date_moves_the_gnb_lever(self):
        choices = resolve_lever_choices(
            {},
            [{"number": "PO-001066", "requested_receipt_date": "2027-01-06"}],
            {},
            NOON,
        )
        assert choices["gnb_january"]["status"] == "moved"
        assert choices["gnb_january"]["source"] == "business_central"

    def test_live_balance_already_includes_payments_so_they_are_not_subtracted_again(self):
        # Nov 3 statement 831,405, before that day's payment.
        # Posted since then: 30,032.41 (Nov 3) + 7,000 (Nov 6) = 37,032.41,
        # and 1,161.45 of invoices. 831,405 + 1,161.45 - 37,032.41 = 795,534.04.
        # Whole dollars: 831,405 + 1,161 - 795,534 = 37,032.
        merged = merge_actuals(
            {"2026-11-03": {"invoices": 1161.45, "invoices_source": "business_central"}},
            {},
            balance=795534.04,
            as_of=NOON,
        )
        assert merged["2026-11-03"]["payments"] == 37032
        assert merged["2026-11-03"]["payments_source"] == "derived_from_balance"
        report = _forecast(
            NOON,
            merged,
            balance=795534.04,
            balance_source="business_central",
            balance_as_of="2026-11-09T14:40:00-06:00",
        )
        assert report["current_balance"] == 795534
        assert report["current_balance_source"] == "business_central"
        assert report["balance_as_of"] == "2026-11-09T14:40:00-06:00"
        assert report["gap_to_target"] == 795534 - TARGET
        assert report["current_balance"] != OPENING_BALANCE - 37032
        assert _week(report, "2026-11-03")["actual_payments"] == 37032
        actual = next(point for point in report["chart"] if point["week_of"] == "2026-11-03")
        assert actual["actual"] == 795534

    def test_ledger_payments_are_kept_once_when_the_balance_is_live(self):
        merged = merge_actuals(
            {
                "2026-11-03": {
                    "invoices": 1161.45,
                    "invoices_source": "business_central",
                    "payments": 37032.41,
                    "payments_source": "business_central_vendor_ledger",
                },
            },
            {},
            balance=795534.04,
            as_of=NOON,
        )
        assert merged["2026-11-03"]["payments"] == 37032
        assert merged["2026-11-03"]["payments_source"] == "business_central_vendor_ledger"
        report = _forecast(NOON, merged, balance=795534.04, balance_source="business_central")
        assert report["current_balance"] == 795534
        assert _week(report, "2026-11-03")["actual_payments"] == 37032

    def test_a_second_open_week_is_not_guessed_from_the_balance(self):
        later = datetime(2026, 11, 12, 12, 0, tzinfo=EDMONTON)
        merged = merge_actuals(
            {"2026-11-03": {"invoices": 1161, "invoices_source": "business_central"}},
            {},
            balance=795534,
            as_of=later,
        )
        assert merged["2026-11-03"]["payments"] is None
        report = _forecast(later, merged, balance=795534, balance_source="business_central")
        assert report["current_balance"] == 795534
        assert report["current_balance_source"] == "business_central"
        assert _week(report, "2026-11-03")["actual_payments"] is None

    def test_statement_fallback_names_the_business_central_failure(self):
        reason = "Vendor lookup failed: HTTP 400: Could not find a property named 'balanceDue'"
        report = _forecast(NOON, errors=[reason])
        assert report["current_balance"] == OPENING_BALANCE
        assert report["current_balance_source"] == "statement_nov_3"
        assert report["balance_as_of"] is None
        notes = " ".join(report["sources"]["notes"])
        assert "Nov 3 statement opening" in notes
        assert "did not return the Upwardor balance" in notes
        assert "balance due" not in notes.lower()
        assert reason in report["sources"]["errors"]

    def test_staff_can_keep_gnb_in_the_november_plan(self):
        choices = resolve_lever_choices(
            {"levers": {"gnb_january": {"status": "in_plan"}}},
            [{"number": "PO-001066", "requested_receipt_date": "2027-01-06"}],
            {},
            NOON,
        )
        assert choices["gnb_january"]["status"] == "in_plan"
        assert choices["gnb_january"]["source"] == "staff"


class TestVendorBalanceRead:
    def test_postings_land_on_the_published_week_not_calendar_monday(self):
        assert plan_service._plan_week_key(datetime(2026, 11, 3).date()) == "2026-11-03"
        assert plan_service._plan_week_key(datetime(2026, 11, 6).date()) == "2026-11-03"
        assert plan_service._plan_week_key(datetime(2026, 11, 9).date()) == "2026-11-03"
        assert plan_service._plan_week_key(datetime(2026, 11, 10).date()) == "2026-11-10"
        assert plan_service._plan_week_key(datetime(2026, 11, 2).date()) is None
    def test_snapshot_reads_balance_and_does_not_select_balance_due(self, monkeypatch):
        calls = []

        def fake_odata(relative):
            calls.append(relative)
            if relative.startswith("vendors"):
                assert "balanceDue" not in relative
                assert "balance" in relative
                if "number eq 'UPW'" in relative:
                    return {"value": [{
                        "number": "UPW",
                        "displayName": "Upwardor",
                        "balanceDue": 1,
                        "balance": 795534.04,
                    }]}
                return {"value": []}
            if relative.startswith("purchaseInvoices"):
                return {"value": [{
                    "number": "PI-1",
                    "postingDate": "2026-11-04",
                    "vendorNumber": "UPW",
                    "totalAmountIncludingTax": 1161.45,
                    "status": "Open",
                }]}
            if relative.startswith("purchaseOrders"):
                return {"value": []}
            raise AssertionError(relative)

        monkeypatch.setattr(plan_service, "_configured", lambda: True)
        monkeypatch.setattr(plan_service, "_odata_get", fake_odata)
        monkeypatch.setattr(plan_service, "_vendor_ledger", lambda vendor_no: None)
        plan_service.clear_snapshot_cache()
        try:
            snapshot = plan_service._fetch_bc_snapshot()
            report = plan_service.build_report(None, as_of=NOON, snapshot=snapshot)
        finally:
            plan_service.clear_snapshot_cache()

        assert calls
        assert all("balanceDue" not in call for call in calls)
        assert snapshot["balance"] == 795534
        assert snapshot["balance_source"] == "business_central"
        assert snapshot["balance_as_of"]
        assert snapshot["errors"] == []
        assert report["current_balance"] == 795534
        assert report["current_balance_source"] == "business_central"
        assert report["balance_as_of"] == snapshot["balance_as_of"]
        week = next(row for row in report["weeks"] if row["week_of"] == "2026-11-03")
        assert week["actual_payments"] == 37032
        assert week["payment_source"] == "derived_from_balance"
        assert not any("Nov 3 statement opening" in note for note in report["sources"]["notes"])

    def test_posted_payments_are_not_derived_on_top_of_the_live_balance(self, monkeypatch):
        def fake_odata(relative):
            if relative.startswith("vendors"):
                return {"value": [{"number": "UPW", "displayName": "Upwardor", "balance": 795534.04}]}
            if relative.startswith("purchaseInvoices"):
                return {"value": [{
                    "postingDate": "2026-11-04",
                    "totalAmountIncludingTax": 1161.45,
                    "status": "Open",
                }]}
            if relative.startswith("purchaseOrders"):
                return {"value": []}
            raise AssertionError(relative)

        def fake_ledger(vendor_no):
            assert vendor_no == "UPW"
            return [
                {"postingDate": "2026-11-03", "documentType": "Payment", "amount": -30032.41},
                {"postingDate": "2026-11-06", "documentType": "Payment", "amount": -7000},
            ]

        monkeypatch.setattr(plan_service, "_configured", lambda: True)
        monkeypatch.setattr(plan_service, "_odata_get", fake_odata)
        monkeypatch.setattr(plan_service, "_vendor_ledger", fake_ledger)
        plan_service.clear_snapshot_cache()
        try:
            snapshot = plan_service._fetch_bc_snapshot()
            report = plan_service.build_report(None, as_of=NOON, snapshot=snapshot)
        finally:
            plan_service.clear_snapshot_cache()

        week = snapshot["weeks"]["2026-11-03"]
        assert "2026-11-02" not in snapshot["weeks"]
        assert round(week["payments"], 2) == 37032.41
        assert week["payments_source"] == "business_central_vendor_ledger"
        assert round(week["invoices"], 2) == 1161.45
        assert report["current_balance"] == 795534
        shown = next(row for row in report["weeks"] if row["week_of"] == "2026-11-03")
        assert shown["actual_payments"] == 37032
        assert shown["payment_source"] == "business_central_vendor_ledger"

    def test_vendor_outage_uses_the_statement_and_records_the_reason(self, monkeypatch, caplog):
        def fake_odata(relative):
            if relative.startswith("vendors"):
                raise RuntimeError("HTTP 400: Could not find a property named 'balanceDue'")
            raise AssertionError(relative)

        monkeypatch.setattr(plan_service, "_configured", lambda: True)
        monkeypatch.setattr(plan_service, "_odata_get", fake_odata)
        plan_service.clear_snapshot_cache()
        try:
            with caplog.at_level("WARNING"):
                snapshot = plan_service._fetch_bc_snapshot()
            report = plan_service.build_report(None, as_of=NOON, snapshot=snapshot)
        finally:
            plan_service.clear_snapshot_cache()

        assert snapshot["balance"] is None
        assert snapshot["balance_source"] == "unavailable"
        assert snapshot["balance_as_of"] is None
        assert any("balanceDue" in err for err in snapshot["errors"])
        assert any("balanceDue" in rec.message for rec in caplog.records)
        assert report["current_balance"] == OPENING_BALANCE
        assert report["current_balance_source"] == "statement_nov_3"
        assert report["balance_as_of"] is None
        assert any("balanceDue" in err for err in report["sources"]["errors"])
        assert any("Nov 3 statement opening" in note for note in report["sources"]["notes"])

    def test_vendor_without_a_balance_is_not_silent(self, monkeypatch, caplog):
        def fake_odata(relative):
            if relative.startswith("vendors"):
                return {"value": [{"number": "UPW", "displayName": "Upwardor"}]}
            if relative.startswith("purchaseInvoices"):
                raise RuntimeError("HTTP 503: purchase invoices unavailable")
            if relative.startswith("purchaseOrders"):
                return {"value": []}
            raise AssertionError(relative)

        monkeypatch.setattr(plan_service, "_configured", lambda: True)
        monkeypatch.setattr(plan_service, "_odata_get", fake_odata)
        monkeypatch.setattr(plan_service, "_vendor_ledger", lambda vendor_no: None)
        plan_service.clear_snapshot_cache()
        try:
            with caplog.at_level("WARNING"):
                snapshot = plan_service._fetch_bc_snapshot()
            report = plan_service.build_report(None, as_of=NOON, snapshot=snapshot)
        finally:
            plan_service.clear_snapshot_cache()

        assert snapshot["balance"] is None
        assert any("did not include a balance" in err for err in snapshot["errors"])
        assert any("purchase invoices" in err.lower() for err in snapshot["errors"])
        assert any("did not include a balance" in rec.message for rec in caplog.records)
        assert report["current_balance_source"] == "statement_nov_3"
        assert any("did not include a balance" in err for err in report["sources"]["errors"])
        assert any("Nov 3 statement opening" in note for note in report["sources"]["notes"])


class TestAccess:
    def test_page_matches_the_business_audience_and_writes_stay_admin(self):
        assert permission_for("GET", "/api/metrics/upwardor-plan") == (
            "any",
            "users.manage",
            "quotes.edit",
            "sales_orders.edit",
            "purchase_orders.view",
            "sales_orders.view",
        )
        assert permission_for("PATCH", "/api/metrics/upwardor-plan/levers") == ("perm", "users.manage")
        assert permission_for("PATCH", "/api/metrics/upwardor-plan/actuals") == ("perm", "users.manage")

    def test_purchasing_can_read_warehouse_cannot_and_admin_can_record(self, monkeypatch):
        engine = create_engine(
            "sqlite://",
            future=True,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        User.__table__.create(engine, checkfirst=True)
        AppSettings.__table__.create(engine, checkfirst=True)
        Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
        db = Session()
        db.add(_user("joey@opendc.ca", UserRole.ADMIN))
        db.add(_user("buyer@opendc.ca", UserRole.PURCHASING))
        db.add(_user("floor@opendc.ca", UserRole.WAREHOUSE))
        db.commit()
        db.close()

        def new_session():
            return Session()

        monkeypatch.setattr(staff_keys, "new_session", new_session)
        monkeypatch.setattr(
            "app.services.upwardor_plan_service.fetch_bc_snapshot",
            lambda: empty_snapshot("Business Central is not configured in this test."),
        )

        def _override():
            scoped = Session()
            try:
                yield scoped
            finally:
                scoped.close()

        app = FastAPI()
        app.middleware("http")(staff_permission_middleware)
        app.include_router(auth_api.router)
        app.include_router(upwardor_router)
        app.dependency_overrides[get_db] = _override
        app.dependency_overrides[auth_api.get_db] = _override
        client = TestClient(app)

        def token(email):
            response = client.post("/api/auth/login", json={"email": email, "password": "test123"})
            assert response.status_code == 200, response.text
            return response.json()["access_token"]

        buyer = token("buyer@opendc.ca")
        read = client.get("/api/metrics/upwardor-plan", headers={"Authorization": f"Bearer {buyer}"})
        assert read.status_code == 200, read.text
        body = read.json()
        assert body["plan_christmas"] == 570328
        assert body["live_christmas"] == 570328
        assert body["can_edit"] is False
        assert body["sources"]["plan"] == "baseline_nov_2026"
        assert body["current_balance_source"] == "statement_nov_3"
        assert body["sources"]["errors"]
        assert len(body["weeks"]) == 8
        assert len(body["levers"]) == 4

        floor = token("floor@opendc.ca")
        refused = client.get("/api/metrics/upwardor-plan", headers={"Authorization": f"Bearer {floor}"})
        assert refused.status_code == 403

        buyer_write = client.patch(
            "/api/metrics/upwardor-plan/levers",
            headers={"Authorization": f"Bearer {buyer}"},
            json={"id": "gnb_january", "status": "moved"},
        )
        assert buyer_write.status_code == 403

        admin = token("joey@opendc.ca")
        moved = client.patch(
            "/api/metrics/upwardor-plan/levers",
            headers={"Authorization": f"Bearer {admin}"},
            json={"id": "gnb_january", "status": "moved", "note": "Receipt dated January"},
        )
        assert moved.status_code == 200, moved.text
        assert moved.json()["live_christmas"] == 493293
        assert moved.json()["can_edit"] is True
        gnb = next(lever for lever in moved.json()["levers"] if lever["id"] == "gnb_january")
        assert gnb["status"] == "moved"
        assert gnb["note"] == "Receipt dated January"

        recorded = client.patch(
            "/api/metrics/upwardor-plan/actuals",
            headers={"Authorization": f"Bearer {admin}"},
            json={"week_of": "2026-11-03", "invoices": 20000, "payments": 80431},
        )
        assert recorded.status_code == 200, recorded.text
        week = next(row for row in recorded.json()["weeks"] if row["week_of"] == "2026-11-03")
        assert week["actual_invoices"] == 20000
        assert week["actual_payments"] == 80431
        assert week["invoice_source"] == "staff_override"
        assert recorded.json()["ahead_on_both"] is True
        assert recorded.json()["live_christmas"] < 493293


def _user(email, role):
    return User(
        email=email,
        password_hash=AuthService.get_password_hash("test123"),
        name=email.split("@")[0],
        role=role,
        is_active=True,
        user_type="INTERNAL",
        invite_pending=False,
    )
