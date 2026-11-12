"""Quote line layout v2.

Off (the default) keeps one FREIGHT line under every door, right after that
door's WRAP, and every operator line — including the chain rail — gets its
own Output check mark.

On (AppSettings ``quote_line_layout_v2``):

* one WRAP inside each door package, so the package subtotal includes it
* operators and add-ons after every package, with no wrapping of their own
* the chain/belt rail shares the operator head's subtotal
* exactly one FREIGHT line, and it is the last line

Before (flag off), a 10' x 8' door with a chain-drive operator plus a
panels-only ``(2) 12'2" x 14'0"`` package::

    (1) 10'0" x 8'0" ...          [Output]
      panels / hardware
      operator head               [Output]
      photo eye                   [Output]
      8' chain rail               [Output]
      WRAP
      FREIGHT                     [Output]
    (2) 12'2" x 14'0" ... PANELS ONLY   [Output]
      panels
      WRAP                        combined qty, one line
      FREIGHT                     [Output]

After (flag on)::

    (1) 10'0" x 8'0" ...          [Output]
      panels / hardware
      WRAP                        inside the door subtotal
    (2) 12'2" x 14'0" ... PANELS ONLY   [Output]
      panels
      WRAP                        combined qty, one line, inside the package
    operator head                 [Output]
      8' chain rail               no check mark — one operator subtotal
    photo eye                     [Output]
    FREIGHT                       [Output]  one line, last
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.part_number_service import door_wrapping_sqft
from app.services.quote_line_layout import (
    QUOTE_LINE_LAYOUT_V2,
    arrange_quote_lines,
    group_operator_with_rails,
    is_operator_rail,
    line_needs_output,
    quote_line_layout_v2_enabled,
    set_quote_line_layout_v2,
)

HEAD = "OP19-01118-00"
RAIL_8 = "OP19-02005-00"
PHOTO = "OP19-02097-00"


def _header(index, description):
    return {
        "lineType": "Comment",
        "description": description,
        "category": "COMMENT",
        "door_index": index,
        "is_door_desc": True,
    }


def _item(part_number, description, category, door_index, quantity=1):
    return {
        "lineType": "Item",
        "part_number": part_number,
        "description": description,
        "category": category,
        "door_index": door_index,
        "quantity": quantity,
    }


def _sample_lines():
    """Two packages: a chain-drive door, then a panels-only pair."""
    return [
        _header(1, '(1) 10\'0" x 8\'0" TX450, WHITE, UDC, 2" BRACKET MOUNT, STD LIFT'),
        _item("PN45-21000-1000", "TX450 SECTION", "panel", 1, 4),
        _item(HEAD, "LiftMaster 2220L Basic 3/4HP DC Chain Drive Camera WiFi", "operator", 1),
        _item(PHOTO, "LiftMaster CPS-RPEN4 Reflective Photo Eyes", "operator", 1),
        _item(RAIL_8, "LiftMaster 8ft Full Chain Rail 1708LM", "operator", 1),
        _item("WRAP", "Wrapping", "wrapping", 1, 80),
        _header(2, '(2) 12\'2" x 14\'0" TX450, WHITE, UDC, PANELS ONLY'),
        _item("PN45-21000-1202", "TX450 SECTION", "panel", 2, 8),
        _item("WRAP", "Wrapping", "wrapping", 2, 340),
    ]


def _marks(lines, *, layout_v2):
    return [line_needs_output(line, layout_v2=layout_v2) for line in lines]


def _labels(lines):
    labels = []
    for line in lines:
        if line.get("is_door_desc"):
            labels.append(line["description"])
        else:
            labels.append(line.get("part_number"))
    return labels


class TestFlagDefaultsOff:
    def test_missing_db_is_off(self):
        assert quote_line_layout_v2_enabled(None) is False

    def test_round_trip(self):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from sqlalchemy.pool import StaticPool
        from app.db.models import AppSettings

        engine = create_engine(
            "sqlite://",
            future=True,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        AppSettings.__table__.create(engine)
        db = sessionmaker(bind=engine, autoflush=False, autocommit=False)()
        try:
            assert quote_line_layout_v2_enabled(db) is False
            assert set_quote_line_layout_v2(db, True) == "on"
            assert quote_line_layout_v2_enabled(db) is True
            stored = db.query(AppSettings).filter(
                AppSettings.setting_key == QUOTE_LINE_LAYOUT_V2
            ).one()
            assert stored.setting_value == "on"
            assert set_quote_line_layout_v2(db, False) == "off"
            assert quote_line_layout_v2_enabled(db) is False
        finally:
            db.close()


class TestArrangeRules:
    def test_flag_off_keeps_freight_under_each_door_and_checks_the_rail(self):
        ordered = arrange_quote_lines(
            _sample_lines(), layout_v2=False, include_freight=True,
        )
        assert _labels(ordered) == [
            '(1) 10\'0" x 8\'0" TX450, WHITE, UDC, 2" BRACKET MOUNT, STD LIFT',
            "PN45-21000-1000",
            HEAD,
            PHOTO,
            RAIL_8,
            "WRAP",
            "FREIGHT",
            '(2) 12\'2" x 14\'0" TX450, WHITE, UDC, PANELS ONLY',
            "PN45-21000-1202",
            "WRAP",
            "FREIGHT",
        ]
        checked = [
            line.get("part_number") or "DOOR"
            for line, mark in zip(ordered, _marks(ordered, layout_v2=False))
            if mark
        ]
        assert checked == ["DOOR", HEAD, PHOTO, RAIL_8, "DOOR"]
        # Freight's check mark is applied when the line is priced, not here.
        assert all(line.get("is_door_freight") for line in ordered if line.get("part_number") == "FREIGHT")

    def test_single_door_wrap_then_one_freight(self):
        lines = [
            _header(1, '(1) 14\'2" x 14\'0" TX450, WHITE, UDC'),
            _item("PN45-21000-1402", "TX450 SECTION", "panel", 1, 7),
            _item("WRAP", "Wrapping", "wrapping", 1, 198),
        ]
        ordered = arrange_quote_lines(lines, layout_v2=True, include_freight=True)
        assert _labels(ordered) == [
            '(1) 14\'2" x 14\'0" TX450, WHITE, UDC',
            "PN45-21000-1402",
            "WRAP",
            "FREIGHT",
        ]
        assert sum(1 for line in ordered if line.get("part_number") == "FREIGHT") == 1
        assert ordered[-1]["part_number"] == "FREIGHT"
        assert _marks(ordered, layout_v2=True) == [True, False, False, False]

    def test_multi_door_package_keeps_one_combined_wrap_inside_the_group(self):
        per_door = door_wrapping_sqft(12 * 12 + 2, 14 * 12)
        lines = [
            _header(1, '(2) 12\'2" x 14\'0" TX450, WHITE, UDC'),
            _item("PN45-21000-1202", "TX450 SECTION", "panel", 1, 8),
            _item("WRAP", "Wrapping", "wrapping", 1, per_door * 2),
        ]
        ordered = arrange_quote_lines(lines, layout_v2=True, include_freight=True)
        wraps = [line for line in ordered if line.get("part_number") == "WRAP"]
        assert len(wraps) == 1
        assert wraps[0]["quantity"] == per_door * 2
        # Wrap sits after the panels and before the single freight line,
        # with no check mark of its own, so the door subtotal includes it.
        assert _labels(ordered)[-3:] == ["PN45-21000-1202", "WRAP", "FREIGHT"]
        wrap_mark = line_needs_output(wraps[0], layout_v2=True)
        assert wrap_mark is False
        assert ordered[-1]["door_index"] is None

    def test_packages_operator_rail_and_panels_only(self):
        ordered = arrange_quote_lines(
            _sample_lines(), layout_v2=True, include_freight=True,
        )
        assert _labels(ordered) == [
            '(1) 10\'0" x 8\'0" TX450, WHITE, UDC, 2" BRACKET MOUNT, STD LIFT',
            "PN45-21000-1000",
            "WRAP",
            '(2) 12\'2" x 14\'0" TX450, WHITE, UDC, PANELS ONLY',
            "PN45-21000-1202",
            "WRAP",
            HEAD,
            RAIL_8,
            PHOTO,
            "FREIGHT",
        ]
        assert sum(1 for line in ordered if line.get("part_number") == "FREIGHT") == 1
        assert ordered[-1]["part_number"] == "FREIGHT"
        assert ordered[-1]["description"] == "Freight"
        # One wrap per package, including the panels-only package. The
        # operator group has none.
        assert [line["quantity"] for line in ordered if line.get("part_number") == "WRAP"] == [80, 340]
        marks = {
            (line.get("part_number") or "DOOR"): mark
            for line, mark in zip(ordered, _marks(ordered, layout_v2=True))
        }
        assert marks["DOOR"] is True
        assert marks["WRAP"] is False
        assert marks[HEAD] is True
        assert marks[RAIL_8] is False
        assert marks[PHOTO] is True
        assert marks["FREIGHT"] is False
        rail = next(line for line in ordered if line.get("part_number") == RAIL_8)
        assert rail["suppress_output"] is True
        # Rail follows the head with nothing checked between them.
        labels = _labels(ordered)
        assert labels[labels.index(HEAD) + 1] == RAIL_8

    def test_pickup_has_no_freight_and_still_lifts_the_operator(self):
        ordered = arrange_quote_lines(
            _sample_lines(), layout_v2=True, include_freight=False,
        )
        assert "FREIGHT" not in _labels(ordered)
        assert _labels(ordered)[-3:] == [HEAD, RAIL_8, PHOTO]
        assert _labels(ordered)[2] == "WRAP"

    def test_six_foot_rail_groups_with_the_head(self):
        six = _item("OP-CUSTOM-6", "6' chain rail", "operator", 1)
        assert is_operator_rail(six) is True
        grouped = group_operator_with_rails([
            _item(HEAD, "Chain Drive operator", "operator", 1),
            _item(PHOTO, "Photo eyes", "operator", 1),
            six,
        ])
        assert [line["part_number"] for line in grouped] == [HEAD, "OP-CUSTOM-6", PHOTO]
        assert grouped[1]["suppress_output"] is True
        assert line_needs_output(grouped[1], layout_v2=True) is False

    def test_rail_without_a_head_keeps_its_own_subtotal(self):
        rail = _item(RAIL_8, "8ft Full Chain Rail", "operator", 1)
        grouped = group_operator_with_rails([rail])
        assert grouped[0] is rail
        assert line_needs_output(rail, layout_v2=True) is True

    def test_aluminum_section_rail_stays_in_the_door(self):
        male = _item("AL-RAIL", "MALE RAIL AL976, A-29046-B, MILL", "aluminum_section", 1)
        assert is_operator_rail(male) is False
        ordered = arrange_quote_lines(
            [
                _header(1, "(1) 16'0\" x 8'0\" AL976"),
                male,
                _item("WRAPALU", "WRAPPING - ALUMINUM PANELS", "aluminum_wrapping", 1),
            ],
            layout_v2=True,
            include_freight=True,
        )
        assert _labels(ordered) == [
            "(1) 16'0\" x 8'0\" AL976",
            "AL-RAIL",
            "WRAPALU",
            "FREIGHT",
        ]

    def test_flag_off_does_not_move_operators(self):
        ordered = arrange_quote_lines(
            _sample_lines(), layout_v2=False, include_freight=False,
        )
        assert _labels(ordered) == _labels(_sample_lines())


# ── Builders actually post this order when the flag is on ────────────────


def _freight_calc(product_subtotal, province, delivery_type, db):
    if (delivery_type or "").lower() == "pickup":
        return {"skip": True, "amount": 0, "rate": 0, "description": "Pickup - No Freight"}
    amount = round(float(product_subtotal) * 0.10, 2)
    return {"skip": False, "amount": amount, "rate": 10.0, "description": "Freight (10%)"}


class _RecordingBC:
    def __init__(self):
        self.added = []
        self.updates = []
        self.output = []
        self._n = 0

    def create_sales_quote(self, quote_data, company_id=None):
        return {"id": "quote-layout", "number": "SQ-LAYOUT", "@odata.etag": "*"}

    def update_sales_quote(self, quote_id, quote_data, etag="*", company_id=None):
        return {"id": quote_id, "number": "SQ-LAYOUT"}

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
        return None

    def get_sales_quote(self, quote_id):
        return {
            "id": quote_id,
            "number": "SQ-LAYOUT",
            "@odata.etag": "*",
            "totalAmountExcludingTax": 100.0,
            "totalAmountIncludingTax": 105.0,
        }

    def get_quote_lines(self, quote_id):
        prices = {}
        descriptions = {}
        for update in self.updates:
            if "unitPrice" in update["data"]:
                prices[update["id"]] = update["data"]["unitPrice"]
            if "description" in update["data"]:
                descriptions[update["id"]] = update["data"]["description"]
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
                "description": descriptions.get(row["id"], row.get("description")),
                "quantity": qty,
                "unitPrice": price,
                "netAmount": round(float(price) * float(qty), 2),
                "@odata.etag": "*",
            })
        return lines

    def skeleton(self):
        rows = []
        checked = {seq for seq, output in self.output if output}
        for row in self.added:
            number = row.get("lineObjectNumber")
            desc = row.get("description") or ""
            mark = " [Output]" if row.get("sequence") in checked else ""
            if row.get("lineType") == "Comment" and desc.startswith("("):
                rows.append(f"DOOR {desc}{mark}")
            elif number in {HEAD, RAIL_8, PHOTO, "WRAP", "FREIGHT"}:
                rows.append(f"{number}{mark}")
        return rows


def _enable_v2(monkeypatch, enabled=True):
    monkeypatch.setattr(
        "app.services.quote_line_layout.quote_line_layout_v2_enabled",
        lambda db: enabled,
    )


def _tx450(**overrides):
    door = {
        "doorType": "commercial",
        "doorSeries": "TX450",
        "doorWidth": 10 * 12,
        "doorHeight": 8 * 12,
        "doorCount": 1,
        "panelColor": "WHITE",
        "panelDesign": "UDC",
        "trackThickness": "2",
        "trackMount": "bracket",
        "liftType": "standard",
    }
    door.update(overrides)
    return door


_PANELS_ONLY = {
    "panels": True,
    "bottomRetainer": False,
    "tracks": False,
    "springs": False,
    "struts": False,
    "hardwareKits": False,
    "weatherStripping": False,
    "shafts": False,
}


def _install_builder_mocks(monkeypatch):
    import app.api.door_configurator as door_config

    monkeypatch.setattr(door_config, "get_bc_spring_inventory", lambda: {})
    monkeypatch.setattr(
        door_config, "resolve_creator_tag", lambda *args, **kwargs: ("EMAIL-0001", None, None)
    )
    monkeypatch.setattr(door_config, "save_quote_snapshot", lambda *args, **kwargs: None)


class TestBuildersPostV2:
    def test_configurator_before_and_after(self, monkeypatch):
        import app.api.door_configurator as door_config
        from app.api.door_configurator import DoorConfigRequest, QuoteGenerationRequest, build_bc_quote_from_doors

        _install_builder_mocks(monkeypatch)
        monkeypatch.setattr(door_config, "calculate_freight", _freight_calc)

        doors = [
            DoorConfigRequest(**_tx450(
                operator=HEAD,
                operatorAccessories=[PHOTO],
            )),
            DoorConfigRequest(**_tx450(
                doorWidth=12 * 12 + 2,
                doorHeight=14 * 12,
                doorCount=2,
                hardware=_PANELS_ONLY,
            )),
        ]

        def _post(enabled):
            _enable_v2(monkeypatch, enabled)
            bc = _RecordingBC()
            monkeypatch.setattr(door_config, "bc_client", bc)
            result = build_bc_quote_from_doors(
                QuoteGenerationRequest(doors=doors, deliveryType="delivery"),
                db=None,
                source="email",
            )
            assert result["success"] is True, result
            return bc

        before = _post(False)
        after = _post(True)

        assert before.skeleton() == [
            'DOOR (1) 10\'0" x 8\'0" TX450, WHITE, UDC, 2" BRACKET MOUNT, STD LIFT [Output]',
            f"{HEAD} [Output]",
            f"{PHOTO} [Output]",
            f"{RAIL_8} [Output]",
            "WRAP",
            "FREIGHT [Output]",
            'DOOR (2) 12\'2" x 14\'0" TX450, WHITE, UDC, PANELS ONLY [Output]',
            "WRAP",
            "FREIGHT [Output]",
        ]
        assert after.skeleton() == [
            'DOOR (1) 10\'0" x 8\'0" TX450, WHITE, UDC, 2" BRACKET MOUNT, STD LIFT [Output]',
            "WRAP",
            'DOOR (2) 12\'2" x 14\'0" TX450, WHITE, UDC, PANELS ONLY [Output]',
            "WRAP",
            f"{HEAD} [Output]",
            f"{RAIL_8}",
            f"{PHOTO} [Output]",
            "FREIGHT [Output]",
        ]

        numbers = [row.get("lineObjectNumber") for row in after.added if row.get("lineType") == "Item"]
        assert numbers.count("FREIGHT") == 1
        assert numbers[-1] == "FREIGHT"
        assert numbers.count("WRAP") == 2
        wraps = [row for row in after.added if row.get("lineObjectNumber") == "WRAP"]
        assert wraps[0]["quantity"] == door_wrapping_sqft(10 * 12, 8 * 12)
        assert wraps[1]["quantity"] == door_wrapping_sqft(12 * 12 + 2, 14 * 12) * 2
        # Nothing operator-like sits inside a door package: both wraps come
        # before the operator head.
        assert numbers.index("WRAP") < numbers.index(HEAD)
        assert numbers.index(RAIL_8) == numbers.index(HEAD) + 1

        prices = {
            update["id"]: update["data"].get("unitPrice")
            for update in after.updates
            if "unitPrice" in update["data"]
        }
        freight = next(row for row in after.added if row.get("lineObjectNumber") == "FREIGHT")
        # Fake BC subtotal is $100, so the one freight line is the whole 10%.
        assert prices[freight["id"]] == 10.0
        descriptions = {
            update["id"]: update["data"].get("description")
            for update in after.updates
            if "description" in update["data"]
        }
        assert descriptions[freight["id"]] == "Freight (10%)"

    def test_portal_single_door_posts_one_trailing_freight(self, monkeypatch):
        import app.api.customer_portal as portal

        _enable_v2(monkeypatch, True)
        monkeypatch.setattr(portal, "get_bc_spring_inventory", lambda: {})
        monkeypatch.setattr(portal, "calculate_freight", _freight_calc)
        bc = _RecordingBC()
        monkeypatch.setattr(portal, "bc_client", bc)
        portal._generate_bc_quote_with_items(
            doors=[_tx450(doorWidth=14 * 12 + 2, doorHeight=14 * 12)],
            bc_customer_id="C-LAYOUT",
            config_id=1,
            db=None,
            delivery_type="delivery",
        )
        numbers = [row.get("lineObjectNumber") for row in bc.added if row.get("lineType") == "Item"]
        assert numbers.count("WRAP") == 1
        assert numbers.count("FREIGHT") == 1
        assert numbers[-2:] == ["WRAP", "FREIGHT"]
        wrap = next(row for row in bc.added if row.get("lineObjectNumber") == "WRAP")
        assert wrap["quantity"] == 198
        freight_marks = [
            seq for seq, output in bc.output
            if output and seq == next(
                row["sequence"] for row in bc.added if row.get("lineObjectNumber") == "FREIGHT"
            )
        ]
        assert freight_marks
        wrap_checked = wrap["sequence"] in {seq for seq, output in bc.output if output}
        assert wrap_checked is False

    def test_local_estimate_prices_one_freight_line_at_the_full_amount(self, monkeypatch):
        import app.api.customer_portal as portal

        _enable_v2(monkeypatch, True)
        monkeypatch.setattr(portal, "get_bc_spring_inventory", lambda: {})
        monkeypatch.setattr(portal, "warm_bc_cost_cache", lambda *args, **kwargs: None)
        monkeypatch.setattr(portal, "calculate_selling_price", lambda **kwargs: 10.0)
        monkeypatch.setattr(
            portal,
            "calculate_freight",
            lambda **kwargs: {
                "skip": False, "amount": 40.0, "rate": 7.0,
                "description": "Freight (7.0% - AB)",
            },
        )
        result = portal._estimate_pricing_locally(
            doors=[
                _tx450(operator=HEAD, operatorAccessories=[PHOTO]),
                _tx450(
                    doorWidth=12 * 12 + 2,
                    doorHeight=14 * 12,
                    doorCount=2,
                    hardware=_PANELS_ONLY,
                ),
            ],
            pricing_tier="retail",
            config_id=1,
            db=None,
            delivery_type="delivery",
        )
        rows = [
            (row["part_number"], row["description"], row["quantity"], row["unit_price"])
            for row in result["line_pricing"]
            if row.get("part_number") in {HEAD, RAIL_8, PHOTO, "WRAP", "FREIGHT"}
            or (row.get("line_type") == "Comment" and str(row.get("description", "")).startswith("("))
        ]
        assert [row[0] or "DOOR" for row in rows] == [
            "DOOR", "WRAP", "DOOR", "WRAP", HEAD, RAIL_8, PHOTO, "FREIGHT",
        ]
        freight = rows[-1]
        assert freight[1] == "Freight (7.0% - AB)"
        assert freight[3] == 40.0
        wraps = [row for row in rows if row[0] == "WRAP"]
        assert len(wraps) == 2
        assert wraps[1][2] == door_wrapping_sqft(12 * 12 + 2, 14 * 12) * 2

    def test_portal_edit_rebuilds_v2_order(self, monkeypatch):
        import app.api.customer_portal as portal

        _enable_v2(monkeypatch, True)
        monkeypatch.setattr(portal, "get_bc_spring_inventory", lambda: {})
        monkeypatch.setattr(portal, "calculate_freight", _freight_calc)
        bc = _RecordingBC()
        monkeypatch.setattr(portal, "bc_client", bc)
        door = {**_tx450(operator=HEAD), "door_uid": "a"}
        config = SimpleNamespace(
            id=None,
            bc_quote_id="quote-layout",
            bc_quote_number="SQ-LAYOUT",
            config_data={"doors": []},
            bc_line_map=None,
        )
        portal._edit_bc_quote_lines(
            config,
            {"doors": [door]},
            bc_customer_id="C-LAYOUT",
            pricing_tier="retail",
            db=None,
            customer_user_id=None,
            delivery_type="delivery",
        )
        numbers = [row.get("lineObjectNumber") for row in bc.added if row.get("lineType") == "Item"]
        assert numbers.count("FREIGHT") == 1
        assert numbers[-1] == "FREIGHT"
        assert numbers[numbers.index("WRAP") + 1] == HEAD
        assert numbers[numbers.index(HEAD) + 1] == RAIL_8
        checked = {seq for seq, output in bc.output if output}
        by_seq = {row["sequence"]: row.get("lineObjectNumber") for row in bc.added}
        checked_numbers = [by_seq.get(seq) for seq in checked]
        assert RAIL_8 not in checked_numbers
        assert HEAD in checked_numbers
        assert "FREIGHT" in checked_numbers
