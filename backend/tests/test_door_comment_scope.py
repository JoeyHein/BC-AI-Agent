"""BC comment-line scope tags for partial hardware orders.

The BC quote header comment is built by _format_door_description in BOTH
door_configurator (in-house, takes a DoorConfigRequest) and customer_portal
(takes a dict). Both must reflect PANELS ONLY / DOOR FACE ONLY / NO DOOR FACE
and drop the track/mount + lift detail for face/panels-only orders (no tracks).
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.api.door_configurator import (
    _format_scope_label,
    _format_door_description as fmt_inhouse,
    DoorConfigRequest,
)
from app.api.customer_portal import _format_door_description as fmt_customer

ALL_OFF = {"tracks": False, "springs": False, "struts": False,
           "hardwareKits": False, "weatherStripping": False, "shafts": False}


# ── scope label core logic ──────────────────────────────────────────────────

def test_scope_label_panels_only():
    assert _format_scope_label({"panels": True, "bottomRetainer": False, **ALL_OFF}) == "PANELS ONLY"

def test_scope_label_door_face_only():
    assert _format_scope_label({"panels": True, "bottomRetainer": True, **ALL_OFF}) == "DOOR FACE ONLY"

def test_scope_label_hardware_only():
    assert _format_scope_label({"panels": False, "tracks": True, "springs": True}) == "NO DOOR FACE"

def test_scope_label_complete_door_is_none():
    assert _format_scope_label({}) is None

def test_scope_label_aluminium_panels_implicitly_on():
    # Aluminium ships sections regardless of a panels flag → face-only, not NO DOOR FACE.
    assert _format_scope_label({**ALL_OFF}, door_type="aluminium") == "DOOR FACE ONLY"


# ── in-house builder (DoorConfigRequest) ────────────────────────────────────

def _door(**hw):
    return DoorConfigRequest(
        doorType="commercial", doorSeries="TX450", doorWidth=144, doorHeight=120,
        doorCount=1, panelColor="WHITE", panelDesign="UDC", trackThickness="3",
        trackMount="bracket", liftType="standard", hardware=hw,
    )

def test_inhouse_face_only_drops_track_and_lift():
    desc = fmt_inhouse(_door(panels=True, bottomRetainer=True, **ALL_OFF))
    assert desc.endswith("DOOR FACE ONLY")
    assert "MOUNT" not in desc and "LIFT" not in desc

def test_inhouse_complete_keeps_track_and_lift():
    desc = fmt_inhouse(_door())  # empty hardware = all defaults on
    assert "3\" BRACKET MOUNT" in desc and "STD LIFT" in desc
    assert "ONLY" not in desc and "NO DOOR FACE" not in desc

def test_inhouse_hardware_only_keeps_track_and_tags():
    desc = fmt_inhouse(_door(panels=False))
    assert "BRACKET MOUNT" in desc and desc.endswith("NO DOOR FACE")


# ── customer-portal builder (dict) ──────────────────────────────────────────

def _door_dict(**hw):
    return {
        "doorType": "commercial", "doorSeries": "TX450", "doorWidth": 144,
        "doorHeight": 120, "doorCount": 1, "panelColor": "WHITE",
        "panelDesign": "UDC", "trackThickness": "3", "trackMount": "bracket",
        "liftType": "standard", "hardware": hw,
    }

def test_customer_face_only_drops_track_and_lift():
    desc = fmt_customer(_door_dict(panels=True, bottomRetainer=True, **ALL_OFF))
    assert desc.endswith("DOOR FACE ONLY")
    assert "MOUNT" not in desc and "LIFT" not in desc

def test_customer_complete_keeps_track_and_lift():
    desc = fmt_customer(_door_dict())
    assert "3\" BRACKET MOUNT" in desc and "STD LIFT" in desc
    assert "ONLY" not in desc
