"""One freight line for the order, plus staff price and freight overrides."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.api.door_configurator import (
    DoorConfigRequest,
    LinePriceOverride,
    QuoteGenerationRequest,
    build_bc_quote_from_doors,
)
from app.services.freight_service import calculate_freight, get_default_freight_config
from app.services.quote_adjustments import (
    FREIGHT_ESTIMATE_NOTE,
    below_cost_warnings,
    dropped_price_overrides,
    price_change_warnings,
)
from app.services.quote_line_layout import arrange_quote_lines


def _tx450(**overrides):
    door = {
        "doorType": "commercial",
        "doorSeries": "TX450",
        "doorWidth": 14 * 12 + 2,
        "doorHeight": 14 * 12,
        "doorCount": 1,
        "panelColor": "WHITE",
        "panelDesign": "UDC",
        "trackThickness": "2",
        "trackMount": "bracket",
        "liftType": "standard",
    }
    door.update(overrides)
    return door


class _RecordingBC:
    def __init__(self):
        self.added = []
        self.updates = []
        self.output = []
        self.deleted = []
        self._n = 0
        self.previous_lines = None

    def create_sales_quote(self, quote_data, company_id=None):
        return {"id": "quote-1", "number": "SQ-000001", "@odata.etag": "*"}

    def get_sales_quote(self, quote_id):
        return {
            "id": quote_id,
            "number": "SQ-000001",
            "@odata.etag": "*",
            "totalAmountExcludingTax": 100.0,
            "totalAmountIncludingTax": 105.0,
        }

    def update_sales_quote(self, quote_id, quote_data, etag="*", company_id=None):
        return {"id": quote_id, "number": "SQ-000001"}

    def add_quote_line(self, quote_id, line_data):
        self._n += 1
        line_id = f"line-{self._n}"
        row = {"id": line_id, "sequence": self._n * 10000, **line_data}
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
        self.output.append((sequence, output))

    def delete_quote_line(self, quote_id, line_id):
        self.deleted.append(line_id)

    def get_quote_lines(self, quote_id):
        if self.previous_lines is not None and not self.deleted:
            # First read is the quote being regenerated, before its lines are cleared.
            if not any(row.get("id") == "old-wrap" for row in self.added):
                return self.previous_lines
        prices = {}
        descriptions = {}
        for update in self.updates:
            if "unitPrice" in update["data"]:
                prices[update["id"]] = update["data"]["unitPrice"]
            if "description" in update["data"]:
                descriptions[update["id"]] = update["data"]["description"]
        lines = []
        for row in self.added:
            if row.get("id") in self.deleted or row.get("lineType") != "Item":
                continue
            qty = row.get("quantity") or 0
            price = prices.get(row["id"], 2.50)
            lines.append({
                "id": row["id"],
                "lineType": "Item",
                "lineObjectNumber": row.get("lineObjectNumber"),
                "description": descriptions.get(row["id"], row.get("description")),
                "quantity": qty,
                "unitPrice": price,
                "@odata.etag": "*",
            })
        return lines


class _CustomerDB:
    """Enough of a session for the freight province lookup and the settings reads."""

    def __init__(self, province):
        self.province = province

    def query(self, model):
        self._model = getattr(model, "__name__", "")
        return self

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        if self._model in {"User", "AppSettings"}:
            return None
        return SimpleNamespace(
            address={"province": self.province},
            pricing_tier="retail",
            bc_price_group=None,
            setting_value=None,
        )

    def get_bind(self):
        raise RuntimeError("no database")


def _install(monkeypatch):
    import app.api.door_configurator as door_config

    monkeypatch.setattr(door_config, "get_bc_spring_inventory", lambda: {})
    monkeypatch.setattr(door_config, "resolve_creator_tag", lambda *args, **kwargs: ("EMAIL-0001", None, None))
    monkeypatch.setattr(door_config, "save_quote_snapshot", lambda *args, **kwargs: None)
    return door_config


def _build(monkeypatch, bc, db=None, **request):
    door_config = _install(monkeypatch)
    monkeypatch.setattr(door_config, "bc_client", bc)
    doors = request.pop("doors", [_tx450()])
    result = build_bc_quote_from_doors(
        QuoteGenerationRequest(
            doors=[DoorConfigRequest(**door) for door in doors],
            deliveryType=request.pop("deliveryType", "delivery"),
            **request,
        ),
        db=db,
        source="admin",
    )
    assert result["success"] is True, result
    return result


def _build_with_db(monkeypatch, bc, db, **request):
    door_config = _install(monkeypatch)
    monkeypatch.setattr(door_config, "bc_client", bc)
    doors = request.pop("doors", [_tx450(), _tx450(doorWidth=10 * 12, doorHeight=8 * 12)])
    result = build_bc_quote_from_doors(
        QuoteGenerationRequest(
            doors=[DoorConfigRequest(**door) for door in doors],
            **request,
        ),
        db=db,
        source="admin",
    )
    assert result["success"] is True, result
    return result


def _prices(bc):
    prices = {}
    for update in bc.updates:
        if "unitPrice" in update["data"]:
            prices[update["id"]] = update["data"]["unitPrice"]
    return prices


def _freight_item(bc):
    return next(row for row in bc.added if row.get("lineObjectNumber") == "FREIGHT")


class TestSingleFreightLine:
    def test_two_doors_keep_wrap_and_put_one_freight_last(self):
        ordered = arrange_quote_lines(
            [
                {"lineType": "Comment", "description": "(1) door", "is_door_desc": True, "door_index": 1},
                {"lineType": "Item", "part_number": "PN45", "door_index": 1, "category": "panel"},
                {"lineType": "Item", "part_number": "WRAP", "door_index": 1, "category": "wrapping"},
                {"lineType": "Comment", "description": "(2) door", "is_door_desc": True, "door_index": 2},
                {"lineType": "Item", "part_number": "PN45", "door_index": 2, "category": "panel"},
                {"lineType": "Item", "part_number": "WRAP", "door_index": 2, "category": "wrapping"},
            ],
            layout_v2=False,
            include_freight=True,
        )
        numbers = [line.get("part_number") for line in ordered]
        assert numbers.count("FREIGHT") == 1
        assert numbers[-1] == "FREIGHT"
        wrap_at = [i for i, number in enumerate(numbers) if number == "WRAP"]
        assert numbers[wrap_at[0] + 1] != "FREIGHT"
        assert ordered[-1]["description"] == "Freight (estimate)"

    def test_default_nine_percent_is_one_bottom_line(self, monkeypatch):
        bc = _RecordingBC()
        db = _CustomerDB(None)
        result = _build(monkeypatch, bc, db=db, doors=[_tx450(), _tx450(doorWidth=16 * 12)])
        expected = calculate_freight(100.0, None, "delivery", db)
        assert expected["amount"] == 9.0
        assert expected["rate"] == 9.0
        freight = _freight_item(bc)
        assert _prices(bc)[freight["id"]] == 9.0
        assert sum(1 for row in bc.added if row.get("lineObjectNumber") == "FREIGHT") == 1
        assert bc.added[-1]["description"] == FREIGHT_ESTIMATE_NOTE
        assert result["data"]["freight"]["amount"] == 9.0
        assert result["data"]["freight"]["description"] == "Freight (estimate)"

    def test_alberta_seven_percent_is_the_full_amount_not_a_split(self, monkeypatch):
        bc = _RecordingBC()
        db = _CustomerDB("AB")
        result = _build_with_db(
            monkeypatch, bc, db,
            customerId="ED-001",
            deliveryType="delivery",
        )
        assert get_default_freight_config()["province_overrides"]["AB"] == 7.0
        assert calculate_freight(100.0, "AB", "delivery", db)["amount"] == 7.0
        freight = _freight_item(bc)
        assert _prices(bc)[freight["id"]] == 7.0
        assert sum(1 for row in bc.added if row.get("lineObjectNumber") == "FREIGHT") == 1
        assert result["data"]["freight"]["amount"] == 7.0
        # 7% of the $100 product subtotal, once, not once per door.
        assert result["data"]["freight"]["rate"] == 7.0

    def test_staff_can_override_the_freight_amount(self, monkeypatch):
        bc = _RecordingBC()
        result = _build(monkeypatch, bc, db=_CustomerDB(None), freightAmount=7276.47)
        freight = _freight_item(bc)
        assert _prices(bc)[freight["id"]] == 7276.47
        descriptions = [
            update["data"].get("description")
            for update in bc.updates
            if update["id"] == freight["id"] and "description" in update["data"]
        ]
        assert descriptions[-1] == "Freight (estimate)"
        assert result["data"]["freight"]["overridden"] is True
        assert bc.added[-1]["description"] == FREIGHT_ESTIMATE_NOTE


class TestLinePriceOverrides:
    def test_override_is_patched_onto_the_bc_line(self, monkeypatch):
        bc = _RecordingBC()
        result = _build(
            monkeypatch, bc,
            linePriceOverrides=[LinePriceOverride(partNumber="WRAP", unitPrice=28.30)],
        )
        wrap = next(row for row in bc.added if row.get("lineObjectNumber") == "WRAP")
        assert _prices(bc)[wrap["id"]] == 28.30
        priced = next(row for row in result["data"]["line_pricing"] if row["part_number"] == "WRAP")
        assert priced["unit_price"] == 28.30
        assert priced["price_overridden"] is True

    def test_missing_part_is_reported_instead_of_dropped_quietly(self, monkeypatch):
        bc = _RecordingBC()
        result = _build(
            monkeypatch, bc,
            linePriceOverrides=[
                LinePriceOverride(partNumber="SP12-00231-00", unitPrice=28.30),
            ],
        )
        dropped = result["data"]["dropped_price_overrides"]
        assert dropped[0]["part_number"] == "SP12-00231-00"
        assert "not applied" in dropped[0]["message"]

    def test_regenerate_warns_when_a_previous_price_is_not_sent_again(self, monkeypatch):
        bc = _RecordingBC()
        bc.previous_lines = [{
            "id": "old-wrap",
            "lineType": "Item",
            "lineObjectNumber": "WRAP",
            "description": "Wrapping",
            "quantity": 198,
            "unitPrice": 28.30,
        }]
        result = _build(monkeypatch, bc, bcQuoteId="quote-1")
        warnings = result["data"]["price_override_warnings"]
        assert any(row["part_number"] == "WRAP" and row["previous_unit_price"] == 28.30 for row in warnings)
        assert "Set a price override" in warnings[0]["message"]

    def test_below_cost_warning_includes_auto_and_overridden_prices(self, monkeypatch):
        import app.services.quote_adjustments as adjustments

        def _cost(part_number):
            if part_number == "WRAP":
                return {"unitCost": 30.0}
            if part_number == "SP12-00231-00":
                return {"unitCost": 40.0}
            return {"unitCost": 1.0}

        monkeypatch.setattr(adjustments, "_get_live_item", _cost, raising=False)
        # below_cost_warnings imports the helper inside the function.
        import app.services.pricing_service as pricing
        monkeypatch.setattr(pricing, "_get_live_item", _cost)

        warnings = below_cost_warnings([
            {"part_number": "WRAP", "unit_price": 0.95, "description": "Wrapping"},
            {"part_number": "SP12-00231-00", "unit_price": 28.30, "price_overridden": True},
            {"part_number": "PN45", "unit_price": 12.0},
            {"part_number": "FREIGHT", "unit_price": 9.0},
        ])
        by_part = {row["part_number"]: row for row in warnings}
        assert by_part["WRAP"]["unit_cost"] == 30.0
        assert by_part["SP12-00231-00"]["overridden"] is True
        assert "PN45" not in by_part
        assert "FREIGHT" not in by_part

    def test_builder_returns_the_below_cost_warning(self, monkeypatch):
        import app.services.pricing_service as pricing
        monkeypatch.setattr(pricing, "_get_live_item", lambda part: {"unitCost": 50.0, "generalProductPostingGroupCode": ""})
        bc = _RecordingBC()
        result = _build(monkeypatch, bc)
        warned = {row["part_number"] for row in result["data"]["below_cost_warnings"]}
        assert "WRAP" in warned
        wrap = next(row for row in result["data"]["below_cost_warnings"] if row["part_number"] == "WRAP")
        assert wrap["unit_price"] < wrap["unit_cost"]


def test_dropped_override_helper_names_the_missing_part():
    dropped = dropped_price_overrides(
        [{"part_number": "SP12-00237-00", "unit_price": 28.30, "door_index": None}],
        [{"lineType": "Item", "part_number": "WRAP", "door_index": 1}],
    )
    assert dropped[0]["part_number"] == "SP12-00237-00"


def test_price_change_warning_stays_quiet_when_the_override_is_sent():
    warnings = price_change_warnings(
        [{"part_number": "SP12-00231-00", "unit_price": 28.30, "door_index": 1}],
        [{"part_number": "SP12-00231-00", "unit_price": 28.30}],
        [{"part_number": "SP12-00231-00", "unit_price": 28.30, "door_index": None}],
    )
    assert warnings == []


def test_price_change_warning_when_the_part_disappears():
    warnings = price_change_warnings(
        [{"part_number": "SP12-00231-00", "unit_price": 28.30, "door_index": 2}],
        [{"part_number": "WRAP", "unit_price": 0.95}],
        [],
    )
    assert "not on this one" in warnings[0]["message"]
