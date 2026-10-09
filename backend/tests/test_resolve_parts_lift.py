"""resolve-parts must price the lift the caller asked for.

Omitting liftType / highLiftInches / lhrMount / trackRadius keeps the
historical standard-lift bill of materials. Sending them selects the
track, hardware kit, high-lift extension, and spring length that
part_number_service already uses for the staff configurator.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import external_door_config
from app.api.auth import get_db
from app.api.external_door_config import _map_widget_config
from app.db.models import ExternalApiKey, User, UserRole
from app.services.external_api_keys_service import create_key
from app.services.part_number_service import get_parts_for_door_config


# A stock 8' x 7' residential door. Defaults (no lift fields) resolve to
# 15" radius, 2" bracket-mount standard lift.
_DOOR = {
    "doorType": "residential",
    "family": "KANATA",
    "widthInches": 96,
    "heightInches": 84,
    "colorId": "WHITE",
    "designId": "SHXL",
    "windows": "none",
}

_HISTORICAL_KEYS = {
    "doorType",
    "doorSeries",
    "doorWidth",
    "doorHeight",
    "doorCount",
    "panelColor",
    "panelDesign",
    "hasWindows",
    "windowQty",
    "windowFrameColor",
}


def _skus(parts):
    return [(p["part_number"], p["quantity"], p["category"]) for p in parts if p.get("part_number")]


def _resolved(door):
    summary = get_parts_for_door_config(_map_widget_config(door))
    return summary["parts_list"]


def _comment(parts):
    comments = [p["description"] for p in parts if p.get("category") == "comment"]
    assert comments, "expected a door comment line"
    return comments[0]


# ── mapping ────────────────────────────────────────────────────────────────


class TestLiftMapping:
    def test_omitted_fields_add_no_keys(self):
        mapped = _map_widget_config(dict(_DOOR))
        assert set(mapped) == _HISTORICAL_KEYS
        assert mapped["doorSeries"] == "KANATA"
        assert mapped["doorWidth"] == 96
        assert mapped["doorHeight"] == 84
        assert mapped["hasWindows"] is False

    def test_explicit_standard_is_passed_through(self):
        mapped = _map_widget_config({**_DOOR, "liftType": "standard", "trackRadius": "15"})
        assert mapped["liftType"] == "standard"
        assert mapped["trackRadius"] == "15"
        assert "lhrMount" not in mapped
        assert "highLiftInches" not in mapped

    def test_low_headroom_front_and_rear(self):
        front = _map_widget_config({**_DOOR, "liftType": "low_headroom", "lhrMount": "front"})
        rear = _map_widget_config({**_DOOR, "liftType": "low_headroom", "lhrMount": "rear"})
        assert front["liftType"] == "low_headroom" and front["lhrMount"] == "front"
        assert rear["liftType"] == "low_headroom" and rear["lhrMount"] == "rear"

    def test_plain_language_and_fit_engine_spellings(self):
        rear = _map_widget_config({**_DOOR, "liftType": "Low Headroom (Rear Mount)"})
        front = _map_widget_config({**_DOOR, "lift": "lhr_front"})
        high = _map_widget_config({**_DOOR, "liftType": "high lift", "highLiftIn": 36})
        std12 = _map_widget_config({**_DOOR, "liftType": "standard_12"})
        assert rear["liftType"] == "low_headroom" and rear["lhrMount"] == "rear"
        assert front["liftType"] == "low_headroom" and front["lhrMount"] == "front"
        assert high["liftType"] == "high_lift" and high["highLiftInches"] == 36
        assert std12["liftType"] == "standard" and std12["trackRadius"] == "12"

    def test_explicit_mount_and_radius_win_over_encoded_lift(self):
        mapped = _map_widget_config({
            **_DOOR,
            "liftType": "lhr_rear",
            "lhrMount": "front",
            "trackRadius": 15,
        })
        assert mapped["liftType"] == "low_headroom"
        assert mapped["lhrMount"] == "front"
        assert mapped["trackRadius"] == "15"

    def test_snake_case_and_inch_strings(self):
        mapped = _map_widget_config({
            **_DOOR,
            "lift_type": "high_lift",
            "high_lift_inches": "24 inches",
            "track_radius": "15\"",
            "track_thickness": 2,
            "track_mount": "angle",
        })
        assert mapped["liftType"] == "high_lift"
        assert mapped["highLiftInches"] == 24
        assert mapped["trackRadius"] == "15"
        assert mapped["trackThickness"] == "2"
        assert mapped["trackMount"] == "angle"

    def test_bad_lift_and_inches_do_not_fail_or_invent_a_lift(self):
        mapped = _map_widget_config({
            **_DOOR,
            "liftType": "sideways",
            "highLiftInches": "lots",
            "lhrMount": "sideways",
        })
        assert "liftType" not in mapped
        assert "highLiftInches" not in mapped
        assert "lhrMount" not in mapped

    def test_input_dict_is_not_mutated(self):
        original = {**_DOOR, "liftType": "high_lift", "highLiftInches": 24}
        snapshot = dict(original)
        _map_widget_config(original)
        assert original == snapshot


# ── parts the endpoint will price ──────────────────────────────────────────


class TestLiftParts:
    def test_omitted_fields_match_todays_standard_lift_parts(self):
        parts = _resolved(dict(_DOOR))
        skus = _skus(parts)
        numbers = [sku for sku, _qty, _cat in skus]
        assert ("TR02-STDBM-0715", 1, "track") in skus
        assert ("HK10-00704-0809", 1, "hardware") in skus
        assert ("SP11-21820-01", 31, "spring") in skus
        assert ("SP11-21820-02", 31, "spring") in skus
        assert not any(n.startswith("TR02-LHR") or n.startswith("TR02-EXT") or n.startswith("HK12") or n.startswith("HK32") for n in numbers)
        assert "LOW HEADROOM" not in _comment(parts)
        assert "HIGH LIFT" not in _comment(parts)

    def test_explicit_standard_matches_omitted_fields(self):
        omitted = _skus(_resolved(dict(_DOOR)))
        explicit = _skus(_resolved({**_DOOR, "liftType": "standard", "trackRadius": "15"}))
        assert explicit == omitted

    def test_twelve_inch_radius_changes_track_and_spring_length(self):
        standard_15 = _skus(_resolved(dict(_DOOR)))
        standard_12 = _skus(_resolved({**_DOOR, "liftType": "standard", "trackRadius": "12"}))
        assert ("TR02-STDBM-0712", 1, "track") in standard_12
        assert ("TR02-STDBM-0715", 1, "track") not in standard_12
        assert ("SP11-21820-01", 30, "spring") in standard_12
        assert standard_12 != standard_15

    def test_low_headroom_front_selects_lhr_track_and_hardware(self):
        parts = _resolved({
            **_DOOR,
            "liftType": "low_headroom",
            "lhrMount": "front",
            "trackRadius": "12",
        })
        skus = _skus(parts)
        numbers = [sku for sku, _qty, _cat in skus]
        assert ("TR02-LHR-07", 1, "track") in skus
        assert ("TR02-STDBM-0712", 1, "track") in skus
        assert ("HK32-11080-RC", 1, "hardware") in skus
        assert "HK10-00704-0809" not in numbers
        assert not any(n.startswith("TR02-EXT") or n.startswith("HK12") for n in numbers)
        assert "LOW HEADROOM (FRONT MOUNT)" in _comment(parts)

    def test_low_headroom_rear_same_priced_parts_different_note(self):
        front = _resolved({**_DOOR, "liftType": "low_headroom", "lhrMount": "front", "trackRadius": "12"})
        rear = _resolved({**_DOOR, "liftType": "Low Headroom (Rear Mount)", "trackRadius": "12"})
        # BC stocks the front-mount kit only, so the priced lines match.
        assert _skus(front) == _skus(rear)
        assert "LOW HEADROOM (REAR MOUNT)" in _comment(rear)
        assert "LOW HEADROOM (FRONT MOUNT)" not in _comment(rear)

    def test_high_lift_24_selects_extension_hardware_and_longer_springs(self):
        standard = _skus(_resolved(dict(_DOOR)))
        parts = _resolved({**_DOOR, "liftType": "high_lift", "highLiftInches": 24})
        skus = _skus(parts)
        numbers = [sku for sku, _qty, _cat in skus]
        assert ("TR02-STDBM-0715", 1, "track") in skus
        assert ("TR02-EXT2-00", 1, "highlift_track") in skus
        assert ("HK12-1108002-RC", 1, "hardware") in skus
        assert ("SP11-21820-01", 34, "spring") in skus
        assert ("SP11-21820-02", 34, "spring") in skus
        assert "HK10-00704-0809" not in numbers
        assert not any(n.startswith("TR02-LHR") or n.startswith("HK32") for n in numbers)
        assert skus != standard
        assert 'HIGH LIFT 24"' in _comment(parts)

    def test_high_lift_inches_change_the_extension_and_hardware(self):
        two_foot = _skus(_resolved({**_DOOR, "liftType": "high lift", "highLiftInches": 24}))
        three_foot = _skus(_resolved({**_DOOR, "liftType": "high_lift", "highLiftIn": 36}))
        assert ("TR02-EXT2-00", 1, "highlift_track") in two_foot
        assert ("HK12-1108002-RC", 1, "hardware") in two_foot
        assert ("TR02-EXT3-00", 1, "highlift_track") in three_foot
        assert ("HK12-1108003-RC", 1, "hardware") in three_foot
        assert two_foot != three_foot

    def test_high_lift_without_inches_uses_the_existing_two_foot_default(self):
        skus = _skus(_resolved({**_DOOR, "liftType": "high_lift"}))
        assert ("TR02-EXT2-00", 1, "highlift_track") in skus
        assert ("HK12-1108002-RC", 1, "hardware") in skus

    def test_three_inch_track_high_lift_uses_the_three_inch_kit(self):
        skus = _skus(_resolved({
            **_DOOR,
            "liftType": "high_lift",
            "highLiftInches": 24,
            "trackThickness": "3",
        }))
        assert ("TR03-EXT2-00", 1, "highlift_track") in skus
        assert ("HK13-1108002-RC", 1, "hardware") in skus
        assert ("TR02-EXT2-00", 1, "highlift_track") not in skus


# ── HTTP ───────────────────────────────────────────────────────────────────


@pytest.fixture
def db_factory():
    engine = create_engine(
        "sqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    User.__table__.create(engine, checkfirst=True)
    ExternalApiKey.__table__.create(engine, checkfirst=True)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


@pytest.fixture
def primary_key(db_factory):
    db = db_factory()
    try:
        admin = User(email="admin@test.local", password_hash="x", role=UserRole.ADMIN, is_active=True)
        db.add(admin)
        db.commit()
        db.refresh(admin)
        _row, plaintext = create_key(
            db, name="lift key", supplier_account_code="ED-001", created_by_user_id=admin.id
        )
        return plaintext
    finally:
        db.close()


@pytest.fixture
def client(db_factory):
    app = FastAPI()
    app.include_router(external_door_config.router)

    def _override_get_db():
        db = db_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    return TestClient(app)


def _post(client, key, door):
    response = client.post(
        "/api/external/door-config/resolve-parts",
        headers={"X-Service-AI-Key": key},
        json={"supplierAccountCode": "ED-001", "doorConfig": door},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is True
    return [(p["sku"], p["quantity"], p["category"]) for p in body["data"]["parts"]]


class TestResolvePartsEndpoint:
    def test_response_shape_is_unchanged(self, client, primary_key):
        response = client.post(
            "/api/external/door-config/resolve-parts",
            headers={"X-Service-AI-Key": primary_key},
            json={"supplierAccountCode": "ED-001", "doorConfig": {**_DOOR, "liftType": "high_lift", "highLiftInches": 24}},
        )
        assert response.status_code == 200
        part = response.json()["data"]["parts"][0]
        assert set(part) == {"sku", "quantity", "description", "category"}

    def test_standard_low_headroom_and_high_lift(self, client, primary_key):
        standard = _post(client, primary_key, dict(_DOOR))
        low_headroom = _post(client, primary_key, {
            **_DOOR, "liftType": "low_headroom", "lhrMount": "rear", "trackRadius": "12",
        })
        high_lift = _post(client, primary_key, {
            **_DOOR, "liftType": "high_lift", "highLiftInches": 24,
        })

        assert ("TR02-STDBM-0715", 1.0, "track") in standard
        assert ("HK10-00704-0809", 1.0, "hardware") in standard
        assert ("SP11-21820-01", 31.0, "spring") in standard

        assert ("TR02-LHR-07", 1.0, "track") in low_headroom
        assert ("HK32-11080-RC", 1.0, "hardware") in low_headroom
        assert ("TR02-EXT2-00", 1.0, "highlift_track") not in low_headroom

        assert ("TR02-EXT2-00", 1.0, "highlift_track") in high_lift
        assert ("HK12-1108002-RC", 1.0, "hardware") in high_lift
        assert ("SP11-21820-01", 34.0, "spring") in high_lift

        assert standard != low_headroom
        assert standard != high_lift
        assert low_headroom != high_lift

    def test_omitted_fields_match_explicit_standard_on_the_wire(self, client, primary_key):
        omitted = _post(client, primary_key, dict(_DOOR))
        explicit = _post(client, primary_key, {**_DOOR, "liftType": "standard", "trackRadius": 15})
        assert omitted == explicit
