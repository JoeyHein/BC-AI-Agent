"""Part number generation tests.

Covers critical bugs:
- Struts: KANATA and CRAFT residential always get 1x20ga
- Hardware boxes: correct BC part numbers (HW for commercial, HK10 for residential)
- Top seal: optional upgrade below threshold, auto above
- Comment line: includes track size, mount type, lift type
- Freight: Output flag set
- High lift: extension track kit included
"""
import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.part_number_service import get_parts_for_door_config
from app.services.bc_part_number_mapper import get_bc_mapper


def _get_parts(overrides: dict) -> list:
    base = {
        "doorType": "residential", "doorSeries": "KANATA",
        "doorWidth": 108, "doorHeight": 84, "doorCount": 1,
        "panelColor": "WHITE", "panelDesign": "SHXL",
        "hardware": {"struts": True, "tracks": True, "springs": True,
                     "hardwareKits": True, "weatherStripping": True,
                     "bottomRetainer": True, "shafts": True},
        "targetCycles": 10000, "trackThickness": "2",
        "trackRadius": "15", "trackMount": "bracket", "liftType": "standard",
    }
    base.update(overrides)
    return get_parts_for_door_config(base).get("parts_list", [])


def _by_category(parts, category):
    return [p for p in parts if p.get("category") == category]


# ── Galvanized spring upgrade (SP10) ────────────────────────────────────────

class TestGalvanizedSprings:
    """springFinish='galvanized' swaps SP11 (oil-tempered) → SP10 (galvanized)
    only where BC stocks the SP10 twin at the resolved wire/coil; otherwise the
    oil-tempered spring is kept and the gap is flagged (never a rate change)."""

    def _springs(self, **overrides):
        return [p["part_number"] for p in _by_category(_get_parts(overrides), "spring")]

    def _warnings(self, **overrides):
        return [p["notes"] for p in _by_category(_get_parts(overrides), "spring_warning")]

    def test_default_is_oil_tempered(self):
        # No springFinish → SP11 (144x120 KANATA resolves to a twinned encoding).
        pns = self._springs(doorWidth=144, doorHeight=120)
        assert pns and all(p.startswith("SP11-") for p in pns)

    def test_galvanized_swaps_when_stocked(self):
        # 144x120 → SP11-26220, which HAS an SP10-26220 twin → swaps to galvanized.
        pns = self._springs(doorWidth=144, doorHeight=120, springFinish="galvanized")
        assert pns and all(p.startswith("SP10-") for p in pns), pns
        # And the detail comment is marked galvanized.
        comments = [p["description"] for p in _by_category(
            _get_parts({"doorWidth": 144, "doorHeight": 120, "springFinish": "galvanized"}),
            "spring_comment")]
        assert any("GALVANIZED" in c for c in comments)

    def test_galvanized_kept_oil_tempered_when_no_twin(self):
        # 120x96 → SP11-21820, which has NO SP10-21820 twin → stays oil-tempered
        # and flags the unavailable upgrade rather than substituting a rate.
        pns = self._springs(doorWidth=120, doorHeight=96, springFinish="galvanized")
        assert pns and all(p.startswith("SP11-") for p in pns), pns
        assert "galvanized_spring_unavailable" in self._warnings(
            doorWidth=120, doorHeight=96, springFinish="galvanized")


# ── Struts ────────────────────────────────────────────────────────────────

class TestStruts:
    @pytest.mark.parametrize("series", ["KANATA", "CRAFT"])
    @pytest.mark.parametrize("width", [96, 108, 144, 192])
    def test_residential_always_gets_strut(self, series, width):
        design = "SHXL" if series == "KANATA" else "FLUSH"
        parts = _get_parts({"doorSeries": series, "panelDesign": design, "doorWidth": width})
        struts = _by_category(parts, "strut")
        assert len(struts) == 1, f"{series} {width//12}ft: expected 1 strut, got {len(struts)}"
        assert struts[0]["quantity"] == 1

    def test_commercial_uses_strutting_chart(self):
        parts = _get_parts({
            "doorType": "commercial", "doorSeries": "TX450",
            "doorWidth": 168, "doorHeight": 120,
            "panelDesign": "UDC", "trackThickness": "3",
        })
        struts = _by_category(parts, "strut")
        # Commercial doors may get 0 or more struts depending on chart
        # Just verify no crash and strut count is reasonable
        assert all(s["quantity"] >= 0 for s in struts)


