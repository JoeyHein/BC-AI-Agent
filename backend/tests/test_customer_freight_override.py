"""Per-customer freight rules, including the Marquis Overhead Doors waiver."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.models import BCCustomer
from app.services.freight_service import (
    FreightOverrideError,
    apply_freight_seed,
    assign_freight_override,
    calculate_freight,
    customer_freight_policy,
    matches_marquis_freight_seed,
    seed_freight_overrides,
)
from app.services.staff_permissions import redact_configurator_quote, redact_customer_search


class _SettingsDB:
    def query(self, model):
        return self

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return None


def test_default_and_alberta_rates_are_unchanged():
    db = _SettingsDB()
    default = calculate_freight(100, None, "delivery", db)
    alberta = calculate_freight(100, "Alberta", "delivery", db)
    assert default["amount"] == 9.0
    assert default["rate"] == 9.0
    assert alberta["amount"] == 7.0
    assert alberta["rate"] == 7.0
    assert "customer_override" not in alberta


def test_waiver_is_zero_on_a_delivery_and_pickup_stays_pickup():
    db = _SettingsDB()
    waived = calculate_freight(250, "AB", "delivery", db, freight_policy={"mode": "waive"})
    assert waived == {
        "amount": 0,
        "rate": 0,
        "description": "Freight waived",
        "skip": True,
        "customer_override": "waive",
    }
    pickup = calculate_freight(250, "AB", "pickup", db, freight_policy={"mode": "waive"})
    assert pickup["description"] == "Pickup - No Freight"
    assert pickup["skip"] is True
    assert "customer_override" not in pickup


def test_percent_replaces_the_province_rate():
    db = _SettingsDB()
    freight = calculate_freight(
        200, "AB", "delivery", db, freight_policy={"mode": "percent", "percent": 4},
    )
    assert freight["amount"] == 8.0
    assert freight["rate"] == 4.0
    assert freight["customer_override"] == "percent"
    assert freight["skip"] is False


def test_marquis_matches_the_customer_number_or_the_company_name():
    assert matches_marquis_freight_seed("Something Else", "mrq") is True
    assert matches_marquis_freight_seed("Marquis Overhead Doors", None) is True
    assert matches_marquis_freight_seed("Marquis Overhead Doors Ltd.", "") is True
    assert matches_marquis_freight_seed("Aaron Gagnon", None) is False
    assert matches_marquis_freight_seed("Overhead Door Company of Calgary", "ODC") is False


def test_seed_sets_marquis_once_and_leaves_an_explicit_default():
    marquis = SimpleNamespace(
        company_name="Marquis Overhead Doors",
        customer_metadata={"number": "MRQ"},
        freight_override=None,
        freight_percent=4,
    )
    assert apply_freight_seed(marquis) is True
    assert marquis.freight_override == "waive"
    assert marquis.freight_percent is None
    assert apply_freight_seed(marquis) is False

    chosen = SimpleNamespace(
        company_name="Marquis Overhead Doors",
        customer_metadata={"number": "MRQ"},
        freight_override=None,
        freight_percent=None,
    )
    assign_freight_override(chosen, "default", 12)
    assert chosen.freight_override == "default"
    assert chosen.freight_percent is None
    assert apply_freight_seed(chosen) is False

    other = SimpleNamespace(
        company_name="Elevated Doors",
        customer_metadata={"number": "ED"},
        freight_override=None,
        freight_percent=None,
    )
    assert apply_freight_seed(other) is False
    assert other.freight_override is None


def test_percent_must_be_between_zero_and_one_hundred():
    customer = SimpleNamespace(freight_override=None, freight_percent=None)
    assign_freight_override(customer, "percent", 0)
    assert customer.freight_percent == 0
    assign_freight_override(customer, " Percent ", "12.5")
    assert customer.freight_override == "percent"
    assert customer.freight_percent == 12.5
    with pytest.raises(FreightOverrideError):
        assign_freight_override(customer, "percent", None)
    with pytest.raises(FreightOverrideError):
        assign_freight_override(customer, "percent", 101)
    with pytest.raises(FreightOverrideError):
        assign_freight_override(customer, "free", 0)
    assert customer_freight_policy(SimpleNamespace(freight_override=None, freight_percent=None)) == {
        "mode": "default",
        "percent": None,
    }


def test_seed_migration_waives_marquis_rows_and_keeps_other_rules():
    engine = create_engine("sqlite://", future=True, poolclass=StaticPool)
    BCCustomer.__table__.create(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = Session()
    db.add_all([
        BCCustomer(
            bc_customer_id="marquis-guid",
            company_name="Marquis Overhead Doors",
            customer_metadata={"number": "MRQ"},
        ),
        BCCustomer(
            bc_customer_id="number-only",
            company_name="M.O.D.",
            customer_metadata={"number": "mrq"},
        ),
        BCCustomer(
            bc_customer_id="already-set",
            company_name="Marquis Overhead Doors",
            customer_metadata={"number": "MRQ"},
            freight_override="percent",
            freight_percent=5,
        ),
        BCCustomer(
            bc_customer_id="neighbour",
            company_name="Elevated Doors",
            customer_metadata={"number": "ED"},
        ),
    ])
    db.commit()

    with engine.begin() as connection:
        assert seed_freight_overrides(connection) == 2

    db.expire_all()
    by_id = {row.bc_customer_id: row for row in db.query(BCCustomer).all()}
    assert by_id["marquis-guid"].freight_override == "waive"
    assert by_id["number-only"].freight_override == "waive"
    assert by_id["already-set"].freight_override == "percent"
    assert by_id["already-set"].freight_percent == 5
    assert by_id["neighbour"].freight_override is None
    db.close()


def test_selling_price_view_labels_a_waiver_as_waived():
    seller = SimpleNamespace(
        role="configurator",
        permissions=None,
        user_type="INTERNAL",
        email="person@opendc.ca",
    )
    payload = {
        "success": True,
        "data": {
            "freight": {
                "amount": 0,
                "rate": 0,
                "description": "Freight waived",
                "skip": True,
                "customer_override": "waive",
            },
            "pricing": {"total": 100},
            "line_pricing": [],
        },
    }
    cleaned = redact_configurator_quote(seller, payload)
    assert cleaned["data"]["freight"]["description"] == "Freight waived"
    assert cleaned["data"]["freight"]["amount"] == 0
    assert "rate" not in cleaned["data"]["freight"]

    picked = redact_customer_search(seller, {
        "bc_customer_id": "marquis-guid",
        "company_name": "Marquis Overhead Doors",
        "freight_override": "waive",
        "freight_percent": None,
    })
    assert picked["freight_override"] == "waive"
    assert picked["company_name"] == "Marquis Overhead Doors"
