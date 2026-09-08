"""_quote_customer_field: BC customer GUID must go in salesQuotes.customerId,
not customerNumber (which BC caps at 20 chars and 400s on a 36-char GUID)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.api.door_configurator import _quote_customer_field


def test_guid_goes_to_customer_id():
    # the exact value from the reported 400 (Global Overhead Doors)
    guid = "9044bb6a-ddac-ef11-b8ec-002248ae71c3"
    assert _quote_customer_field(guid) == {"customerId": guid}


def test_uppercase_guid_still_detected():
    guid = "9044BB6A-DDAC-EF11-B8EC-002248AE71C3"
    assert _quote_customer_field(guid) == {"customerId": guid}


def test_bare_customer_number_goes_to_customer_number():
    assert _quote_customer_field("BAKK") == {"customerNumber": "BAKK"}
    assert _quote_customer_field("GLOB") == {"customerNumber": "GLOB"}


def test_whitespace_trimmed():
    assert _quote_customer_field("  BAKK \n") == {"customerNumber": "BAKK"}
    g = "9044bb6a-ddac-ef11-b8ec-002248ae71c3"
    assert _quote_customer_field(f" {g} ") == {"customerId": g}
