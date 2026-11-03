"""Door-package wrapping (BC item WRAP) on every quoted steel door.

Upwardor bills wrapping as the door opening in square feet, rounded to the
nearest whole foot (a half rounds up) per door, then multiplied by the door
quantity. Aluminum doors already carry WRAPALU and are not charged again.
Operator-only / parts-only / loose-section orders have no panels and get no
WRAP line. The sell price is $0.95/SF even though the BC item card is $2.50.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.api.customer_portal import (
    LINE_ORDER as PORTAL_LINE_ORDER,
    _edit_bc_quote_lines,
    _estimate_pricing_locally,
    _generate_bc_quote_with_items,
    _sort_parts_by_category as portal_sort,
)
from app.api.door_configurator import (
    LINE_ORDER as CONFIG_LINE_ORDER,
    DoorConfigRequest,
    QuoteGenerationRequest,
    build_bc_quote_from_doors,
    _sort_parts_by_category as config_sort,
)
from app.services.freight_service import allocate_freight_across_doors
from app.services.part_number_service import (
    WRAP_UNIT_PRICE,
    door_needs_wrapping,
    door_wrapping_sqft,
    get_parts_for_door_config,
)


def _wrap(parts):
    rows = [p for p in parts if p.get("part_number") == "WRAP"]
    assert len(rows) <= 1
    return rows[0] if rows else None


def _parts(**overrides):
    base = {
        "doorType": "residential",
        "doorSeries": "KANATA",
        "doorWidth": 108,
        "doorHeight": 84,
        "doorCount": 1,
        "panelColor": "WHITE",
        "panelDesign": "SHXL",
        "hardware": {
            "panels": True,
            "tracks": True,
            "springs": True,
            "struts": True,
            "hardwareKits": True,
            "weatherStripping": True,
            "bottomRetainer": True,
            "shafts": True,
        },
        "targetCycles": 10000,
        "trackThickness": "2",
        "trackRadius": "15",
        "trackMount": "bracket",
        "liftType": "standard",
    }
    base.update(overrides)
    return get_parts_for_door_config(base).get("parts_list", [])


class _RecordingBC:
    """Stand-in that remembers item lines and unitPrice patches.

    BC's item card would fill unitPrice at $2.50 on POST. The portal has to
    PATCH the wrapping line or the quote bills the card price.
    """

    def __init__(self):
        self.added = []
        self.updates = []
        self._n = 0

    def create_sales_quote(self, quote_data, company_id=None):
        return {"id": "quote-wrap", "number": "SQ-WRAP1", "@odata.etag": "*"}

    def update_sales_quote(self, quote_id, quote_data, etag="*", company_id=None):
        return {"id": quote_id, "number": "SQ-WRAP1"}

    def add_quote_line(self, quote_id, line_data):
        self._n += 1
        line_id = f"line-{self._n}"
        row = {"id": line_id, **line_data}
        self.added.append(row)
        return {
            "id": line_id,
            "sequence": self._n * 10000,
            "description": line_data.get("description", ""),
            "lineObjectNumber": line_data.get("lineObjectNumber"),
            "quantity": line_data.get("quantity"),
            "unitPrice": 2.50,
            "@odata.etag": "*",
        }

    def update_quote_line(self, quote_id, line_id, etag, data):
        self.updates.append({"id": line_id, "data": dict(data)})
        return {"id": line_id}

    def set_quote_line_output(self, number, sequence, output=True):
        return None

    def delete_quote_line(self, quote_id, line_id):
        return None

    def get_sales_quote(self, quote_id):
        return {
            "id": quote_id,
            "number": "SQ-WRAP1",
            "@odata.etag": "*",
            "totalAmountExcludingTax": 100.0,
            "totalAmountIncludingTax": 105.0,
        }

    def get_quote_lines(self, quote_id):
        prices = {}
        for update in self.updates:
            if "unitPrice" in update["data"]:
                prices[update["id"]] = update["data"]["unitPrice"]
        lines = []
        for row in self.added:
            if row.get("lineType") != "Item":
                continue
            qty = row.get("quantity") or 0
            price = prices.get(row["id"], 2.50)
            lines.append({
                "id": row["id"],
                "lineType": "Item",
                "lineObjectNumber": row.get("lineObjectNumber"),
                "description": row.get("description"),
                "quantity": qty,
                "unitPrice": price,
                "netAmount": round(float(price) * float(qty), 2),
                "@odata.etag": "*",
            })
        return lines


def _wrap_line(bc: _RecordingBC):
    added = [row for row in bc.added if row.get("lineObjectNumber") == "WRAP"]
    assert len(added) == 1, [row.get("lineObjectNumber") for row in bc.added]
    patches = [
        update["data"].get("unitPrice")
        for update in bc.updates
        if update["id"] == added[0]["id"] and "unitPrice" in update["data"]
    ]
    assert patches == [WRAP_UNIT_PRICE]
    return added[0]


def _install_builder_mocks(monkeypatch):
    import app.api.door_configurator as door_config

    monkeypatch.setattr(door_config, "get_bc_spring_inventory", lambda: {})
    monkeypatch.setattr(
        door_config, "resolve_creator_tag", lambda *args, **kwargs: ("EMAIL-0001", None, None)
    )
    monkeypatch.setattr(door_config, "save_quote_snapshot", lambda *args, **kwargs: None)


# ── Rounding ──────────────────────────────────────────────────────────────

class TestWrappingSqft:
    def test_invoice_examples(self):
        # 14'2" x 14' = 198.333… → 198
        assert door_wrapping_sqft(14 * 12 + 2, 14 * 12) == 198
        # 24'2" x 16' = 386.666… → 387
        assert door_wrapping_sqft(24 * 12 + 2, 16 * 12) == 387
        # 16'2" x 14' = 226.333… → 226 (qty multiply happens later)
        assert door_wrapping_sqft(16 * 12 + 2, 14 * 12) == 226

    def test_inch_width(self):
        # 12'2" x 8' = 97.333… → 97
        assert door_wrapping_sqft(12 * 12 + 2, 8 * 12) == 97

    def test_half_rounds_up_not_bankers(self):
        # 9' x 8'6" = 76.5. Python round() is banker's and returns 76.
        exact_half = (9 * 12) * (8 * 12 + 6) / 144
        assert exact_half == 76.5
        assert round(exact_half) == 76
        assert door_wrapping_sqft(9 * 12, 8 * 12 + 6) == 77

    def test_fraction_under_half_rounds_down(self):
        # 100" x 100" = 69.444… → 69
        assert door_wrapping_sqft(100, 100) == 69

    def test_exact_square_foot_stays(self):
        # 9' x 7' = 63 exactly
        assert door_wrapping_sqft(108, 84) == 63


# ── Who gets a line ───────────────────────────────────────────────────────

class TestWrappingInclusion:
    @pytest.mark.parametrize(
        "door_type,series,design,track",
        [
            ("residential", "KANATA", "SHXL", "2"),
            ("commercial", "TX450", "UDC", "2"),
            ("commercial", "TX500", "FLUSH", "3"),
            ("commercial", "TX380", "UDC", "2"),
        ],
    )
    def test_residential_and_commercial_series(self, door_type, series, design, track):
        parts = _parts(
            doorType=door_type,
            doorSeries=series,
            panelDesign=design,
            trackThickness=track,
            doorWidth=96,
            doorHeight=96,
        )
        wrap = _wrap(parts)
        assert wrap is not None
        assert wrap["description"] == "Wrapping"
        assert wrap["category"] == "wrapping"
        assert wrap["quantity"] == door_wrapping_sqft(96, 96)
        assert wrap["unit_price"] == 0.95
        assert wrap["fixed_unit_price"] == 0.95

    def test_panels_only_still_wraps(self):
        """A door face / panels-only order still ships panels, so it wraps."""
        parts = _parts(hardware={
            "panels": True,
            "bottomRetainer": False,
            "tracks": False,
            "springs": False,
            "struts": False,
            "hardwareKits": False,
            "weatherStripping": False,
            "shafts": False,
        })
        assert _wrap(parts)["quantity"] == 63

    def test_operator_only_is_excluded(self):
        parts = _parts(
            operator="OP20-01056-00",
            hardware={
                "panels": False,
                "tracks": True,
                "springs": True,
                "struts": True,
                "hardwareKits": True,
                "weatherStripping": True,
                "bottomRetainer": True,
                "shafts": True,
            },
        )
        assert _wrap(parts) is None
        assert any(p.get("category") == "operator" for p in parts)

    def test_parts_only_and_loose_sections_are_excluded(self):
        parts = _parts(hardware={
            "panels": False,
            "bottomRetainer": False,
            "tracks": False,
            "springs": False,
            "struts": False,
            "hardwareKits": False,
            "weatherStripping": False,
            "shafts": False,
        })
        assert _wrap(parts) is None
        assert door_needs_wrapping("commercial", {"panels": False}) is False

    def test_aluminum_keeps_wrapalu_and_does_not_add_wrap(self):
        parts = _parts(
            doorType="aluminium",
            doorSeries="AL976",
            panelColor="CLEAR_ANODIZED",
            panelDesign="FLUSH",
            glazingType="glass",
            doorWidth=192,
            doorHeight=96,
        )
        assert _wrap(parts) is None
        wrapalu = [p for p in parts if p.get("part_number") == "WRAPALU"]
        assert len(wrapalu) == 1
        assert wrapalu[0]["category"] == "aluminum_wrapping"

    def test_panorama_is_not_double_charged(self):
        parts = _parts(
            doorType="aluminium",
            doorSeries="PANORAMA",
            panelColor="WHITE",
            panelDesign="FLUSH",
            glazingType="polycarbonate",
            glassColor="CLEAR",
            doorWidth=144,
            doorHeight=96,
        )
        assert _wrap(parts) is None
        assert any(p.get("part_number") == "WRAPALU" for p in parts)


class TestWrappingQuantityAndPrice:
    def test_per_door_rounding_then_quantity(self):
        # 2 x 16'2" x 14' = 226 SF each x 2 = 452, not round(452.666…)
        parts = _parts(
            doorType="commercial",
            doorSeries="TX450",
            panelDesign="UDC",
            trackThickness="3",
            doorWidth=16 * 12 + 2,
            doorHeight=14 * 12,
            doorCount=2,
        )
        wrap = _wrap(parts)
        assert wrap["quantity"] == 452
        assert wrap["fixed_unit_price"] == 0.95
        assert round(wrap["quantity"] * wrap["fixed_unit_price"], 2) == 429.40

    def test_inch_width_on_the_part_line(self):
        # 12'2" x 8' → 97 SF
        parts = _parts(doorWidth=12 * 12 + 2, doorHeight=8 * 12)
        assert _wrap(parts)["quantity"] == 97

    def test_half_up_on_the_part_line(self):
        # 9' x 8'6" → 77 SF, not the banker's 76
        parts = _parts(doorWidth=9 * 12, doorHeight=8 * 12 + 6)
        wrap = _wrap(parts)
        assert wrap["quantity"] == 77
        assert round(77 * 0.95, 2) == 73.15

    def test_fourteen_two_by_fourteen(self):
        parts = _parts(
            doorType="commercial",
            doorSeries="TX450",
            panelDesign="UDC",
            trackThickness="3",
            doorWidth=14 * 12 + 2,
            doorHeight=14 * 12,
        )
        wrap = _wrap(parts)
        assert wrap["quantity"] == 198
        assert round(198 * WRAP_UNIT_PRICE, 2) == 188.10

    def test_wrapping_sorts_last_in_the_door_package(self):
        assert "wrapping" not in CONFIG_LINE_ORDER
        assert "wrapping" not in PORTAL_LINE_ORDER
        raw = _parts()
        for sort in (config_sort, portal_sort):
            categories = [p["category"] for p in sort(raw)]
            assert categories[-1] == "wrapping"
            assert categories.index("operator") < categories.index("wrapping") if "operator" in categories else True
            assert categories.index("panel") < categories.index("retainer") < categories.index("wrapping")


# ── Quote paths actually bill $0.95 ───────────────────────────────────────

def _tx450_door(**overrides):
    door = {
        "doorType": "commercial",
        "doorSeries": "TX450",
        "doorWidth": 14 * 12 + 2,
        "doorHeight": 14 * 12,
        "doorCount": 1,
        "panelColor": "WHITE",
        "panelDesign": "UDC",
        "trackThickness": "3",
        "trackMount": "bracket",
        "liftType": "standard",
    }
    door.update(overrides)
    return door


class TestQuotePathsPriceWrap:
    def test_configurator_and_email_quote_patch_unit_price(self, monkeypatch):
        """Email auto-quote and the door configurator share this builder."""
        import app.api.door_configurator as door_config

        _install_builder_mocks(monkeypatch)
        bc = _RecordingBC()
        monkeypatch.setattr(door_config, "bc_client", bc)

        result = build_bc_quote_from_doors(
            QuoteGenerationRequest(
                doors=[DoorConfigRequest(**_tx450_door())],
                deliveryType="pickup",
            ),
            db=None,
            source="email",
        )
        assert result["success"] is True, result
        line = _wrap_line(bc)
        assert line["quantity"] == 198
        assert line["description"] == "Wrapping"
        # No other catalog line is forced off BC's price.
        other_prices = [
            update["data"].get("unitPrice")
            for update in bc.updates
            if update["id"] != line["id"] and "unitPrice" in update["data"]
        ]
        assert other_prices == []
        priced = next(
            row for row in result["data"]["line_pricing"] if row["part_number"] == "WRAP"
        )
        assert priced["unit_price"] == 0.95
        assert priced["quantity"] == 198
        assert round(priced["unit_price"] * priced["quantity"], 2) == 188.10

    def test_customer_portal_quote_patches_unit_price(self, monkeypatch):
        import app.api.customer_portal as portal

        monkeypatch.setattr(portal, "get_bc_spring_inventory", lambda: {})
        bc = _RecordingBC()
        monkeypatch.setattr(portal, "bc_client", bc)

        result = _generate_bc_quote_with_items(
            doors=[_tx450_door(doorCount=2, doorWidth=16 * 12 + 2, doorHeight=14 * 12)],
            bc_customer_id="C-WRAP",
            config_id=1,
            db=None,
            delivery_type="pickup",
        )
        line = _wrap_line(bc)
        assert line["quantity"] == 452
        priced = next(
            row for row in result["line_pricing"] if row["part_number"] == "WRAP"
        )
        assert priced["unit_price"] == 0.95
        assert priced["quantity"] == 452
        assert priced["line_total"] == 429.40

    def test_customer_portal_edit_reapplies_unit_price(self, monkeypatch):
        import app.api.customer_portal as portal

        monkeypatch.setattr(portal, "get_bc_spring_inventory", lambda: {})
        bc = _RecordingBC()
        monkeypatch.setattr(portal, "bc_client", bc)
        config = SimpleNamespace(
            bc_quote_id="quote-wrap",
            bc_quote_number="SQ-WRAP1",
            config_data={"doors": []},
            bc_line_map=None,
        )
        _edit_bc_quote_lines(
            config,
            {"doors": [_tx450_door(doorWidth=12 * 12 + 2, doorHeight=8 * 12)]},
            bc_customer_id="C-WRAP",
            pricing_tier="retail",
            db=None,
            customer_user_id=None,
            delivery_type="pickup",
        )
        line = _wrap_line(bc)
        assert line["quantity"] == 97
        assert round(97 * 0.95, 2) == 92.15

    def test_local_estimate_uses_fixed_rate_not_card_margin(self, monkeypatch):
        import app.api.customer_portal as portal

        monkeypatch.setattr(portal, "get_bc_spring_inventory", lambda: {})
        monkeypatch.setattr(portal, "warm_bc_cost_cache", lambda *args, **kwargs: None)
        monkeypatch.setattr(portal, "calculate_selling_price", lambda **kwargs: 12.34)
        monkeypatch.setattr(
            portal,
            "calculate_freight",
            lambda **kwargs: {"skip": True, "amount": 0, "rate": 0, "description": "Pickup"},
        )
        result = _estimate_pricing_locally(
            doors=[_tx450_door()],
            pricing_tier="retail",
            config_id=1,
            db=None,
            delivery_type="pickup",
        )
        priced = next(
            row for row in result["line_pricing"] if row["part_number"] == "WRAP"
        )
        assert priced["unit_price"] == 0.95
        assert priced["quantity"] == 198
        assert priced["line_total"] == 188.10
        # Other lines still go through the margin engine (stubbed here).
        panel = next(
            row for row in result["line_pricing"]
            if row["line_type"] == "Item" and row["part_number"] != "WRAP"
        )
        assert panel["unit_price"] == 12.34


def _freight_calc(product_subtotal, province, delivery_type, db):
    if (delivery_type or "").lower() == "pickup":
        return {"skip": True, "amount": 0, "rate": 0, "description": "Pickup - No Freight"}
    amount = round(float(product_subtotal) * 0.10, 2)
    return {"skip": False, "amount": amount, "rate": 10, "description": "Freight (10%)"}


def _final_unit_prices(bc):
    prices = {}
    for update in bc.updates:
        if "unitPrice" in update["data"]:
            prices[update["id"]] = update["data"]["unitPrice"]
    return prices


def _item_numbers(bc):
    return [
        row.get("lineObjectNumber")
        for row in bc.added
        if row.get("lineType") == "Item"
    ]


class TestFreightFollowsWrap:
    def test_allocate_splits_the_quote_total_and_fixes_the_penny(self):
        assert allocate_freight_across_doors([100, 300], 40) == [10.0, 30.0]
        shares = allocate_freight_across_doors([1, 1, 1], 10)
        assert shares == [3.33, 3.33, 3.34]
        assert round(sum(shares), 2) == 10.00

    def test_single_door_quote_is_wrap_then_freight(self, monkeypatch):
        import app.api.door_configurator as door_config

        _install_builder_mocks(monkeypatch)
        monkeypatch.setattr(door_config, "calculate_freight", _freight_calc)
        bc = _RecordingBC()
        monkeypatch.setattr(door_config, "bc_client", bc)

        result = build_bc_quote_from_doors(
            QuoteGenerationRequest(
                doors=[DoorConfigRequest(**_tx450_door())],
                deliveryType="delivery",
            ),
            db=None,
            source="email",
        )
        assert result["success"] is True, result
        numbers = _item_numbers(bc)
        assert numbers[-2:] == ["WRAP", "FREIGHT"]
        prices = _final_unit_prices(bc)
        wrap = next(row for row in bc.added if row.get("lineObjectNumber") == "WRAP")
        freight = next(row for row in bc.added if row.get("lineObjectNumber") == "FREIGHT")
        assert prices[wrap["id"]] == 0.95
        assert wrap["quantity"] == 198
        # Fake BC subtotal is $100, so the quote freight is 10%.
        assert prices[freight["id"]] == 10.0
        priced = [row for row in result["data"]["line_pricing"] if row["part_number"] in ("WRAP", "FREIGHT")]
        assert [row["part_number"] for row in priced][-2:] == ["WRAP", "FREIGHT"]
        assert priced[-1]["unit_price"] == 10.0
        assert priced[-1]["description"] == "Freight (10%)"

    def test_multi_door_quote_puts_freight_under_each_wrap(self, monkeypatch):
        import app.api.customer_portal as portal

        monkeypatch.setattr(portal, "get_bc_spring_inventory", lambda: {})
        monkeypatch.setattr(portal, "calculate_freight", _freight_calc)
        bc = _RecordingBC()
        monkeypatch.setattr(portal, "bc_client", bc)

        result = _generate_bc_quote_with_items(
            doors=[
                _tx450_door(),
                _tx450_door(doorWidth=16 * 12 + 2, doorHeight=14 * 12, doorCount=2),
            ],
            bc_customer_id="C-WRAP",
            config_id=1,
            db=None,
            delivery_type="delivery",
        )
        numbers = _item_numbers(bc)
        wrap_at = [i for i, pn in enumerate(numbers) if pn == "WRAP"]
        assert len(wrap_at) == 2
        for index in wrap_at:
            assert numbers[index + 1] == "FREIGHT"
        # Nothing after the second freight. Each door ended wrap -> freight.
        assert numbers[-1] == "FREIGHT"
        prices = _final_unit_prices(bc)
        freight_prices = [
            prices[row["id"]]
            for row in bc.added
            if row.get("lineObjectNumber") == "FREIGHT"
        ]
        assert freight_prices[0] > 0 and freight_prices[1] > 0
        assert round(sum(freight_prices), 2) == 10.0
        assert freight_prices[0] != freight_prices[1]
        view = [
            (row["part_number"], row["description"])
            for row in result["line_pricing"]
            if row["part_number"] in ("WRAP", "FREIGHT")
        ]
        assert view == [
            ("WRAP", "Wrapping"),
            ("FREIGHT", "Freight (10%)"),
            ("WRAP", "Wrapping"),
            ("FREIGHT", "Freight (10%)"),
        ]
        wrap_rows = [row for row in result["line_pricing"] if row["part_number"] == "WRAP"]
        assert wrap_rows[0]["quantity"] == 198
        assert wrap_rows[0]["unit_price"] == 0.95
        assert wrap_rows[1]["quantity"] == 452
        assert wrap_rows[1]["unit_price"] == 0.95

    def test_pickup_multi_door_ends_each_package_on_wrap(self, monkeypatch):
        import app.api.door_configurator as door_config

        _install_builder_mocks(monkeypatch)
        bc = _RecordingBC()
        monkeypatch.setattr(door_config, "bc_client", bc)
        result = build_bc_quote_from_doors(
            QuoteGenerationRequest(
                doors=[
                    DoorConfigRequest(**_tx450_door()),
                    DoorConfigRequest(**_tx450_door(
                        doorSeries="TX500", panelDesign="UDC", trackThickness="3",
                        doorWidth=10 * 12, doorHeight=10 * 12,
                    )),
                ],
                deliveryType="pickup",
            ),
            db=None,
            source="admin",
        )
        assert result["success"] is True, result
        assert "FREIGHT" not in _item_numbers(bc)
        # Walk posted lines. Each door header starts a package; its last item is WRAP.
        packages = []
        current = []
        for row in bc.added:
            desc = row.get("description") or ""
            if row.get("lineType") == "Comment" and desc.startswith("("):
                if current:
                    packages.append(current)
                current = []
            elif row.get("lineType") == "Item":
                current.append(row.get("lineObjectNumber"))
        if current:
            packages.append(current)
        assert len(packages) == 2
        assert packages[0][-1] == "WRAP"
        assert packages[1][-1] == "WRAP"
        assert "WRAPALU" not in _item_numbers(bc)
