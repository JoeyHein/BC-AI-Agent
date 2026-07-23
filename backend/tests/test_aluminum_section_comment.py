"""Aluminum sections + glass-pockets BC comment line.

Aluminum doors must carry a comment on the quote (and therefore the order,
since BC copies comment lines on quote→order conversion) showing how many
sections the door has and how many glass pockets sit in each section. Built
by format_aluminum_section_comment and emitted by both the in-house
configurator and all three customer-portal quote paths.
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.part_number_service import (
    format_aluminum_section_comment as fmt,
    _section_count,
)


# ── section count from door height ──────────────────────────────────────────

def test_section_count_ceil_of_height_over_24():
    assert _section_count(168) == 7   # ceil(168/24)
    assert _section_count(144) == 6
    assert _section_count(120) == 5

def test_section_count_floor_is_three():
    assert _section_count(60) == 3     # short door clamps to 3

def test_section_count_non_multiple_rounds_up():
    assert _section_count(130) == 6    # ceil(130/24) = 6


# ── comment formatting ──────────────────────────────────────────────────────

def test_default_pockets_from_width():
    # 14' wide (168") default is 5 pockets, 14' tall (168") is 7 sections
    assert fmt(168, 168, None) == "** 7 SECTIONS, 5 GLASS POCKETS PER SECTION **"

def test_uniform_per_section_dict():
    assert fmt(120, 144, {"0": 4, "1": 4, "2": 4, "3": 4, "4": 4}) == \
        "** 5 SECTIONS, 4 GLASS POCKETS PER SECTION **"

def test_varying_per_section_dict_lists_breakdown():
    assert fmt(120, 144, {"0": 5, "1": 4, "2": 4, "3": 4, "4": 4}) == \
        "** 5 SECTIONS, GLASS POCKETS PER SECTION: 5/4/4/4/4 **"

def test_int_keyed_dict_supported():
    assert fmt(96, 96, {0: 2, 1: 2, 2: 2, 3: 2}) == \
        "** 4 SECTIONS, 2 GLASS POCKETS PER SECTION **"

def test_scalar_int_pockets():
    assert fmt(96, 96, 3) == "** 4 SECTIONS, 3 GLASS POCKETS PER SECTION **"

def test_empty_dict_falls_back_to_width_default():
    # 8' wide (96") default is 2 pockets; 8' tall (96") is 4 sections
    assert fmt(96, 96, {}) == "** 4 SECTIONS, 2 GLASS POCKETS PER SECTION **"
