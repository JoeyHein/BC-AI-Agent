"""Builder-account installation pricing tests.

Covers the mount-surface rate model:
  wood $4.50 / steel $5.50 / concrete $7.50 per sqft, uniform across builders.
Residential doors <= 130 sqft have a flat FLOOR ($500 / $600) — we bill the
HIGHER of the floor and the per-sqft amount. Travel default is $1/km.
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
        assert r["rate"] == 5.50 and r["price"] == 1100.0  # 200 * 5.50

    def test_concrete_rate(self):
        r = self._price("concrete")
        assert r["rate"] == 7.50 and r["price"] == 1500.0  # 200 * 7.50

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
        # 72 sqft steel = 396 < 500 -> floor still wins
        r = svc._install_for_single_door(72.0, "residential", "steel")
        assert r["price"] == 500.0

    def test_small_concrete_exceeds_floor(self):
        # 72 sqft concrete = 540 > 500 -> per-sqft wins
        r = svc._install_for_single_door(72.0, "residential", "concrete")
        assert r["price"] == 540.0 and r["tier"] == "per-sqft"

    def test_medium_steel_exceeds_floor(self):
        # 120 sqft steel = 660 > 600 -> per-sqft wins
        r = svc._install_for_single_door(120.0, "residential", "steel")
        assert r["price"] == 660.0 and r["tier"] == "per-sqft"

    def test_medium_wood_uses_floor(self):
        # 120 sqft wood = 540 < 600 -> floor wins
        r = svc._install_for_single_door(120.0, "residential", "wood")
        assert r["price"] == 600.0

    def test_large_residential_is_per_sqft(self):
        # > 130 sqft -> always per-sqft, no floor
        r = svc._install_for_single_door(140.0, "residential", "wood")
        assert r["tier"] == "per-sqft" and r["price"] == 630.0  # 140 * 4.50


class TestTravelDefault:
    def test_default_travel_is_one_dollar_per_km(self):
        assert ips.BUILDER_TRAVEL_RATE_PER_KM == 1.00


class TestTotalInstall:
    """End-to-end builder total honours per-door mount and the $1/km default."""

    def _run(self, monkeypatch, doors, town=None, km=None):
        monkeypatch.setattr(svc, "get_customer_pricing", lambda cid, db: None)
        if km is not None:
            monkeypatch.setattr(svc, "lookup_distance_km", lambda t, db: (km, "static"))
        return svc.calculate_total_install_price(customer_id=1, doors=doors, town=town, db=None)

    def test_mix_of_mounts(self, monkeypatch):
        doors = [
            {"doorWidth": 192, "doorHeight": 168, "doorCount": 1,
             "doorType": "commercial", "mountSurface": "steel"},   # 224 sqft * 5.50 = 1232
            {"doorWidth": 120, "doorHeight": 96, "doorCount": 1,
             "doorType": "commercial", "mountSurface": "wood"},    # 80 sqft * 4.50 = 360
        ]
        res = self._run(monkeypatch, doors)
        assert res["base_install_price"] == 1232.0 + 360.0
        mounts = {p["mount_surface"] for p in res["per_door"]}
        assert mounts == {"steel", "wood"}

    def test_travel_uses_one_dollar_default(self, monkeypatch):
        doors = [{"doorWidth": 120, "doorHeight": 96, "doorCount": 1,
                  "doorType": "commercial", "mountSurface": "wood"}]
        res = self._run(monkeypatch, doors, town="Regina", km=590)
        assert res["travel_rate_per_km"] == 1.00
        assert res["travel_price"] == 590.0  # 590 km * $1

    # --- Per-diem 200 km gate -------------------------------------------------
    def _big_doors(self):
        # Two 24' x 16' doors = 768 sqft total (> 400 sqft, so per-diem qualifies on size)
        return [{"doorWidth": 288, "doorHeight": 192, "doorCount": 2,
                 "doorType": "commercial", "mountSurface": "wood"}]

    def test_per_diem_charged_when_far(self, monkeypatch):
        res = self._run(monkeypatch, self._big_doors(), town="Regina", km=590)
        # 768 sqft -> 2 blocks; far (> 200 km) -> per diem applies
        assert res["per_diem_applies"] is True
        assert res["per_diem_qty"] == 2
        assert res["per_diem_total"] == 400.0

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