# ── Comment scope label (panels / door-face / hardware only) ────────────────

class TestCommentScope:
    """The auto-generated comment line must reflect partial hardware selections."""

    ALL_OFF = {"tracks": False, "springs": False, "struts": False,
               "hardwareKits": False, "weatherStripping": False, "shafts": False}

    def _comment(self, parts):
        comments = _by_category(parts, "comment")
        assert comments, "expected a comment line"
        return comments[0]["description"]

    def test_panels_only(self):
        """Only Door Panels checked (no bottom retainer) → PANELS ONLY."""
        hw = {"panels": True, "bottomRetainer": False, **self.ALL_OFF}
        desc = self._comment(_get_parts({"hardware": hw}))
        assert "PANELS ONLY" in desc
        # No tracks selected → no track/mount detail in the comment
        assert "MOUNT" not in desc

    def test_door_face_only(self):
        """Panels + bottom retainer, no operating hardware → DOOR FACE ONLY."""
        hw = {"panels": True, "bottomRetainer": True, **self.ALL_OFF}
        desc = self._comment(_get_parts({"hardware": hw}))
        assert "DOOR FACE ONLY" in desc
        assert "MOUNT" not in desc

    def test_hardware_only(self):
        """Hardware checked, panels off → NO DOOR FACE (and keeps track detail)."""
        hw = {"panels": False, "tracks": True, "springs": True, "struts": True,
              "hardwareKits": True, "weatherStripping": True, "bottomRetainer": True, "shafts": True}
        desc = self._comment(_get_parts({"hardware": hw}))
        assert "NO DOOR FACE" in desc
        assert "MOUNT" in desc

    def test_complete_door_has_no_scope_label(self):
        """A full door gets no scope tag, and still shows track/mount detail."""
        desc = self._comment(_get_parts({}))  # default hardware = all on
        assert "PANELS ONLY" not in desc
        assert "DOOR FACE ONLY" not in desc
        assert "NO DOOR FACE" not in desc
        assert "MOUNT" in desc


# ── V130G full-view fallback (AL976 substitute + next size up) ──────────────

class TestV130GFallback:
    """TX450 doors with V130G full-view inserts.

    As of 2026-07 BC now stocks V130G (PN10) sections in black (fff=008), so black
    resolves to the real PN10 part like any other stocked finish. The AL976 (PN97)
    fallback REMAINS as a safety net: PN10/PN12 and PN97 share an identical
    body+width encoding, so any finish/size BC does NOT carry as V130G still falls
    back to the AL976 equivalent (and an unavailable size steps up to the next
    stocked size). See test_resolver_falls_back_to_al976_when_v130g_missing.
    """

    def _v130g_door(self, **overrides):
        cfg = {
            "doorType": "commercial", "doorSeries": "TX450",
            "doorWidth": 96, "doorHeight": 96, "doorCount": 1,
            "panelColor": "WHITE", "panelDesign": "UDC", "trackThickness": "3",
            "hasWindows": True, "windowInsert": "V130G", "windowQty": 2,
            "windowSection": 1, "glassColor": "CLEAR", "glassPaneType": "INSULATED",
        }
        cfg.update(overrides)
        return _get_parts(cfg)

    def _sections(self, parts):
        return _by_category(parts, "v130g_section")

    def test_black_v130g_now_stocked_uses_pn10(self):
        """Black V130G is stocked in BC as of 2026-07 → real PN10 parts, no AL976
        substitution (the catalog refresh pulled in the black PN10 sections)."""
        sections = self._sections(self._v130g_door(panelColor="BLACK"))
        assert sections, "expected V130G full-view sections"
        for s in sections:
            assert s["part_number"].startswith("PN10-"), (
                f"black V130G is now stocked and should stay PN10, got {s['part_number']}"
            )

    def test_resolver_falls_back_to_al976_when_v130g_missing(self):
        """Safety net: when the requested V130G part is NOT stocked but the AL976
        equivalent is, the resolver substitutes PN97. Uses a stub catalog so the
        test is independent of what BC currently stocks."""
        from app.services.part_number_service import PartNumberService

        class _StubMapper:
            bc_items = {"PN97-24200810-0802"}  # only the AL976 equivalent is stocked

        svc = PartNumberService()
        resolved, used_al976, size_bumped = svc._resolve_full_view_section_pn(
            _StubMapper(), "PN10", "24", "2", "008", "10", "0802"
        )
        assert resolved == "PN97-24200810-0802"
        assert used_al976 is True
        assert size_bumped is False

    def test_white_v130g_stays_v130g(self):
        """White V130G is stocked → keep the PN10 V130G part numbers (no substitution)."""
        sections = self._sections(self._v130g_door(panelColor="WHITE"))
        assert sections
        for s in sections:
            assert s["part_number"].startswith("PN10-"), (
                f"white V130G should stay PN10, got {s['part_number']}"
            )

    @pytest.mark.parametrize("color", ["WHITE", "BLACK"])
    def test_all_emitted_sections_exist_in_bc(self, color):
        """Every emitted full-view section resolves to a real stocked BC item."""
        mapper = get_bc_mapper()
        sections = self._sections(self._v130g_door(panelColor=color))
        assert sections
        for s in sections:
            assert s["part_number"] in mapper.bc_items, (
                f"{color}: {s['part_number']} is not a stocked BC item"
            )

    def test_wide_door_top_section_falls_back_to_int(self):
        """BC only stocks the INT full-view section past ~20' wide (no TOP/BOT
        DEF at 22'+). A 24' wide door's TOP section must resolve to the stocked
        INT part (PN10-24600352-2402), not a non-existent TOP part."""
        mapper = get_bc_mapper()
        # 24' wide × 8' tall commercial → 24" DEF sections, width code 2402.
        sections = self._sections(
            self._v130g_door(doorWidth=288, doorHeight=96, windowQty=2, windowSection=1)
        )
        assert sections, "expected V130G full-view sections for a 24' door"
        for s in sections:
            assert s["part_number"] in mapper.bc_items, (
                f"{s['part_number']} not stocked in BC (position fallback failed)"
            )
        # The top-most section cannot be the unstocked TOP part; INT is stocked.
        assert "PN10-24600345-2402" not in [s["part_number"] for s in sections]
        assert "PN10-24600352-2402" in [s["part_number"] for s in sections]


