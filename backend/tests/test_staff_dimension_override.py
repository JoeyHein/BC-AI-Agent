"""Staff may override catalog size limits; customer portals may not.

TX380 catalog max height is 192" (16'). Real quotes include 18–20' and staff
must be able to enter 28' (336") on the internal configurator. Customer
`_validate_doors_config` stays strict.
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi import HTTPException

from app.api.door_configurator import (
    ABSOLUTE_MAX_HEIGHT_IN,
    ABSOLUTE_MAX_WIDTH_IN,
    collect_absolute_dimension_errors,
    collect_dimension_validation,
    validate_door_dimensions,
)
from app.api.customer_portal import _validate_doors_config


def _tx380_door(width, height):
    return {
        "doorType": "commercial",
        "doorSeries": "TX380",
        "doorWidth": width,
        "doorHeight": height,
    }


def test_tx380_28ft_is_catalog_error_when_strict():
    errors, warnings = collect_dimension_validation(
        "commercial", "TX380", 194, 336  # 16'2" × 28'0"
    )
    assert any('exceeds maximum 192"' in e for e in errors)
    assert not any('exceeds maximum 192"' in w for w in warnings)
    with pytest.raises(ValueError, match="exceeds maximum 192"):
        validate_door_dimensions("commercial", "TX380", 194, 336)


def test_staff_tx380_28ft_is_warning_not_error():
    errors, warnings = collect_dimension_validation(
        "commercial", "TX380", 194, 336, strict=False
    )
    assert errors == []
    assert any('exceeds maximum 192"' in w for w in warnings)
    validate_door_dimensions("commercial", "TX380", 194, 336, strict=False)


def test_staff_craft_unstocked_size_is_warning_not_error():
    errors, warnings = collect_dimension_validation(
        "residential", "CRAFT", 120, 84, strict=False  # 10' × 7'
    )
    assert errors == []
    assert any("not available in width 10'0\"" in w for w in warnings)
    validate_door_dimensions("residential", "CRAFT", 120, 84, strict=False)


def test_customer_portal_still_rejects_tx380_over_max_height():
    with pytest.raises(HTTPException) as ei:
        _validate_doors_config({"doors": [_tx380_door(194, 336)]})
    assert ei.value.status_code == 400
    assert "Door 1:" in ei.value.detail
    assert "exceeds maximum 192" in ei.value.detail


def test_customer_portal_still_rejects_unstocked_craft():
    with pytest.raises(HTTPException) as ei:
        _validate_doors_config({
            "doors": [{
                "doorType": "residential",
                "doorSeries": "CRAFT",
                "doorWidth": 120,
                "doorHeight": 84,
            }]
        })
    assert ei.value.status_code == 400
    assert "not available in width 10'0\"" in ei.value.detail


def test_staff_override_still_blocks_beyond_absolute_envelope():
    too_tall = ABSOLUTE_MAX_HEIGHT_IN + 12  # 41'
    errors, warnings = collect_dimension_validation(
        "commercial", "TX380", 194, too_tall, strict=False
    )
    assert any("must be between" in e and "40'" in e for e in errors)
    assert any('exceeds maximum 192"' in w for w in warnings)
    with pytest.raises(ValueError, match="must be between"):
        validate_door_dimensions("commercial", "TX380", 194, too_tall, strict=False)


def test_absolute_envelope_matches_staff_calculator_limits():
    assert ABSOLUTE_MAX_WIDTH_IN == 576  # 48'
    assert ABSOLUTE_MAX_HEIGHT_IN == 480  # 40'
    # 28' used to fail the old calculate-door 24' cap.
    assert collect_absolute_dimension_errors(194, 336, skip_zero=False) == []
    assert collect_absolute_dimension_errors(0, 0, skip_zero=False)
    assert not collect_absolute_dimension_errors(0, 0, skip_zero=True)
