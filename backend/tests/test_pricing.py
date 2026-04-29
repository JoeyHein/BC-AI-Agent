"""Pricing and freight tests.

Pricing now reads live from BC's published Sales Price Lists — there is no
margin-matrix or cost-adjustment matrix to test. We exercise the lookup
chain via mocks instead of the legacy formula.

Lookup order pinned by these tests:
  1. SalesPriceLists where Assign_to_No = customer's BC price group
  2. SalesPriceLists where Assign_to_No = '' (All Customers)
  3. ItemMasterList Unit_Price (item card)
"""
import pytest
import sys
import os
from unittest.mock import patch, MagicMock, call

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.freight_service import PROVINCE_NAME_TO_CODE, get_default_freight_config
from app.services import pricing_service
from app.integrations.bc.client import BusinessCentralClient


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
        ("MB", "MB"),
        ("AB", "AB"),
    ])
    def test_province_resolves(self, input_val, expected_code):
        upper = input_val.upper().strip()
        code = PROVINCE_NAME_TO_CODE.get(upper, upper)
        assert code == expected_code, f"'{input_val}' resolved to '{code}', expected '{expected_code}'"


# ── Freight rates ─────────────────────────────────────────────────────────

class TestFreightRates:
    def test_manitoba_not_default_rate(self):
        config = get_default_freight_config()
        default = config["default_rate"]
        mb_rate = config["province_overrides"].get("MB")
        assert mb_rate is not None, "Manitoba should have a freight override"
        assert mb_rate != default, f"Manitoba rate ({mb_rate}) should differ from default ({default})"

    def test_sk_bc_have_overrides(self):
        config = get_default_freight_config()
        assert "SK" in config["province_overrides"]
        assert "BC" in config["province_overrides"]


# ── Pricing lookup chain (mocked BC) ──────────────────────────────────────

class TestPricingLookupChain:
    def setup_method(self):
        pricing_service.clear_pricing_cache()

    def test_tier1_group_specific_price_wins(self):
        """SalesPriceLists with Assign_to_No should take precedence."""
        with patch("app.integrations.bc.client.bc_client") as mock_bc:
            mock_bc.get_item_master.return_value = {
                "No": "PN10-001", "Base_Unit_of_Measure": "EA", "Unit_Price": 999.99,
            }
            mock_bc.get_sales_price.return_value = {"Unit_Price": 100.00}
            mock_bc.get_default_sales_price.return_value = {"Unit_Price": 200.00}

            price = pricing_service.calculate_selling_price("PN10-001", bc_price_group="GOLD")
            assert price == 100.00
            mock_bc.get_sales_price.assert_called_once_with("PN10-001", "GOLD", "EA")

    def test_tier2_default_list_when_no_group_match(self):
        """Falls through to no-group list price if group-specific price is missing."""
        with patch("app.integrations.bc.client.bc_client") as mock_bc:
            mock_bc.get_item_master.return_value = {
                "No": "PN10-002", "Base_Unit_of_Measure": "EA", "Unit_Price": 999.99,
            }
            mock_bc.get_sales_price.return_value = None
            mock_bc.get_default_sales_price.return_value = {"Unit_Price": 250.00}

            price = pricing_service.calculate_selling_price("PN10-002", bc_price_group="GOLD")
            assert price == 250.00

    def test_tier3_item_card_when_no_price_list(self):
        """Falls through to item-card Unit_Price when SalesPriceLists has nothing."""
        with patch("app.integrations.bc.client.bc_client") as mock_bc:
            mock_bc.get_item_master.return_value = {
                "No": "PN10-003", "Base_Unit_of_Measure": "EA", "Unit_Price": 49.50,
            }
            mock_bc.get_sales_price.return_value = None
            mock_bc.get_default_sales_price.return_value = None

            price = pricing_service.calculate_selling_price("PN10-003", bc_price_group="GOLD")
            assert price == 49.50

    def test_returns_none_when_part_unknown(self):
        with patch("app.integrations.bc.client.bc_client") as mock_bc:
            mock_bc.get_item_master.return_value = None
            mock_bc.get_sales_price.return_value = None
            mock_bc.get_default_sales_price.return_value = None

            price = pricing_service.calculate_selling_price("DOES-NOT-EXIST", bc_price_group="GOLD")
            assert price is None

    def test_no_group_skips_to_default_list(self):
        """When customer has no price group, tier 1 is skipped."""
        with patch("app.integrations.bc.client.bc_client") as mock_bc:
            mock_bc.get_item_master.return_value = {
                "No": "PN10-004", "Base_Unit_of_Measure": "EA", "Unit_Price": 75.00,
            }
            mock_bc.get_default_sales_price.return_value = {"Unit_Price": 80.00}

            price = pricing_service.calculate_selling_price("PN10-004", bc_price_group=None)
            assert price == 80.00
            mock_bc.get_sales_price.assert_not_called()

    def test_lookup_order_is_strict(self):
        """When ALL three tiers have a price, tier 1 wins and tiers 2/3 are
        never queried. This pins the order: Customer Price Group →
        All Customer Price Group → Unit Price from Item Master.
        """
        with patch("app.integrations.bc.client.bc_client") as mock_bc:
            mock_bc.get_item_master.return_value = {
                "No": "PN10-005", "Base_Unit_of_Measure": "EA", "Unit_Price": 999.00,
            }
            mock_bc.get_sales_price.return_value = {"Unit_Price": 100.00}
            mock_bc.get_default_sales_price.return_value = {"Unit_Price": 200.00}

            price = pricing_service.calculate_selling_price("PN10-005", bc_price_group="GOLD")

            assert price == 100.00, "Tier 1 (group-specific) must win when present"
            mock_bc.get_sales_price.assert_called_once()
            mock_bc.get_default_sales_price.assert_not_called()

    def test_skips_tier1_to_tier2_when_group_blank(self):
        """An empty/whitespace group is treated as 'no group' so Tier 1 is
        skipped and All-Customers (Tier 2) is consulted next.
        """
        with patch("app.integrations.bc.client.bc_client") as mock_bc:
            mock_bc.get_item_master.return_value = {
                "No": "PN10-006", "Base_Unit_of_Measure": "EA", "Unit_Price": 50.00,
            }
            mock_bc.get_default_sales_price.return_value = {"Unit_Price": 65.00}

            price = pricing_service.calculate_selling_price("PN10-006", bc_price_group="   ")
            assert price == 65.00
            mock_bc.get_sales_price.assert_not_called()
            mock_bc.get_default_sales_price.assert_called_once_with("PN10-006", "EA")