class TestAluminumWidthSnap:
    """Aluminum full-view sections (Solalite/AL976/Panorama/SWD) exist only in
    discrete standard widths. The generator must snap the section width code UP
    to the smallest covering standard panel — a per-inch code (e.g. PN20-...1603
    for a 16'1" door) is not a stocked BC item and makes BC reject the quote
    line. Root cause of SQ-002808.

    Beyond existence, a section must also be SELLABLE (blocked=False): a blocked
    item is rejected on a quote line and silently drops to a comment (root cause
    of SQ-002814). For Solalite the only sellable config is Clear Anodized +
    thermal, so every emitted section must resolve to an unblocked BC item.
    """

    def _alu_door(self, **overrides):
        cfg = {
            "doorType": "aluminium", "doorSeries": "SOLALITE",
            "doorWidth": 192, "doorHeight": 120, "doorCount": 1,
            "panelColor": "CLEAR_ANODIZED", "glazingType": "polycarbonate",
            "glassColor": "CLEAR", "hasWindows": True, "operator": "NONE",
            "hardware": {},
        }
        cfg.update(overrides)
        return _by_category(_get_parts(cfg), "aluminum_section")

    @staticmethod
    def _assert_sellable(mapper, pn, ctx=""):
        item = mapper.bc_items.get(pn)
        assert item is not None, f"{ctx}{pn} is not a stocked BC item"
        assert not item.get("blocked"), f"{ctx}{pn} is BLOCKED (not sellable)"

    def test_odd_width_snaps_to_standard_and_sellable(self):
        """SQ-002808: a 16'1" Solalite emits the 16' panel (…1602), not …1603."""
        mapper = get_bc_mapper()
        sections = self._alu_door(doorWidth=193, doorHeight=168)
        assert sections
        for s in sections:
            assert s["part_number"].endswith("-1602"), (
                f"16'1\" door should snap to the 16' panel, got {s['part_number']}"
            )
            self._assert_sellable(mapper, s["part_number"])

    def test_solalite_is_always_clear_anodized_thermal(self):
        """SQ-002814: the only sellable Solalite is Clear Ano (f=0) + THERM (s=3).
        Mill / no-opt / double sections all exist but are blocked, so requesting
        Mill or a non-thermal door must still emit the clear-ano thermal item."""
        mapper = get_bc_mapper()
        for color in ("CLEAR_ANODIZED", "MILL", "WHITE"):
            for therm in (False, True):
                sections = self._alu_door(
                    doorWidth=144, panelColor=color,
                    hardware={"thermalBreak": therm},
                )
                assert sections
                for s in sections:
                    pn = s["part_number"]  # PN20-{hh}00{f}{p}{s}-{wwww}
                    assert pn[9] == "0", f"{color}/therm={therm}: expected f=0, got {pn}"
                    assert pn[11] == "3", f"{color}/therm={therm}: expected s=3, got {pn}"
                    self._assert_sellable(mapper, pn, f"{color}/therm={therm}: ")

    @pytest.mark.parametrize("width", [96, 110, 120, 144, 168, 192, 193, 205, 216, 240, 250])
    @pytest.mark.parametrize("height", [72, 120])
    def test_solalite_full_matrix_sellable(self, width, height):
        """Every Solalite section across widths/heights resolves to a sellable item."""
        mapper = get_bc_mapper()
        sections = self._alu_door(doorWidth=width, doorHeight=height)
        assert sections
        for s in sections:
            self._assert_sellable(mapper, s["part_number"], f"{width}x{height}: ")

    @pytest.mark.parametrize("series", ["SOLALITE", "AL976", "PANORAMA", "SWD"])
    @pytest.mark.parametrize("width", [98, 145, 170, 193, 205, 217, 241])
    def test_all_series_odd_widths_exist_in_bc(self, series, width):
        """Every aluminum series snaps odd widths to a real stocked section.

        NOTE: existence only — Panorama has blocked finish/width combos at
        18'–20' that need a product-rule decision; tracked separately.
        """
        mapper = get_bc_mapper()
        sections = self._alu_door(doorSeries=series, doorWidth=width)
        assert sections
        for s in sections:
            assert s["part_number"] in mapper.bc_items, (
                f"{series} @ {width}\": {s['part_number']} is not a stocked BC item"
            )


