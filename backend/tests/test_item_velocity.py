"""Tests for item velocity — the 3-month-consumable inventory signal."""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from app.services import item_velocity_service as mod
from app.services.item_velocity_service import (
    item_velocity_service as svc,
    _is_movement, _norm_entry_type, SLOW_MONTHS_SUPPLY,
)


class TestEntryClassification:
    def test_escaped_entry_type_normalises(self):
        assert _norm_entry_type("Negative_x0020_Adjmt_x002E_") == "negative adjmt."

    def test_consumption_and_sale_are_movement(self):
        assert _is_movement("Consumption", "PROD-1")
        assert _is_movement("Sale", "SI-1")

    def test_counts_and_corrections_are_not_movement(self):
        assert not _is_movement("Positive_x0020_Adjmt_x002E_", "ANNUAL_COUNT_2026")
        assert not _is_movement("Negative_x0020_Adjmt_x002E_", "COST CORR")

    def test_tagged_cut_counts_as_movement(self):
        assert _is_movement("Negative_x0020_Adjmt_x002E_", "CUT-001238")


class _FakeClient:
    company_id = "co"
    def __init__(self, entries):
        self._entries = entries
    def _make_request(self, method, endpoint):
        return {"value": self._entries}


def _entry(dt, etype, qty, doc="PROD-1"):
    return {"postingDate": dt, "entryType": etype, "quantity": qty, "documentNumber": doc}


class TestVelocity:
    def setup_method(self):
        svc._cache.clear()   # ledger cache is a singleton; isolate each case

    def _run(self, monkeypatch, entries, on_hand, today=date(2026, 7, 20)):
        monkeypatch.setattr(mod, "bc_client", _FakeClient(entries), raising=False)
        # bc_client is imported inside donor_velocity; patch at source module.
        import app.integrations.bc.client as bcmod
        monkeypatch.setattr(bcmod, "bc_client", _FakeClient(entries))
        return svc.donor_velocity({"SKU": on_hand}, months=12, today=today)["SKU"]

    def test_fast_mover_is_not_slow(self, monkeypatch):
        # 12 consumption entries of 10 over the year = 120/yr = 10/mo; 20 on hand = 2 months.
        entries = [_entry(f"2026-{m:02d}-05", "Consumption", -10) for m in range(1, 8)]
        entries += [_entry(f"2025-{m:02d}-05", "Consumption", -10) for m in range(8, 13)]
        v = self._run(monkeypatch, entries, on_hand=20)
        assert v["monthly_rate"] == pytest.approx(10.0, abs=0.5)
        assert v["months_supply"] <= SLOW_MONTHS_SUPPLY
        assert v["is_slow"] is False

    def test_high_months_supply_is_slow(self, monkeypatch):
        # Moves 1/mo but 100 on hand = 100 months of supply -> slow.
        entries = [_entry("2026-06-05", "Consumption", -12)]  # 12 over the year = 1/mo
        v = self._run(monkeypatch, entries, on_hand=100)
        assert v["months_supply"] > SLOW_MONTHS_SUPPLY
        assert v["is_slow"] is True

    def test_stale_no_movement_is_slow(self, monkeypatch):
        # Last real movement over a year ago -> stale -> slow, rate 0.
        entries = [_entry("2024-01-05", "Consumption", -5)]
        v = self._run(monkeypatch, entries, on_hand=3)
        assert v["monthly_rate"] == 0.0
        assert v["is_slow"] is True
        assert v["days_since_movement"] > 90

    def test_counts_do_not_count_as_movement(self, monkeypatch):
        # Only count/correction entries -> no real movement -> slow.
        entries = [
            _entry("2026-06-30", "Negative_x0020_Adjmt_x002E_", -1.4, "ANNUAL_COUNT_2026"),
            _entry("2026-02-02", "Negative_x0020_Adjmt_x002E_", -3.7, "BATCH_COUNT_FEB_2"),
        ]
        v = self._run(monkeypatch, entries, on_hand=8)
        assert v["monthly_rate"] == 0.0
        assert v["is_slow"] is True

    def test_recently_repurchased_bulk_is_not_slow(self, monkeypatch):
        """The 32'4" case: little DIRECT consumption (it's cut down, and those
        cuts are untagged historically), but bought within the last ~3.5 months
        -> actively turning -> NOT slow, despite high months_supply."""
        entries = [
            _entry("2026-06-30", "Negative_x0020_Adjmt_x002E_", -1.4, "ANNUAL_COUNT_2026"),  # noise
            _entry("2026-03-30", "Purchase", 15, "P-RCPT001279"),  # ~112 days ago
        ]
        v = self._run(monkeypatch, entries, on_hand=8)
        assert v["recently_replenished"] is True
        assert v["days_since_purchase"] <= mod.REPLENISH_DAYS
        assert v["is_slow"] is False

    def test_stale_purchase_stays_slow(self, monkeypatch):
        """Bought over a year ago and no real outflow -> genuinely dead."""
        entries = [_entry("2024-01-05", "Purchase", 10, "P-OLD")]
        v = self._run(monkeypatch, entries, on_hand=8)
        assert v["recently_replenished"] is False
        assert v["is_slow"] is True

    def test_ledger_error_defaults_to_slow(self, monkeypatch):
        class Boom:
            company_id = "co"
            def _make_request(self, *a): raise RuntimeError("down")
        import app.integrations.bc.client as bcmod
        monkeypatch.setattr(bcmod, "bc_client", Boom())
        v = svc.donor_velocity({"SKU": 5}, months=12, today=date(2026, 7, 20))["SKU"]
        assert v["is_slow"] is True
        assert v["monthly_rate"] == 0.0
