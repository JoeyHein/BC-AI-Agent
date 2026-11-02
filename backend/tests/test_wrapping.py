"""In-house wrapping on every steel door package.

Quantity matches Upwardor's invoice rule: round one door's opening to the
nearest square foot (half up), then multiply by the door count. Sell price
is $0.95/SF even though the WRAP item card in BC is $2.50.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.part_number_service import get_parts_for_door_config
from app.services.wrapping import (
    WRAP_SELL_PRICE_PER_SF,
    fixed_wrap_unit_price,
    wrapping_sqft,
)


def _parts(**overrides):
    base = {
        "doorType": "residential",
        "doorSeries": "KANATA",
        "doorWidth": 96,
        "doorHeight": 84,
        "doorCount": 1,
        "panelColor": "WHITE",
        "panelDesign": "SHXL",
        "hardware": {
            "struts": True, "tracks": True, "springs": True,
            "hardwareKits": True, "weatherStripping": True,
            "bottomRetainer": True, "shafts": True,
        },
        "targetCycles": 10000,
        "trackThickness": "2",
        "trackRadius": "15",
        "trackMount": "bracket",
        "liftType": "standard",
    }
    base.update(overrides)
    return get_parts_for_door_config(base).get("parts_list", [])


def _wrap(parts):
    rows = [p for p in parts if p.get("part_number") == "WRAP"]
    assert len(rows) == 1, rows
    return rows[0]


# ── rounding ──────────────────────────────────────────────────────────────

class TestWrappingSqft:
    def test_invoice_14ft2_by_14_rounds_down(self):
        # 14'2" x 14' = 198.333… -> 198. Verified against an Upwardor invoice.
        assert wrapping_sqft(14 * 12 + 2, 14 * 12) == 198

    def test_invoice_24ft2_by_16_rounds_up(self):
        # 24'2" x 16' = 386.666… -> 387.
        assert wrapping_sqft(24 * 12 + 2, 16 * 12) == 387

    def test_invoice_16ft2_by_14_per_door(self):
        # 16'2" x 14' = 226.333… -> 226, before the door quantity is applied.
        assert wrapping_sqft(16 * 12 + 2, 14 * 12) == 226

    def test_inch_width_12ft2(self):
        # 12'2" x 8' = 97.333… -> 97.
        assert wrapping_sqft(12 * 12 + 2, 8 * 12) == 97

    def test_half_rounds_up_not_bankers(self):
        # 9'0" x 11'2" = 108 * 134 / 144 = 100.5.
        # Python round() is half-to-even and returns 100.
        assert (108 * 134) / 144 == 100.5
        assert round(100.5) == 100
        assert wrapping_sqft(108, 134) == 101

    def test_smaller_half_also_rounds_up(self):
        # 18" x 20" = 2.5. round(2.5) == 2; we want 3.
        assert round(2.5) == 2
        assert wrapping_sqft(18, 20) == 3

    def test_exact_square_footage_stays_put(self):
        # 10' x 10' = 100 exactly.
        assert wrapping_sqft(120, 120) == 100

    def test_non_positive_opening_is_zero(self):
        assert wrapping_sqft(0, 84) == 0
        assert wrapping_sqft(96, 0) == 0
        assert wrapping_sqft(-12, 84) == 0


class TestWrapOnDoorPackages:
    def test_verified_invoice_sizes_round_per_door_then_multiply(self):
        one = _wrap(_parts(doorWidth=14 * 12 + 2, doorHeight=14 * 12, doorCount=1))
        assert one["quantity"] == 198
        assert one["description"] == "Wrapping"
        assert one["category"] == "wrapping"
        assert one["unit_price"] == WRAP_SELL_PRICE_PER_SF

        wide = _wrap(_parts(
            doorType="commercial", doorSeries="TX450",
            panelDesign="UDC", trackThickness="3",
            doorWidth=24 * 12 + 2, doorHeight=16 * 12, doorCount=1,
        ))
        assert wide["quantity"] == 387
        assert wide["unit_price"] == 0.95

        pair = _wrap(_parts(
            doorWidth=16 * 12 + 2, doorHeight=14 * 12, doorCount=2,
        ))
        # 226 per door, then × 2. Rounding the combined 452.666… would be 453.
        assert pair["quantity"] == 452
        assert round(pair["quantity"] * pair["unit_price"], 2) == 429.40

    def test_half_up_is_applied_before_door_quantity(self):
        # 100.5 SF rounds to 101, then × 2 = 202.
        # Rounding after the multiply (201.0) would stay 201.
        row = _wrap(_parts(doorWidth=108, doorHeight=134, doorCount=2))
        assert row["quantity"] == 202
        assert round(row["quantity"] * row["unit_price"], 2) == 191.90

    def test_inch_width_on_a_real_door(self):
        row = _wrap(_parts(doorWidth=12 * 12 + 2, doorHeight=8 * 12))
        assert row["quantity"] == 97
        assert round(row["quantity"] * 0.95, 2) == 92.15

    @pytest.mark.parametrize("series,door_type,design", [
        ("KANATA", "residential", "SHXL"),
        ("CRAFT", "residential", "FLUSH"),
        ("TX380", "commercial", "UDC"),
        ("TX450", "commercial", "UDC"),
        ("TX500", "commercial", "UDC"),
        ("TX760", "commercial", "MICROGROOVE"),
    ])
    def test_residential_and_commercial_series_include_wrap(self, series, door_type, design):
        width = 96 if series == "CRAFT" else 120
        height = 84 if series in ("KANATA", "CRAFT") else 96
        parts = _parts(
            doorType=door_type, doorSeries=series, panelDesign=design,
            doorWidth=width, doorHeight=height,
            trackThickness="2" if door_type == "residential" else "3",
        )
        row = _wrap(parts)
        assert row["quantity"] == wrapping_sqft(width, height)
        assert row["unit_price"] == 0.95
        assert not any(p.get("part_number") == "WRAPALU" for p in parts)

    def test_panels_only_still_wraps(self):
        # A door face / panels-only order still ships panels, so it wraps.
        hw = {
            "panels": True, "bottomRetainer": False,
            "tracks": False, "springs": False, "struts": False,
            "hardwareKits": False, "weatherStripping": False, "shafts": False,
        }
        row = _wrap(_parts(hardware=hw, doorWidth=16 * 12 + 2, doorHeight=14 * 12))
        assert row["quantity"] == 226

    def test_hardware_only_is_excluded(self):
        hw = {
            "panels": False, "tracks": True, "springs": True, "struts": True,
            "hardwareKits": True, "weatherStripping": True,
            "bottomRetainer": True, "shafts": True,
        }
        parts = _parts(hardware=hw)
        assert not any(p.get("part_number") == "WRAP" for p in parts)

    def test_operator_only_is_excluded(self):
        hw = {
            "panels": False, "tracks": True, "springs": True, "struts": True,
            "hardwareKits": True, "weatherStripping": True,
            "bottomRetainer": False, "shafts": True,
        }
        parts = _parts(hardware=hw, operator="OP19-01048-00")
        assert not any(p.get("part_number") == "WRAP" for p in parts)

    def test_operator_on_a_complete_door_still_wraps(self):
        row = _wrap(_parts(operator="OP19-01048-00", doorWidth=120, doorHeight=96))
        assert row["quantity"] == wrapping_sqft(120, 96)

    @pytest.mark.parametrize("series,glazing", [
        ("AL976", "glass"),
        ("PANORAMA", "polycarbonate"),
        ("SOLALITE", "polycarbonate"),
        ("SWD", "glass"),
    ])
    def test_aluminum_keeps_wrapalu_and_is_not_double_charged(self, series, glazing):
        parts = _parts(
            doorType="aluminium", doorSeries=series,
            panelColor="CLEAR_ANODIZED", panelDesign="FLUSH",
            glazingType=glazing, doorWidth=96, doorHeight=84,
        )
        assert not any(p.get("part_number") == "WRAP" for p in parts)
        alu = [p for p in parts if p.get("part_number") == "WRAPALU"]
        assert len(alu) == 1
        assert alu[0]["category"] == "aluminum_wrapping"
        # WRAPALU quantity stays on the existing section formula (not forced
        # to the steel nearest-SF rule, and not repriced to $0.95).
        assert alu[0].get("unit_price") is None


class TestWrapSellPrice:
    def test_only_the_wrap_item_is_overridden(self):
        assert fixed_wrap_unit_price({
            "part_number": "WRAP", "quantity": 198, "unit_price": 0.95,
        }) == 0.95
        # A caller that drops unit_price still cannot fall through to $2.50.
        assert fixed_wrap_unit_price({"part_number": "wrap", "quantity": 10}) == 0.95
        assert fixed_wrap_unit_price({
            "part_number": "PN45-24400-0900", "unit_price": 100,
        }) is None
        assert fixed_wrap_unit_price({
            "part_number": "WRAPALU", "description": "WRAPPING - ALUMINUM PANELS",
        }) is None
        assert fixed_wrap_unit_price({
            "lineType": "Comment", "part_number": "WRAP",
        }) is None

    def test_line_order_places_wrapping_with_the_door_face(self):
        from app.api.door_configurator import LINE_ORDER as admin_order
        from app.api.door_configurator import _sort_parts_by_category as admin_sort
        from app.api.customer_portal import LINE_ORDER as portal_order
        from app.api.customer_portal import _sort_parts_by_category as portal_sort

        for order in (admin_order, portal_order):
            assert order.index("panel") < order.index("wrapping") < order.index("retainer")

        parts = [
            {"category": "operator", "part_number": "OP"},
            {"category": "wrapping", "part_number": "WRAP"},
            {"category": "panel", "part_number": "PN"},
            {"category": "aluminum_wrapping", "part_number": "WRAPALU"},
        ]
        for sort in (admin_sort, portal_sort):
            ordered = [p["part_number"] for p in sort(parts)]
            assert ordered.index("PN") < ordered.index("WRAP")
            # WRAPALU is intentionally unsorted (left as-is, at the end).
            assert ordered[-1] == "WRAPALU"


class _RecordingBC:
    def __init__(self):
        self.added = []
        self.updates = []
        self.n = 0

    def create_sales_quote(self, quote_data, company_id=None):
        self.n += 1
        return {"id": f"quote-{self.n}", "number": f"SQ-90000{self.n}"}

    def add_quote_line(self, quote_id, line_data, company_id=None):
        self.added.append(dict(line_data))
        self.n += 1
        return {
            "id": f"line-{self.n}",
            "sequence": self.n * 10000,
            "@odata.etag": "*",
            "description": "Wrapping" if line_data.get("lineObjectNumber") == "WRAP" else line_data.get("description", ""),
            "unitPrice": 2.5 if line_data.get("lineObjectNumber") == "WRAP" else 100,
        }

    def update_quote_line(self, quote_id, line_id, etag, data, company_id=None):
        self.updates.append({"id": line_id, "data": dict(data), "etag": etag})
        return {"id": line_id}

    def delete_quote_line(self, quote_id, line_id):
        return None

    def get_sales_quote(self, quote_id):
        return {
            "id": quote_id,
            "number": "SQ-900001",
            "totalAmountExcludingTax": 288.10,
            "totalAmountIncludingTax": 302.51,
        }

    def get_quote_lines(self, quote_id):
        return [
            {
                "id": "line-panel",
                "lineType": "Item",
                "lineObjectNumber": "PN-TEST",
                "description": "Test panel",
                "quantity": 4,
                "unitPrice": 100.0,
                "netAmount": 400.0,
                "@odata.etag": "*",
            },
            {
                "id": "line-wrap",
                "lineType": "Item",
                "lineObjectNumber": "WRAP",
                "description": "Wrapping",
                "quantity": 198,
                "unitPrice": 0.95,
                "netAmount": 188.10,
                "@odata.etag": "*",
            },
        ]

    def set_quote_line_output(self, number, sequence, output=True):
        return None

    def search_items(self, part_number, company_id=None):
        return [{"id": f"item-{part_number}", "unitPrice": 2.5 if part_number == "WRAP" else 100}]


def _install_configurator_mocks(monkeypatch, bc):
    import app.api.door_configurator as door_config

    def _fake_parts(config_dict, spring_inventory=None):
        return {
            "parts_list": [
                {
                    "part_number": "PN-TEST",
                    "description": "Test panel",
                    "quantity": 4,
                    "category": "panel",
                    "unit_price": 100,
                    "notes": None,
                },
                {
                    "part_number": "WRAP",
                    "description": "Wrapping",
                    "quantity": 198,
                    "category": "wrapping",
                    "unit_price": 0.95,
                    "notes": "198 SF",
                },
            ]
        }

    monkeypatch.setattr(door_config, "get_bc_spring_inventory", lambda: {})
    monkeypatch.setattr(door_config, "get_parts_for_door_config", _fake_parts)
    monkeypatch.setattr(door_config, "bc_client", bc)
    monkeypatch.setattr(door_config, "save_quote_snapshot", lambda **kwargs: None)
    monkeypatch.setattr(
        door_config, "resolve_creator_tag",
        lambda *args, **kwargs: ("EMAIL-0001", None, None),
    )
    monkeypatch.setattr(
        "app.services.bc_part_number_mapper.get_bc_mapper",
        lambda: SimpleNamespace(bc_items={
            "PN-TEST": {"displayName": "Test panel"},
            "WRAP": {"displayName": "Wrapping", "unitPrice": 2.5},
        }),
    )


class TestQuotePathsChargeNinetyFiveCents:
    def test_configurator_and_email_patch_wrap_and_leave_other_lines(self, monkeypatch):
        from app.api.door_configurator import (
            DoorConfigRequest,
            QuoteGenerationRequest,
            build_bc_quote_from_doors,
        )

        bc = _RecordingBC()
        _install_configurator_mocks(monkeypatch, bc)
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None

        result = build_bc_quote_from_doors(
            QuoteGenerationRequest(
                doors=[DoorConfigRequest(
                    doorType="residential",
                    doorSeries="KANATA",
                    doorWidth=96,
                    doorHeight=84,
                    panelColor="WHITE",
                    panelDesign="SHXL",
                )],
                deliveryType="pickup",
            ),
            db,
            source="email",
        )

        assert result["success"] is True
        wrap_adds = [ln for ln in bc.added if ln.get("lineObjectNumber") == "WRAP"]
        assert wrap_adds == [{
            "lineType": "Item",
            "lineObjectNumber": "WRAP",
            "description": "Wrapping",
            "quantity": 198,
        }]
        price_patches = [u["data"] for u in bc.updates if "unitPrice" in u["data"]]
        assert price_patches == [{"unitPrice": 0.95}]

    def test_customer_portal_patches_wrap_unit_price(self, monkeypatch):
        import app.api.customer_portal as portal

        bc = _RecordingBC()

        def _fake_parts(config_dict, spring_inventory=None):
            return {
                "parts_list": [{
                    "part_number": "WRAP",
                    "description": "Wrapping",
                    "quantity": 387,
                    "category": "wrapping",
                    "unit_price": 0.95,
                    "notes": None,
                }]
            }

        monkeypatch.setattr(portal, "get_bc_spring_inventory", lambda: {})
        monkeypatch.setattr(portal, "get_parts_for_door_config", _fake_parts)
        monkeypatch.setattr(portal, "bc_client", bc)

        result = portal._generate_bc_quote_with_items(
            doors=[{
                "doorType": "commercial",
                "doorSeries": "TX450",
                "doorWidth": 24 * 12 + 2,
                "doorHeight": 16 * 12,
                "doorCount": 1,
                "panelColor": "WHITE",
                "panelDesign": "UDC",
            }],
            bc_customer_id="11111111-1111-1111-1111-111111111111",
            config_id=1,
            delivery_type="pickup",
        )

        wrap_adds = [ln for ln in bc.added if ln.get("lineObjectNumber") == "WRAP"]
        assert len(wrap_adds) == 1
        assert wrap_adds[0]["quantity"] == 387
        assert {"unitPrice": 0.95} in [u["data"] for u in bc.updates]
        wrap_line = next(
            ln for ln in result["line_pricing"] if ln.get("part_number") == "WRAP"
        )
        assert wrap_line["quantity"] == 387
        assert wrap_line["unit_price"] == 0.95
        assert wrap_line["line_total"] == 367.65

    def test_legacy_quote_service_patches_wrap_only(self):
        from app.services.bc_quote_service import BCQuoteService

        bc = _RecordingBC()
        service = BCQuoteService()
        service.bc_client = bc
        quote_request = SimpleNamespace(quote_items=[
            SimpleNamespace(
                id=1, product_code="WRAP", quantity=198,
                unit_price=0.95, description="Wrapping",
            ),
            SimpleNamespace(
                id=2, product_code="PN-TEST", quantity=4,
                unit_price=100, description="Panel",
            ),
        ])
        service._add_quote_lines(MagicMock(), quote_request, {"id": "quote-1"})
        price_patches = [u["data"] for u in bc.updates if "unitPrice" in u["data"]]
        assert price_patches == [{"unitPrice": 0.95}]