# ── Hardware boxes ────────────────────────────────────────────────────────

class TestHardwareBoxes:
    def test_residential_hk10_for_standard_sizes(self):
        """Residential KANATA/CRAFT, std lift, ≤8' tall, ≤18' wide → HK10 prebuilt box."""
        cases = [
            # (width_ft, height_in, expected SKU)
            ( 9, 84, "HK10-00704-0809"),
            (10, 84, "HK10-00704-0809"),
            (11, 84, "HK10-00704-0809"),  # 11' bucketed into smaller box
            (12, 84, "HK10-00704-1316"),
            (16, 84, "HK10-00704-1316"),
            (18, 84, "HK10-00704-1316"),
            ( 9, 96, "HK10-00804-0809"),
            (16, 96, "HK10-00804-1316"),
        ]
        for width, height, expected in cases:
            parts = _get_parts({"doorWidth": width * 12, "doorHeight": height})
            pn = _by_category(parts, "hardware")[0]["part_number"]
            assert pn == expected, f"{width}'x{height}\": expected {expected}, got {pn}"

    def test_residential_falls_back_to_hk02_outside_hk10_envelope(self):
        """Heights >8' or widths >18' use the per-size HK02 kits."""
        # 9' tall → no HK10 SKU
        pn = _by_category(_get_parts({"doorWidth": 16*12, "doorHeight": 108}), "hardware")[0]["part_number"]
        assert pn.startswith("HK02-"), f"9' tall: expected HK02, got {pn}"
        # 20' wide → no HK10 SKU
        pn = _by_category(_get_parts({"doorWidth": 20*12, "doorHeight": 96}), "hardware")[0]["part_number"]
        assert pn.startswith("HK02-"), f"20' wide: expected HK02, got {pn}"

    def test_commercial_hardware_generated(self):
        """HK03 kits follow a deterministic pattern — verify they're generated (not generic)."""
        for width in [12, 14, 16, 18]:
            parts = _get_parts({
                "doorType": "commercial", "doorSeries": "TX450",
                "doorWidth": width * 12, "doorHeight": 120,
                "panelDesign": "UDC", "trackThickness": "3",
            })
            hw = _by_category(parts, "hardware")
            assert len(hw) >= 1, f"Comm {width}ft: no hardware kit"
            pn = hw[0]["part_number"]
            assert pn.startswith("HK03-"), f"Comm {width}ft: expected HK03, got {pn}"
            assert pn != "HK03-00000-RC", f"Comm {width}ft: got generic fallback instead of sized kit"


