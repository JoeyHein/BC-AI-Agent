"""Pricing and freight tests.

Covers:
- Freight province normalization (Manitoba = MB); default 9%, AB override 7%
- Glazing margins loaded correctly (not blank)
- Glass kit pricing uses glazing margins
"""
import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.freight_service import (
    PROVINCE_NAME_TO_CODE,
    calculate_freight,
    get_default_freight_config,
)
from app.services.pricing_service import get_default_tier_margins


# ── Province normalization ────────────────────────────────────────────────

class TestProvinceNormalization:
    def test_all_provinces_mapped(self):
        expected = ["AB", "BC", "MB", "NB", "NL", "NS", "NT", "NU", "ON", "PE", "QC", "SK", "YT"]
        for code in expected:
            name = next((k for k, v in PROVINCE_NAME_TO_CODE.items() if v == code), None)
            assert name is not None, f"Province code {code} not in PROVINCE_NAME_TO_CODE"

    @pytest.mark.parametrize("input_val,expected_code", [
        ("Manitoba", "MB"),
        ("MANITOBA", "MB"),
        ("manitoba", "MB"),
        ("Saskatchewan", "SK"),
        ("British Columbia", "BC"),
        ("MB", "MB"),  # Already a code
        ("AB", "AB"),  # Already a code
    ])
    def test_province_resolves(self, input_val, expected_code):
        upper = input_val.upper().strip()
        code = PROVINCE_NAME_TO_CODE.get(upper, upper)
        assert code == expected_code, f"'{input_val}' resolved to '{code}', expected '{expected_code}'"


# ── Freight rates ─────────────────────────────────────────────────────────

class TestFreightRates:
    def test_default_rate_is_9_percent(self):
        config = get_default_freight_config()
        assert config["default_rate"] == 9.0

    def test_ab_override_differs_from_default(self):
        config = get_default_freight_config()
        ab_rate = config["province_overrides"].get("AB")
        assert ab_rate == 7.0, "Alberta freight override should be 7%"
        assert ab_rate != config["default_rate"]

    def test_other_provinces_use_default_rate(self):
        # Only Alberta carries an override now; MB/SK/BC fall through to the default.
        config = get_default_freight_config()
        for code in ("MB", "SK", "BC"):
            assert code not in config["province_overrides"], (
                f"{code} should no longer have a freight override (uses default)"
            )

    def test_one_line_matches_the_combined_goods_percent(self, monkeypatch):
        """Quote freight is the province percent of all doors together.

        A 3-door Alberta quote whose goods are $1,000 + $2,000 + $500 used
        to post three FREIGHT lines. Those shares were a split of one
        charge, round(3500 * 7%, 2) = $245.00, so they summed to $245.00
        (70 + 140 + 35). The quote now posts that $245.00 once.
        """
        import app.services.freight_service as freight_service

        monkeypatch.setattr(
            freight_service,
            "get_freight_config",
            lambda db: get_default_freight_config(),
        )
        goods = [1000.00, 2000.00, 500.00]
        result = calculate_freight(sum(goods), "Alberta", "delivery", db=None)
        assert result["skip"] is False
        assert result["rate"] == 7.0
        assert result["description"] == "Freight (7.0% - AB)"
        assert result["amount"] == 245.00
        former_shares = [round(amount * 0.07, 2) for amount in goods]
        assert former_shares == [70.00, 140.00, 35.00]
        assert round(sum(former_shares), 2) == result["amount"]

    def test_pickup_and_zero_goods_do_not_charge(self, monkeypatch):
        import app.services.freight_service as freight_service

        monkeypatch.setattr(
            freight_service,
            "get_freight_config",
            lambda db: get_default_freight_config(),
        )
        pickup = calculate_freight(3500.00, "AB", "pickup", db=None)
        assert pickup["skip"] is True
        assert pickup["amount"] == 0
        empty = calculate_freight(0, "AB", "delivery", db=None)
        assert empty["skip"] is True
        assert empty["amount"] == 0


# ── Tier margins ──────────────────────────────────────────────────────────

class TestTierMargins:
    def test_glazing_margins_exist(self):
        margins = get_default_tier_margins()
        assert "glazing" in margins, "Glazing category must exist in tier margins"

    def test_all_tiers_have_values(self):
        margins = get_default_tier_margins()
        expected_tiers = ["platinum", "unlisted", "gold", "silver", "bronze", "retail"]
        for door_type in ["residential", "commercial", "aluminium", "glazing"]:
            assert door_type in margins, f"Missing door type: {door_type}"
            for tier in expected_tiers:
                val = margins[door_type].get(tier)
                assert val is not None and val > 0, \
                    f"{door_type}/{tier} margin is {val} — should be > 0"

    def test_glazing_margins_higher_than_residential(self):
        margins = get_default_tier_margins()
        for tier in ["gold", "silver", "bronze", "retail"]:
            assert margins["glazing"][tier] > margins["residential"][tier], \
                f"Glazing {tier} ({margins['glazing'][tier]}) should be higher than residential ({margins['residential'][tier]})"
