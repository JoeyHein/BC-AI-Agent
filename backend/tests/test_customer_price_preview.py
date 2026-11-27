"""Running price beside the dealer designer. No Business Central quote is created."""

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import AppSettings, BCCustomer, SavedQuoteConfig


def _door(door_type, series, width=96, height=84, **extra):
    door = {
        "doorType": door_type,
        "doorSeries": series,
        "doorWidth": width,
        "doorHeight": height,
        "doorCount": 1,
        "panelColor": "WHITE",
        "panelDesign": "SH",
    }
    door.update(extra)
    return door


def test_price_preview_uses_province_freight_and_does_not_save_a_quote(monkeypatch):
    from app.api import customer_portal as portal
    from app.api.customer_auth import get_current_customer

    engine = create_engine(
        "sqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    AppSettings.__table__.create(engine, checkfirst=True)
    BCCustomer.__table__.create(engine, checkfirst=True)
    SavedQuoteConfig.__table__.create(engine, checkfirst=True)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = Session()
    db.add(BCCustomer(
        bc_customer_id="C-100",
        company_name="Prairie Door Co.",
        pricing_tier="gold",
        address={"province": "Alberta"},
    ))
    db.commit()

    seen = []

    def parts(config, spring_inventory=None):
        seen.append((config.get("doorType"), config.get("doorSeries")))
        return {
            "parts_list": [{
                "part_number": "PN-SECTION",
                "description": "Section",
                "quantity": 2,
                "category": "section",
            }]
        }

    def selling_price(part_number, door_type, tier, db):
        seen.append(("tier", tier, door_type))
        return 500.0

    monkeypatch.setattr(portal, "get_parts_for_door_config", parts)
    monkeypatch.setattr(portal, "calculate_selling_price", selling_price)
    monkeypatch.setattr(portal, "warm_bc_cost_cache", lambda part_numbers: None)
    monkeypatch.setattr(portal, "get_bc_spring_inventory", lambda: {})

    user = SimpleNamespace(
        id=7,
        email="dealer@example.com",
        bc_customer_id="C-100",
        is_active=True,
        user_type="CUSTOMER",
    )

    def _db():
        yield db

    app = FastAPI()
    app.include_router(portal.router)
    app.dependency_overrides[portal.get_db] = _db
    app.dependency_overrides[get_current_customer] = lambda: user
    client = TestClient(app)

    residential = client.post("/api/customer/portal/price-preview", json={
        "deliveryType": "delivery",
        "doors": [_door("residential", "KANATA", 192, 84)],
    })
    assert residential.status_code == 200, residential.text
    body = residential.json()
    assert body["is_estimate"] is True
    assert body["pricing_tier"] == "gold"
    assert body["pricing"]["is_estimate"] is True
    # 2 sections × $500 = $1,000. Alberta is 7%, so freight is $70.
    assert body["freight"]["rate"] == 7.0
    assert body["freight"]["amount"] == 70.0
    assert body["pricing"]["total"] == 1070.0
    assert "bc_quote_id" not in body
    # The running estimate is a customer payload: one package row, no component
    # part numbers or unit prices. Freight stays its own line.
    import json
    rendered = json.dumps(body["line_pricing"])
    assert "PN-SECTION" not in rendered
    assert "unit_price" not in rendered
    package = next(row for row in body["line_pricing"] if row["line_type"] == "Package")
    assert "KANATA" in package["description"]
    assert package["quantity"] == 1
    assert package["line_total"] == 1000.0
    freight = next(row for row in body["line_pricing"] if row["line_type"] == "Freight")
    assert freight["line_total"] == 70.0
    assert "parts_count" not in json.dumps(body["door_results"])
    assert db.query(SavedQuoteConfig).count() == 0

    customer = db.query(BCCustomer).filter_by(bc_customer_id="C-100").one()
    customer.address = {"province": "Saskatchewan"}
    db.commit()
    other = client.post("/api/customer/portal/price-preview", json={
        "deliveryType": "delivery",
        "doors": [_door("commercial", "TX450", 144, 96, panelDesign="UDC")],
    })
    assert other.status_code == 200, other.text
    # Outside Alberta the default freight rate is 9%.
    assert other.json()["freight"]["rate"] == 9.0
    assert other.json()["freight"]["amount"] == 90.0
    assert other.json()["pricing"]["total"] == 1090.0

    customer.freight_override = "waive"
    db.commit()
    waived = client.post("/api/customer/portal/price-preview", json={
        "deliveryType": "delivery",
        "doors": [_door("residential", "KANATA", 192, 84)],
    })
    assert waived.status_code == 200, waived.text
    assert waived.json()["freight"]["customer_override"] == "waive"
    assert waived.json()["freight"]["skip"] is True
    assert waived.json()["freight"]["amount"] == 0
    assert waived.json()["pricing"]["total"] == 1000.0

    pickup = client.post("/api/customer/portal/price-preview", json={
        "deliveryType": "pickup",
        "doors": [_door("aluminium", "AL976", 96, 84, panelColor="CLEAR_ANODIZED", panelDesign="FLUSH")],
    })
    assert pickup.status_code == 200, pickup.text
    assert pickup.json()["freight"]["skip"] is True
    assert pickup.json()["pricing"]["total"] == 1000.0

    assert ("residential", "KANATA") in seen
    assert ("commercial", "TX450") in seen
    assert ("aluminium", "AL976") in seen
    assert db.query(SavedQuoteConfig).count() == 0

    missing = client.post("/api/customer/portal/price-preview", json={
        "doors": [{"doorType": "residential", "doorWidth": 96, "doorHeight": 84}],
    })
    assert missing.status_code == 400
    db.close()