# ── Top seal ──────────────────────────────────────────────────────────────

class TestTopSeal:
    def test_residential_no_top_seal(self):
        parts = _get_parts({})
        top_seals = _by_category(parts, "top_seal")
        assert len(top_seals) == 0, "Residential door should NOT have top seal"

    def test_commercial_below_threshold_no_top_seal_by_default(self):
        parts = _get_parts({
            "doorType": "commercial", "doorSeries": "TX450",
            "doorWidth": 168, "doorHeight": 120,
            "panelDesign": "UDC", "trackThickness": "3",
        })
        top_seals = _by_category(parts, "top_seal")
        assert len(top_seals) == 0, "Commercial below 18'x10' should NOT have top seal by default"

    def test_commercial_below_threshold_with_upgrade(self):
        parts = _get_parts({
            "doorType": "commercial", "doorSeries": "TX450",
            "doorWidth": 168, "doorHeight": 120,
            "panelDesign": "UDC", "trackThickness": "3",
            "includeTopSeal": True,
        })
        top_seals = _by_category(parts, "top_seal")
        assert len(top_seals) >= 1, "Commercial with includeTopSeal=True should have top seal"

    def test_commercial_above_threshold_always_has_top_seal(self):
        parts = _get_parts({
            "doorType": "commercial", "doorSeries": "TX450",
            "doorWidth": 240, "doorHeight": 144,
            "panelDesign": "UDC", "trackThickness": "3",
        })
        top_seals = _by_category(parts, "top_seal")
        assert len(top_seals) >= 1, "Commercial 20'x12' should always have top seal"


# ── Weather stripping color substitution ───────────────────────────────────

class TestWeatherStripColor:
    """French Oak has no weather-strip SKU in BC; it seals in New Almond.

    Regression for SQ-002677 (French Oak weather stripping dropped because
    PL10-..-35 does not exist in the BC catalog).
    """

    def test_french_oak_resolves_to_new_almond(self):
        mapper = get_bc_mapper()
        assert mapper.resolve_weather_strip_color("French Oak") == "NEW ALMOND"
        assert mapper.resolve_weather_strip_color("FRENCH OAK") == "NEW ALMOND"
        # Non-substituted colors pass through unchanged
        assert mapper.resolve_weather_strip_color("White") == "White"
        assert mapper.resolve_weather_strip_color("Walnut") == "Walnut"

    def test_french_oak_seal_parts_exist_in_bc(self):
        mapper = get_bc_mapper()
        parts = _get_parts({"panelColor": "French Oak"})
        strips = _by_category(parts, "weather_stripping")
        assert strips, "French Oak door produced no weather stripping"
        for s in strips:
            pn = s["part_number"]
            assert pn in mapper.bc_items, f"French Oak strip {pn} not in BC catalog"
            assert pn.endswith("-30"), f"Expected New Almond (-30) strip, got {pn}"
            assert "NEW ALMOND" in s["description"], \
                f"Strip description should say NEW ALMOND, got: {s['description']}"


# ── Comment line ──────────────────────────────────────────────────────────

class TestCommentLine:
    def test_comment_includes_mount_type(self):
        parts = _get_parts({"trackMount": "bracket"})
        comments = _by_category(parts, "comment")
        assert any("BRACKET MOUNT" in c.get("description", "") for c in comments), \
            "Comment should include BRACKET MOUNT"

    def test_comment_includes_angle_mount(self):
        parts = _get_parts({"trackMount": "angle"})
        comments = _by_category(parts, "comment")
        assert any("ANGLE MOUNT" in c.get("description", "") for c in comments), \
            "Comment should include ANGLE MOUNT"

    def test_comment_includes_high_lift(self):
        parts = _get_parts({"liftType": "high_lift", "highLiftInches": 24})
        comments = _by_category(parts, "comment")
        assert any('HIGH LIFT 24"' in c.get("description", "") for c in comments), \
            "Comment should include HIGH LIFT 24\""

    def test_comment_includes_track_size(self):
        parts = _get_parts({"trackThickness": "2"})
        comments = _by_category(parts, "comment")
        assert any('2"' in c.get("description", "") for c in comments), \
            "Comment should include track size"


