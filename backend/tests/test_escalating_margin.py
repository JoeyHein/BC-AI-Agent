"""Escalating volume-margin curve (GNB Manitoba).

Locks the curve math that powers GNB's custom pricing grid before it goes live
(it had zero coverage). Numbers mirror docs/PRICING_GRID_GNB_MANITOBA.md, which
is generated from this same profile.
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from app.services.escalating_margin_service import (
    get_escalating_margin,
    get_profile_by_key,
)

GNB = get_profile_by_key("GNB_MANITOBA")


# ── target GM interpolation ─────────────────────────────────────────────────

@pytest.mark.parametrize("total,expected_gm", [
    (5_000, 30.0),     # below first breakpoint → base GM, no discount
    (9_999, 30.0),
    (10_000, 26.0),    # exact breakpoints
    (16_000, 23.0),
    (38_000, 18.5),
    (180_000, 9.5),
    (250_000, 9.5),    # above last → floor
    (12_000, 25.0),    # interpolated: 26 + (2/6)*(23-26)
])
def test_target_gm(total, expected_gm):
    assert GNB.get_target_gm(total) == pytest.approx(expected_gm, abs=0.01)


# ── multiplier / discount (matches the published sample table) ──────────────

@pytest.mark.parametrize("total,mult,discount", [
    (5_000, 1.0000, 0.0),
    (10_000, 0.9459, 5.41),
    (16_000, 0.9091, 9.09),
    (38_000, 0.8589, 14.11),
    (180_000, 0.7735, 22.65),
    (250_000, 0.7735, 22.65),
])
def test_calculate_multiplier_and_discount(total, mult, discount):
    r = GNB.calculate(total)
    assert r["multiplier"] == pytest.approx(mult, abs=0.0001)
    assert r["discount_pct"] == pytest.approx(discount, abs=0.01)


def test_below_threshold_is_a_no_op():
    r = GNB.calculate(9_999)
    assert r["multiplier"] == 1.0
    assert r["discount_pct"] == 0.0


def test_floor_does_not_go_below_9_5():
    # Arbitrarily huge quote still floors at 9.5% GM.
    assert GNB.get_target_gm(10_000_000) == 9.5


# ── ALUM exclusion ──────────────────────────────────────────────────────────

def test_alum_excluded_from_curve_and_subtotal():
    lines = {
        "a": {"price": 100.0, "qty": 2, "posting_group": "RESI"},   # 200
        "b": {"price": 50.0, "qty": 1, "posting_group": "HARD"},    # 50
        "c": {"price": 500.0, "qty": 1, "posting_group": "ALUM"},   # excluded
    }
    curve, excluded = GNB.split_lines(lines)
    assert set(curve) == {"a", "b"}
    assert set(excluded) == {"c"}
    # Subtotal must ignore the aluminum line.
    assert GNB.curve_subtotal(lines) == pytest.approx(250.0)


# ── customer matching ───────────────────────────────────────────────────────

@pytest.mark.parametrize("name", ["GNB Doors", "gnb manitoba", "GNB Doors (Manitoba)"])
def test_matches_gnb_names(name):
    p = get_escalating_margin(name)
    assert p is not None and p.name == "GNB Manitoba"


@pytest.mark.parametrize("name", ["Acme Garage", "", "Elevated Doors"])
def test_non_gnb_names_have_no_profile(name):
    assert get_escalating_margin(name) is None
