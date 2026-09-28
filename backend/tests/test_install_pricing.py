"""Builder-account installation pricing tests.

Covers the mount-surface rate model:
  wood $4.50 / steel $6.00 / concrete $8.50 per sqft, uniform across builders.
Residential doors <= 130 sqft have a flat FLOOR ($500 / $600) — we bill the
HIGHER of the floor and the per-sqft amount. Travel default is $2.25/km.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services import install_pricing_service as ips
from app.services.install_pricing_service import install_pricing_service as svc


class TestMountRate:
    """The per-sqft rate is chosen by mount surface (commercial / large doors)."""

    def _price(self, mount, area=200.0, door_type="commercial"):
        return svc._install_for_single_door(area, door_type, mount)

    def test_wood_rate(self):
        r = self._price("wood")
        assert r["rate"] == 4.50 and r["price"] == 900.0  # 200 * 4.50

    def test_steel_rate(self):
        r = self._price("steel")
        assert r["rate"] == 6.00 and r["price"] == 1200.0  # 200 * 6.00

    def test_concrete_rate(self):
        r = self._price("concrete")
        assert r["rate"] == 8.50 and r["price"] == 1700.0  # 200 * 8.50

    def test_unknown_mount_falls_back_to_wood(self):
        r = self._price("aluminum-siding")
        assert r["rate"] == 4.50

    def test_missing_mount_defaults_wood(self):
        assert svc._install_for_single_door(200.0, "commercial", None)["rate"] == 4.50


class TestResidentialFloor:
    """Residential <=130 sqft: bill max(flat floor, per-sqft)."""

    def test_small_wood_uses_flat_floor(self):
        # 72 sqft wood = 324 < 500 floor -> floor wins
        r = svc._install_for_single_door(72.0, "residential", "wood")
        assert r["price"] == 500.0 and r["tier"] == "residential-flat-floor"

    def test_small_steel_still_below_floor(self):
        # 72 sqft steel = 432 < 500 -> floor still wins
        r = svc._install_for_single_door(72.0, "residential", "steel")
        assert r["price"] == 500.0

    def test_small_concrete_exceeds_floor(self):
        # 72 sqft concrete = 612 > 500 -> per-sqft wins
        r = svc._install_for_single_door(72.0, "residential", "concrete")
        assert r["price"] == 612.0 and r["tier"] == "per-sqft"

    def test_medium_steel_exceeds_floor(self):
        # 120 sqft steel = 720 > 600 -> per-sqft wins
        r = svc._install_for_single_door(120.0, "residential", "steel")
        assert r["price"] == 720.0 and r["tier"] == "per-sqft"

    def test_medium_wood_uses_floor(self):
        # 120 sqft wood = 540 < 600 -> floor wins
        r = svc._install_for_single_door(120.0, "residential", "wood")
        assert r["price"] == 600.0

    def test_large_residential_is_per_sqft(self):
        # > 130 sqft -> always per-sqft, no floor
        r = svc._install_for_single_door(140.0, "residential", "wood")
        assert r["tier"] == "per-sqft" and r["price"] == 630.0  # 140 * 4.50


class TestTravelDefault:
    def test_default_travel_rate(self):
        assert ips.BUILDER_TRAVEL_RATE_PER_KM == 2.25

    def test_operator_addon(self):
        assert ips.BUILDER_OPERATOR_ADDON_PER_DOOR == 250.00


class TestTotalInstall:
    """End-to-end builder total honours per-door mount and the $2.25/km default."""

    def _run(self, monkeypatch, doors, town=None, km=None):
        monkeypatch.setattr(svc, "get_customer_pricing", lambda cid, db: None)
        if km is not None:
            monkeypatch.setattr(svc, "lookup_distance_km", lambda t, db: (km, "static"))
        return svc.calculate_total_install_price(customer_id=1, doors=doors, town=town, db=None)

    def test_mix_of_mounts(self, monkeypatch):
        doors = [
            {"doorWidth": 192, "doorHeight": 168, "doorCount": 1,
             "doorType": "commercial", "mountSurface": "steel"},   # 224 sqft * 6.00 = 1344
            {"doorWidth": 120, "doorHeight": 96, "doorCount": 1,
             "doorType": "commercial", "mountSurface": "wood"},    # 80 sqft * 4.50 = 360
        ]
        res = self._run(monkeypatch, doors)
        assert res["base_install_price"] == 1344.0 + 360.0
        mounts = {p["mount_surface"] for p in res["per_door"]}
        assert mounts == {"steel", "wood"}

    def test_travel_uses_default_rate(self, monkeypatch):
        doors = [{"doorWidth": 120, "doorHeight": 96, "doorCount": 1,
                  "doorType": "commercial", "mountSurface": "wood"}]
        res = self._run(monkeypatch, doors, town="Regina", km=590)
        assert res["travel_rate_per_km"] == 2.25
        assert res["travel_price"] == 1327.5  # 590 km * $2.25

    # --- Per-diem 200 km gate -------------------------------------------------
    def _big_doors(self):
        # Two 24' x 16' doors = 768 sqft total (> 400 sqft, so per-diem qualifies on size)
        return [{"doorWidth": 288, "doorHeight": 192, "doorCount": 2,
                 "doorType": "commercial", "mountSurface": "wood"}]

    def test_per_diem_charged_when_far(self, monkeypatch):
        res = self._run(monkeypatch, self._big_doors(), town="Regina", km=590)
        # 768 sqft -> 4 x 250 sqft blocks; far (> 200 km) -> per diem applies
        assert res["per_diem_applies"] is True
        assert res["per_diem_qty"] == 4
        assert res["per_diem_total"] == 800.0
        assert res["lift_qty"] == 2  # 16' doors > 12' -> 768/400 = 2 lift blocks

    def test_per_diem_250_blocks_lift_400_blocks(self, monkeypatch):
        # SQ-003191 shape: 2 x 12'x16' = 384 sqft, Melfort 880 km
        doors = [{"doorWidth": 144, "doorHeight": 192, "doorCount": 2,
                  "doorType": "commercial", "mountSurface": "wood"}]
        res = self._run(monkeypatch, doors, town="Melfort SK", km=880)
        assert res["per_diem_qty"] == 2 and res["per_diem_total"] == 400.0
        assert res["lift_qty"] == 1 and res["lift_total"] == 400.0
        assert res["travel_price"] == 1980.0
        assert res["grand_total"] == 1728.0 + 400.0 + 400.0 + 1980.0

    def test_no_per_diem_at_or_under_250(self, monkeypatch):
        doors = [{"doorWidth": 192, "doorHeight": 168, "doorCount": 1,
                  "doorType": "commercial", "mountSurface": "wood"}]  # 224 sqft
        res = self._run(monkeypatch, doors, town="Regina", km=590)
        assert res["per_diem_qty"] == 0

    def test_no_per_diem_within_200km(self, monkeypatch):
        # Elkwater ~66 km from Medicine Hat — day trip, no per diem even at 768 sqft
        res = self._run(monkeypatch, self._big_doors(), town="Elkwater", km=66)
        assert res["per_diem_applies"] is False
        assert res["per_diem_qty"] == 0
        assert res["per_diem_total"] == 0.0

    def test_no_per_diem_when_distance_unknown(self, monkeypatch):
        # No town / unknown distance -> cannot confirm overnight -> no per diem
        res = self._run(monkeypatch, self._big_doors())
        assert res["per_diem_total"] == 0.0


class TestInstallDescription:
    def test_includes_per_door_sqft_and_lift(self):
        ir = {"total_sqft": 768, "door_count_total": 2, "town": "Elkwater",
              "per_door": [{"area_sqft": 384, "door_count": 2}], "lift_qty": 2}
        desc = svc.build_install_description(ir)
        assert desc == "Installation - Elkwater (2 doors @ 384 sqft, 768 total, incl. lift)"
        assert len(desc) <= 100

    def test_single_door_no_lift(self):
        ir = {"total_sqft": 120, "door_count_total": 1, "town": None,
              "per_door": [{"area_sqft": 120, "door_count": 1}], "lift_qty": 0}
        desc = svc.build_install_description(ir)
        assert desc == "Installation (1 door, 120 sqft)"


class TestTravelResolution:
    """SQ-003191: 'Melfort SK' missed the static 'Melfort' entry -> $0 travel."""

    def test_province_suffix_matches_static(self, monkeypatch):
        monkeypatch.setattr(svc, "get_travel_distances", lambda db: {"Melfort": 880})
        monkeypatch.setattr(svc, "_google_distance_km", lambda t: None)
        for town in ("Melfort SK", "Melfort, Sask.", "melfort, saskatchewan"):
            assert svc.lookup_distance_km(town, None) == (880.0, "static")

    def test_warning_when_travel_unpriced(self):
        assert "no install town" in svc.travel_warning({"town": None, "travel_price": 0})
        assert "Nowhere" in svc.travel_warning({"town": "Nowhere", "travel_price": 0})
        assert svc.travel_warning({"town": "Regina", "travel_price": 1327.5}) is None

    def test_description_shows_km(self):
        ir = {"total_sqft": 384, "door_count_total": 2, "town": "Melfort SK",
              "per_door": [{"area_sqft": 192, "door_count": 2}], "lift_qty": 1,
              "travel_distance_km": 880, "travel_price": 1980}
        desc = svc.build_install_description(ir)
        assert desc == "Installation - Melfort SK (2 doors @ 192 sqft, 384 total, incl. lift, 880 km)"
        assert len(desc) <= 100