# ── High lift extension ──────────────────────────────────────────────────

class TestHighLiftExtension:
    def test_high_lift_gets_extension_track(self):
        parts = _get_parts({"liftType": "high_lift", "highLiftInches": 24})
        hl_parts = _by_category(parts, "highlift_track")
        assert len(hl_parts) >= 1, "High lift door should have extension track kit"
        assert "EXT" in hl_parts[0]["part_number"], \
            f"Extension part number should contain EXT: {hl_parts[0]['part_number']}"

    def test_standard_lift_no_extension(self):
        parts = _get_parts({"liftType": "standard"})
        hl_parts = _by_category(parts, "highlift_track")
        assert len(hl_parts) == 0, "Standard lift should NOT have extension track"


# ── Manual chain hoist ───────────────────────────────────────────────────

class TestChainHoist:
    """Manual hand-chain hoist: commercial, motor-less doors only, 1 per door.
    'shaft' -> SP12-00084-00, 'wall' -> FH12-00190-00."""

    _COMMERCIAL = {
        "doorType": "commercial", "doorSeries": "TX450",
        "panelDesign": "UDC", "operator": "NONE",
    }

    def _hoist_parts(self, parts):
        return [p for p in parts
                if (p.get("part_number") or "").startswith(("SP12-00084", "FH12-00190"))]

    def test_shaft_mount_emits_part(self):
        parts = _get_parts({**self._COMMERCIAL, "chainHoist": "shaft"})
        hoists = self._hoist_parts(parts)
        assert len(hoists) == 1, "Shaft hoist should emit exactly one part"
        assert hoists[0]["part_number"] == "SP12-00084-00"
        assert hoists[0]["quantity"] == 1
        assert hoists[0]["category"] == "operator", "Must be operator category for Output=True"

    def test_wall_mount_emits_part(self):
        parts = _get_parts({**self._COMMERCIAL, "chainHoist": "wall"})
        hoists = self._hoist_parts(parts)
        assert len(hoists) == 1 and hoists[0]["part_number"] == "FH12-00190-00"

    def test_none_emits_nothing(self):
        for val in ("none", None):
            parts = _get_parts({**self._COMMERCIAL, "chainHoist": val})
            assert len(self._hoist_parts(parts)) == 0

    def test_residential_does_not_emit(self):
        parts = _get_parts({"doorType": "residential", "chainHoist": "shaft"})
        assert len(self._hoist_parts(parts)) == 0, "Chain hoist is commercial-only"

    def test_operator_present_suppresses_hoist(self):
        # A chain hoist is the manual option — mutually exclusive with a motor.
        parts = _get_parts({**self._COMMERCIAL, "operator": "OP19-01048-00",
                            "chainHoist": "shaft"})
        assert len(self._hoist_parts(parts)) == 0


