"""Customer sync must drop customers deleted in BC.

Sync used to be upsert-only, so a customer deleted in BC (e.g. a duplicate
"Elevated Doors") stayed in the configurator's customer picker forever.
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import AppSettings, BCCustomer, CustomerNote, User, UserRole
from app.services.bc_sync_service import BCSyncService
from app.api.admin_customers import is_quotable_bc_customer


class FakeClient:
    def __init__(self, customers):
        self.customers = customers

    def get_customers_with_multiplier(self, strict=False):
        return self.customers

    def get_all_customer_price_groups(self):
        return {}


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    for m in (AppSettings, BCCustomer, User, CustomerNote):
        m.__table__.create(engine)
    return sessionmaker(bind=engine)()


def _sync(db, customers):
    svc = BCSyncService.__new__(BCSyncService)
    svc.client = FakeClient(customers)
    return asyncio.run(svc.sync_customers(db=db))


def _bc(i, name="Cust", blocked=""):
    return {"id": f"guid-{i}", "number": f"C{i}", "displayName": f"{name} {i}", "blocked": blocked}


def test_removed_unlinked_customer_is_deleted(db):
    _sync(db, [_bc(i) for i in range(10)])
    res = _sync(db, [_bc(i) for i in range(9)])
    assert res["customers_removed"] == 1
    assert db.query(BCCustomer).filter_by(bc_customer_id="guid-9").first() is None


def test_removed_linked_customer_is_flagged_not_deleted(db):
    _sync(db, [_bc(i) for i in range(10)])
    db.add(User(email="x@y.com", password_hash="h", role=UserRole.VIEWER,
                user_type="CUSTOMER", bc_customer_id="guid-9"))
    db.commit()
    res = _sync(db, [_bc(i) for i in range(9)])
    assert res["customers_flagged_removed"] == 1
    c = db.query(BCCustomer).filter_by(bc_customer_id="guid-9").one()
    assert not is_quotable_bc_customer(c)
    # comes back in BC -> quotable again
    _sync(db, [_bc(i) for i in range(10)])
    db.refresh(c)
    assert is_quotable_bc_customer(c)


def test_mass_disappearance_skips_pruning(db):
    _sync(db, [_bc(i) for i in range(10)])
    res = _sync(db, [_bc(0)])
    assert res["customers_removed"] == 0
    assert db.query(BCCustomer).count() == 10
    assert any("unsafe" in e for e in res["errors"])


def test_blocked_all_hidden_from_picker(db):
    _sync(db, [_bc(1, blocked="All"), _bc(2, blocked="Ship"), _bc(3)])
    by_id = {c.bc_customer_id: c for c in db.query(BCCustomer)}
    assert not is_quotable_bc_customer(by_id["guid-1"])
    assert is_quotable_bc_customer(by_id["guid-2"])
    assert is_quotable_bc_customer(by_id["guid-3"])
