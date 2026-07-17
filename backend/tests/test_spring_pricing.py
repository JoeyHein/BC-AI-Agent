"""Cost-aware spring selection tests.

Spring selection used to optimize length (shortest wins), which is inversely
correlated with price — a shorter spring means a bigger coil, which costs more
per inch, needs a pricier winder, and at 6" drags in a PVC tube. These tests pin
the behaviour that replaced it:

- the cheapest mechanically-valid assembly wins, not the shortest
- duplex is a last resort, not the default when small coils don't fit
- candidates with no trustworthy BC price never get picked
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services import spring_pricing
from app.services.door_calculator_service import DoorCalculatorService

STD_LIFT = {"type": "standard"}


@pytest.fixture(scope="module")
def svc():
    return DoorCalculatorService()


def _select(svc, weight, height, width, cycles=50000, track_size=3):
    drum = svc._select_drum(height, weight, STD_LIFT, track_size=track_size)
    assert drum is not None, f"no drum for {height}\" @ {weight} lbs"
    return svc._calculate_springs(weight, height, width, drum, cycles, 15, 2), drum


class TestPriceBook:
    def test_price_book_loads(self):
        assert spring_pricing.has_price_book(), (
            "spring_price_book.json missing — run: python -m scripts.refresh_spring_prices"
        )

    def test_no_zero_or_negative_prices(self):
        """A $0 part looks free and would win every comparison.

        SP11-25036-01/-02 are live and unblocked in BC at $0.00 — they must not
        reach the price book.
        """
        bad = {pn: p for pn, p in spring_pricing.PRICES.items() if p <= 0}
        assert not bad, f"non-positive prices in book: {bad}"

    def test_phantom_zero_priced_spring_excluded(self):
        assert spring_pricing.price_of("SP11-25036-01") is None
        assert spring_pricing.price_of("SP11-25036-02") is None

    def test_unknown_part_has_no_price(self):
        assert spring_pricing.price_of("SP11-99999-01") is None
        assert spring_pricing.price_of("") is None


class TestAssemblyCost:
    def test_six_inch_costs_more_than_smaller_coil_at_same_wire(self):
        """6" carries a triple penalty: dearer wire/in, dearer winder, plus a PVC tube."""
        small = spring_pricing.assembly_cost(0.3125, 3.75, 39, 2)
        big = spring_pricing.assembly_cost(0.3125, 6.0, 26, 2)
        assert small is not None and big is not None
        assert small < big

    def test_unpriced_wire_coil_returns_none_not_zero(self):
        """.375 x 3.75" is a valid Canimex pairing with no BC SKU.

        None keeps it out of the running; 0.0 would make it win outright.
        """
        assert spring_pricing.assembly_cost(0.375, 3.75, 40, 2) is None

    def test_pvc_tube_charged_for_six_inch_only(self):
        """6" springs need a PVC tube; smaller coils don't.

        Rebuilt from components so the tube is pinned exactly, not just implied
        by an inequality.
        """
        from app.services.bc_part_number_mapper import get_bc_mapper

        mapper = get_bc_mapper()
        qty, length = 2, 30
        pvc = spring_pricing.price_of(spring_pricing.PVC_TUBE_PN)

        for coil, expect_tube in ((6.0, True), (3.75, False)):
            lh = spring_pricing.price_of(mapper.get_spring_part_number(0.3125, coil, "LH").part_number)
            rh = spring_pricing.price_of(mapper.get_spring_part_number(0.3125, coil, "RH").part_number)
            winder = spring_pricing.price_of(mapper.get_winder_stationary_set(coil, 1.0).part_number)
            expected = lh * length + rh * length + winder * qty
            if expect_tube:
                expected += pvc * length * qty
            actual = spring_pricing.assembly_cost(0.3125, coil, length, qty)
            assert actual == pytest.approx(expected, abs=0.01), f"coil {coil}"

    def test_duplex_skips_pvc_tube(self):
        """The inner spring already fills a duplex outer, so no tube is billed."""
        from app.services.bc_part_number_mapper import get_bc_mapper

        mapper = get_bc_mapper()
        qty, pairs, outer_len, inner_len = 4, 2, 30, 28
        cost = spring_pricing.assembly_cost(
            0.3125, 6.0, outer_len, qty,
            is_duplex=True, inner_wire_diameter=0.2625, inner_coil_diameter=3.75,
            inner_length=inner_len, duplex_pairs=pairs,
        )
        assert cost is not None

        def p(pn):
            return spring_pricing.price_of(pn)

        outer = sum(p(mapper.get_spring_part_number(0.3125, 6.0, w).part_number) * outer_len * (qty // 2)
                    for w in ("LH", "RH"))
        inner = sum(p(mapper.get_spring_part_number(0.2625, 3.75, w).part_number) * inner_len * pairs
                    for w in ("LH", "RH"))
        winders = (p(mapper.get_winder_stationary_set(6.0, 1.0).part_number) * qty
                   + p(mapper.get_winder_stationary_set(3.75, 1.0).part_number) * qty)
        coupler = spring_pricing.price_of(spring_pricing.COUPLER_PN) * (qty // 2 - 1)
        assert cost == pytest.approx(outer + inner + winders + coupler, abs=0.01)

    def test_couplers_charged_above_two_springs(self):
        """qty > 2 forces a second shaft, so couplers are real cost."""
        two = spring_pricing.assembly_cost(0.2625, 3.75, 30, 2)
        four = spring_pricing.assembly_cost(0.2625, 3.75, 30, 4)
        assert two is not None and four is not None
        coupler = spring_pricing.price_of(spring_pricing.COUPLER_PN)
        # 4 springs = 2x the springs/winders of 2, plus exactly one coupler.
        assert four == pytest.approx(two * 2 + coupler, abs=0.01)

    def test_single_spring_has_no_rh_counterpart(self):
        """qty=1 is one LH spring — pricing an RH would double-count."""
        one = spring_pricing.assembly_cost(0.2500, 2.0, 30, 1)
        two = spring_pricing.assembly_cost(0.2500, 2.0, 30, 2)
        assert one is not None and two is not None
        assert one < two


class TestCostAwareSelection:
    def test_picks_cheaper_coil_over_shorter_spring(self, svc):
        """SQ-001722 Door A: 10'2 x 10, 314 lb.

        6" gives a shorter spring (26" vs 39") and the old length-based sort took
        it. 3.75" hits the same MIP at the same cycle life and is ~18% cheaper.
        """
        sel, _ = _select(svc, 314, 120, 122)
        assert sel is not None
        assert not sel.is_duplex
        assert sel.coil_diameter == 3.75

    def test_selected_option_is_cheapest_priced_candidate(self, svc):
        """Whatever wins must be the minimum-cost candidate that fits."""
        from app.services.door_calculator_service import _springs_fit_on_shaft

        weight, height, width, cycles = 314, 120, 122, 50000
        sel, drum = _select(svc, weight, height, width, cycles)
        assert sel is not None and not sel.is_duplex

        costs = []
        for qty in (2, 4, 6, 8):
            for cand in svc._enumerate_spring_candidates(
                weight, height, 15, qty, cycles, drum.model, 0
            ):
                if not _springs_fit_on_shaft(
                    width, cand.length, qty, cand.coil_diameter, drum.model,
                    turns=cand.turns, wire_diameter=cand.wire_diameter,
                ):
                    continue
                c = spring_pricing.assembly_cost(
                    cand.wire_diameter, cand.coil_diameter, cand.length, qty
                )
                if c is not None:
                    costs.append(c)
        assert costs
        chosen = spring_pricing.assembly_cost(
            sel.wire_diameter, sel.coil_diameter, sel.length, sel.quantity
        )
        assert chosen == pytest.approx(min(costs), abs=0.01)

    def test_no_duplex_when_a_single_spring_fits(self, svc):
        """Duplex is a nested 6"+3.75" build — it must not win by default.

        These all used to come back duplex because coil escalation stopped at the
        first MIP-passing coil, produced an over-long spring, and the fit check
        then rejected every single-spring option.
        """
        for weight, height, width in [(314, 120, 122), (256, 120, 98), (250, 96, 120), (180, 84, 96)]:
            sel, _ = _select(svc, weight, height, width)
            assert sel is not None, f"no spring for {width}x{height} {weight}lb"
            assert not sel.is_duplex, f"{width}x{height} {weight}lb wrongly picked duplex"

    def test_selection_never_returns_unpriceable_spring(self, svc):
        """A pick with no BC part can't be ordered; it should never be chosen
        when a priced alternative exists."""
        for weight, height, width in [(520, 144, 168), (400, 120, 144), (650, 168, 216)]:
            sel, _ = _select(svc, weight, height, width)
            if sel is None or sel.is_duplex:
                continue
            cost = spring_pricing.assembly_cost(
                sel.wire_diameter, sel.coil_diameter, sel.length, sel.quantity
            )
            assert cost is not None, (
                f"{width}x{height} {weight}lb selected {sel.wire_diameter}x{sel.coil_diameter} "
                f"which has no BC price"
            )

    def test_meets_requested_cycle_life(self, svc):
        """Cost pressure must never undercut the cycle target."""
        from app.services.spring_calculator_service import spring_calculator

        for cycles in (25000, 50000, 100000):
            sel, _ = _select(svc, 314, 120, 122, cycles=cycles)
            assert sel is not None
            if sel.is_duplex:
                continue
            assert sel.cycles == cycles
            capacity = spring_calculator.get_mip_capacity(sel.wire_diameter, cycles)
            assert capacity is not None

    def test_never_exceeds_practical_length_when_avoidable(self, svc):
        sel, _ = _select(svc, 314, 120, 122)
        assert sel is not None
        assert sel.length <= 75.0


class TestInventoryPathCostAware:
    """The portal/configurator route through _calculate_springs_from_inventory,
    a separate selector. It must pick on cost too, so a door quoted through the
    portal matches the same door quoted through email."""

    def test_prefers_cheaper_coil_within_stock(self, svc):
        # .289 x 3.75 fits the 98" door and is cheaper than any 6" option; with
        # it in stock the inventory path must not fall back to a 6" coil.
        inv = {"3.75": ["0.2890", "0.3125"], "6.0": ["0.2950", "0.3125"]}
        drum = svc._select_drum(120, 256, STD_LIFT, track_size=3)
        sel = svc._calculate_springs_from_inventory(
            256, 120, 50000, 15, inv, 98, drum_model=drum.model
        )
        assert sel is not None
        assert not sel.is_duplex
        assert sel.coil_diameter == 3.75

    def test_respects_stock_constraint(self, svc):
        # Only 6" stocked → must pick 6" even though 3.75" would be cheaper.
        inv = {"6.0": ["0.2950", "0.3125", "0.3310"]}
        drum = svc._select_drum(120, 256, STD_LIFT, track_size=3)
        sel = svc._calculate_springs_from_inventory(
            256, 120, 50000, 15, inv, 98, drum_model=drum.model
        )
        assert sel is not None
        assert sel.coil_diameter == 6.0

    def test_meets_cycle_life_from_inventory(self, svc):
        from app.services.spring_calculator_service import spring_calculator

        inv = {"3.75": ["0.2890", "0.3125", "0.3437"], "6.0": ["0.3125", "0.3310"]}
        drum = svc._select_drum(120, 314, STD_LIFT, track_size=3)
        sel = svc._calculate_springs_from_inventory(
            314, 120, 100000, 15, inv, 122, drum_model=drum.model
        )
        assert sel is not None
        cap = spring_calculator.get_mip_capacity(sel.wire_diameter, 100000)
        assert cap is not None


class TestFallbackWithoutPriceBook:
    def test_falls_back_to_legacy_ordering_when_book_empty(self, svc, monkeypatch):
        """No price book (fresh checkout, unreadable file) must still quote a door."""
        monkeypatch.setattr(spring_pricing, "PRICES", {})
        sel, _ = _select(svc, 314, 120, 122)
        assert sel is not None
        assert sel.wire_diameter > 0 and sel.coil_diameter > 0