class TestBCClientFilterStrings:
    """Pin the exact OData $filter strings sent to BC for each tier so a
    future refactor can't quietly drop the Assign_to_No constraint."""

    def _stub_client(self):
        client = BusinessCentralClient.__new__(BusinessCentralClient)
        client.odata_url = "https://example/ODataV4"
        client._get_access_token = lambda: "token"  # bypass MSAL
        return client

    def test_tier1_filter_targets_specific_group(self):
        client = self._stub_client()
        captured = {}

        def fake_get(*args, **kwargs):
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"value": [{"Unit_Price": 100}]}
            captured["url"] = args[0] if args else kwargs.get("url")
            return mock_resp

        with patch("app.integrations.bc.client.requests.get", side_effect=fake_get):
            client.get_sales_price("PN10-100", "GOLD", "EA")

        assert "Product_No eq 'PN10-100'" in captured["url"]
        assert "Assign_to_No eq 'GOLD'" in captured["url"]
        assert "Unit_of_Measure_Code eq 'EA'" in captured["url"]

    def test_tier2_filter_targets_all_customers_only(self):
        """All Customers entries in BC have Assign_to_No = ''. Tier 2 must
        scope to those rows so we don't accidentally pick up a different
        group's price."""
        client = self._stub_client()
        captured = {}

        def fake_get(*args, **kwargs):
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"value": []}
            captured["url"] = args[0] if args else kwargs.get("url")
            return mock_resp

        with patch("app.integrations.bc.client.requests.get", side_effect=fake_get):
            client.get_default_sales_price("PN10-200", "EA")

        assert "Product_No eq 'PN10-200'" in captured["url"]
        assert "Assign_to_No eq ''" in captured["url"], (
            "Tier 2 must filter on Assign_to_No = '' to match only the "
            "All Customers entry, not arbitrary group rows"
        )
        assert "Unit_of_Measure_Code eq 'EA'" in captured["url"]

    def test_tier1_and_tier2_use_different_filters(self):
        """Sanity: the two SalesPriceLists URLs must differ in their
        Assign_to_No clause."""
        client = self._stub_client()
        urls = []

        def fake_get(*args, **kwargs):
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"value": []}
            urls.append(args[0] if args else kwargs.get("url"))
            return mock_resp

        with patch("app.integrations.bc.client.requests.get", side_effect=fake_get):
            client.get_sales_price("X", "GOLD", "EA")
            client.get_default_sales_price("X", "EA")

        assert "Assign_to_No eq 'GOLD'" in urls[0]
        assert "Assign_to_No eq ''" in urls[1]
        assert urls[0] != urls[1]

    def test_odata_escape_handles_apostrophes(self):
        client = self._stub_client()
        # OData escapes a single quote by doubling it. Make sure part numbers
        # with apostrophes don't break the filter syntax.
        assert client._odata_escape("o'connor") == "o''connor"
        assert client._odata_escape("PLAIN") == "PLAIN"
        assert client._odata_escape("") == ""