class TestJackshaftAccessories:
    """Commercial SHAFT-mounted operators (hoist / jackshaft / direct-drive, per
    the catalog Mount column) auto-include a shaft accessory: the LiftMaster JHDC
    gets a chain TENSIONER, every other shaft-mounted operator gets a SPREADER BAR
    (mutually exclusive). Trolley/rail operators get neither. The accessory bore
    follows the torsion shaft bore (1-1/4" only on >2000 lb doors, else 1"). One
    per door."""

    _SPREADERS = {"OP20-02001-00", "OP20-02002-00"}
    _TENSIONERS = {"OP19-02126-00", "OP19-02127-00"}

    _COMMERCIAL = {
        "doorType": "commercial", "doorSeries": "TX450",
        "doorWidth": 144, "doorHeight": 144, "panelDesign": "FLUSH",
        "trackThickness": "3",
    }

    def _ops(self, parts):
        return {p.get("part_number") for p in parts if p.get("category") == "operator"}

    def test_jhdc_emits_tensioner_not_spreader(self):
        # JHDC jackshaft: tensioner replaces the spreader bar.
        pns = self._ops(_get_parts({**self._COMMERCIAL, "operator": "OP19-01107-00"}))
        assert "OP19-02126-00" in pns, "JHDC should get the 1\" tensioner"
        assert not (pns & self._SPREADERS), "JHDC should NOT get a spreader bar"

    def test_micanan_hoist_gets_spreader(self):
        # Micanan hoists carry no 'hoist' keyword in the name — they qualify via
        # the catalog Mount=shaft column. This is the SQ-002847 gap.
        for op in ("OP20-01056-00", "OP20-01001-00", "OP20-01011-00"):
            pns = self._ops(_get_parts({**self._COMMERCIAL, "operator": op}))
            assert pns & self._SPREADERS, f"{op} (shaft hoist) should get a spreader bar"
            assert not (pns & self._TENSIONERS), f"{op} should NOT get a tensioner"

    def test_accessory_is_one_each(self):
        # Exactly one shaft accessory, qty 1, category 'operator' (Output=True).
        parts = _get_parts({**self._COMMERCIAL, "operator": "OP20-01056-00"})
        accs = [p for p in parts if (p.get("part_number") or "") in self._SPREADERS | self._TENSIONERS]
        assert len(accs) == 1 and accs[0]["quantity"] == 1
        assert accs[0]["category"] == "operator"

    def test_heavy_jhdc_uses_1_25in_tensioner(self):
        # >2000 lb door runs a 1-1/4" shaft, so the accessory steps up. Weight
        # isn't injectable through the quote dict (always computed), so exercise
        # the bore branch directly on a heavy DoorConfiguration.
        from app.services.part_number_service import PartNumberService, DoorConfiguration

        svc = PartNumberService()
        cfg = DoorConfiguration(
            door_type="commercial", door_series="TX450", door_width=288, door_height=240,
            door_count=1, panel_color="WHITE", panel_design="FLUSH",
            operator="OP19-01109-00", door_weight=2500,
        )
        assert svc._torsion_shaft_bore(cfg) == "1-1/4"
        pns = {p.part_number for p in svc._get_operator_parts(cfg)}
        assert "OP19-02127-00" in pns          # 1-1/4" tensioner (JHDC)
        assert not (pns & self._SPREADERS)      # tensioner replaces spreader

    def test_accessory_bore_matches_shaft_bore(self):
        # The invariant: whatever bore the shaft gets, the accessory matches.
        from app.services.part_number_service import PartNumberService, DoorConfiguration

        svc = PartNumberService()
        # JHDC -> tensioner bore; Micanan hoist -> spreader bore
        cases = [
            ("OP19-01107-00", svc.JHDC_TENSIONERS),          # jackshaft
            ("OP20-01056-00", svc.JACKSHAFT_SPREADER_BARS),  # hoist
        ]
        for op, table in cases:
            for weight, expect in ((800, "1"), (2500, "1-1/4")):
                cfg = DoorConfiguration(
                    door_type="commercial", door_series="TX450", door_width=200, door_height=180,
                    door_count=1, panel_color="WHITE", panel_design="FLUSH",
                    operator=op, door_weight=weight,
                )
                bore = svc._torsion_shaft_bore(cfg)
                assert bore == expect
                pns = {p.part_number for p in svc._get_operator_parts(cfg)}
                assert table[bore][0] in pns, f"{op} @ {weight}lb should get {table[bore][0]}"

    def test_trolley_commercial_gets_neither(self):
        # LiftMaster T501L5 and Micanan PRO-TE are rail-mounted trolley ops.
        for op in ("OP19-01057-00", "OP20-01025-00"):
            pns = self._ops(_get_parts({**self._COMMERCIAL, "operator": op}))
            assert not (pns & (self._SPREADERS | self._TENSIONERS)), f"{op} (trolley) should add neither"

    def test_residential_shaft_op_gets_neither(self):
        # Residential jackshaft (LJ8900W) on a residential door — commercial gate.
        pns = self._ops(_get_parts({"doorType": "residential", "doorSeries": "KANATA",
                                    "operator": "OP19-01082-00"}))
        assert not (pns & (self._SPREADERS | self._TENSIONERS))

    def test_opt_out_suppresses_auto_accessory(self):
        # includeShaftAccessory=False lets the portal opt out (e.g. customer owns
        # the bar). Default (omitted) still auto-adds.
        base = {**self._COMMERCIAL, "operator": "OP20-01056-00"}
        assert self._ops(_get_parts(base)) & self._SPREADERS, "default should auto-add"
        opted_out = self._ops(_get_parts({**base, "includeShaftAccessory": False}))
        assert not (opted_out & (self._SPREADERS | self._TENSIONERS)), "opt-out should suppress it"
