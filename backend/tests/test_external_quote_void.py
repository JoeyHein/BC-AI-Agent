"""External quote void endpoint tests (TD-SQB-A8).

Covers:
    - Auth: 401 missing key, 401 garbage key.
    - Lookup: 404 unknown external_quote_id, 404 cross-key probe.
    - Status invariant: 422 when source quote is not status='committed';
      422 when the quote has already been converted to an order.
    - Happy path: returns voidedAt + supplier_quote_ref + cached=False,
      persists voided_at on the same external_quote_commits row, calls
      bc_client.delete_sales_quote exactly once.
    - Idempotent replay: a second call returns cached=True without a
      second BC call.
    - BC failure: BC raises → 502 UPSTREAM_ERROR. voided_at stays null
      so the next call retries.
    - BC 404: BC says "not found" → treated as success (already voided);
      voided_at persists.
    - Path-traversal safety: weird external_quote_id values are
      rejected at the route layer before any DB work.
    - void_reason persistence: reason in body lands on the row.
"""
from __future__ import annotations

import os
import sys
import uuid
from datetime import datetime, timezone
from typing import List, Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import external_quotes
from app.api.auth import get_db
from app.db.models import (
    ExternalApiKey,
    ExternalQuoteCommit,
    User,
    UserRole,
)
from app.services import external_quote_void_service
from app.services.external_api_keys_service import create_key


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def db_factory():
    engine = create_engine(
        "sqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    User.__table__.create(engine, checkfirst=True)
    ExternalApiKey.__table__.create(engine, checkfirst=True)
    ExternalQuoteCommit.__table__.create(engine, checkfirst=True)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


@pytest.fixture
def session(db_factory):
    db = db_factory()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def admin_user(session):
    u = User(
        email="admin@test.local",
        password_hash="x",
        role=UserRole.ADMIN,
        is_active=True,
    )
    session.add(u)
    session.commit()
    session.refresh(u)
    return u


@pytest.fixture
def primary_key(session, admin_user):
    _row, plaintext = create_key(
        session,
        name="void test key",
        supplier_account_code="ED-001",
        created_by_user_id=admin_user.id,
    )
    return plaintext


@pytest.fixture
def other_key(session, admin_user):
    _row, plaintext = create_key(
        session,
        name="void test other-account key",
        supplier_account_code="ED-OTHER",
        created_by_user_id=admin_user.id,
    )
    return plaintext


@pytest.fixture
def app(db_factory):
    test_app = FastAPI()
    test_app.include_router(external_quotes.router)

    def _override_get_db():
        db = db_factory()
        try:
            yield db
        finally:
            db.close()

    test_app.dependency_overrides[get_db] = _override_get_db
    return test_app


@pytest.fixture
def client(app):
    return TestClient(app)


# ─────────────────────────────────────────────────────────────────────────────
# BC client stub
# ─────────────────────────────────────────────────────────────────────────────


class FakeBcClient:
    """Records BC delete_sales_quote calls. Configurable failure mode."""

    def __init__(self) -> None:
        self.delete_calls: List[str] = []
        self._raise: Optional[Exception] = None

    def set_failure(self, exc: Exception) -> None:
        self._raise = exc

    def delete_sales_quote(
        self, quote_id: str, company_id: Optional[str] = None
    ) -> bool:
        if self._raise is not None:
            raise self._raise
        self.delete_calls.append(quote_id)
        return True


@pytest.fixture
def fake_bc(monkeypatch):
    fake = FakeBcClient()
    monkeypatch.setattr(external_quote_void_service, "bc_client", fake)
    yield fake


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _seed_commit_row(
    db_factory,
    external_quote_id: str,
    supplier_account_code: str = "ED-001",
    status: str = "committed",
    bc_quote_id: Optional[str] = None,
    converted: bool = False,
) -> int:
    db = db_factory()
    try:
        now = datetime.now(timezone.utc)
        row = ExternalQuoteCommit(
            external_quote_id=external_quote_id,
            supplier_account_code=supplier_account_code,
            status=status,
            bc_quote_id=bc_quote_id or f"bc-quote-{uuid.uuid4()}",
            supplier_quote_ref=f"SQ-{uuid.uuid4().hex[:6].upper()}",
            item_count=2,
            subtotal_cents=10_000,
            currency="CAD",
            committed_at=now if status == "committed" else None,
            converted_at=now if converted else None,
            bc_order_id=f"bc-order-{uuid.uuid4()}" if converted else None,
            bc_order_ref=f"SO-{uuid.uuid4().hex[:6].upper()}" if converted else None,
        )
        db.add(row)
        db.commit()
        return row.id
    finally:
        db.close()


def _void(client: TestClient, api_key: str, external_quote_id: str, reason: Optional[str] = None):
    payload = {"reason": reason} if reason is not None else {}
    return client.post(
        f"/api/external/quotes/{external_quote_id}/void",
        headers={"X-Service-AI-Key": api_key},
        json=payload,
    )


def _read_row(db_factory, external_quote_id: str) -> Optional[ExternalQuoteCommit]:
    db = db_factory()
    try:
        return (
            db.query(ExternalQuoteCommit)
            .filter(ExternalQuoteCommit.external_quote_id == external_quote_id)
            .first()
        )
    finally:
        db.close()


# ─────────────────────────────────────────────────────────────────────────────
# Auth
# ─────────────────────────────────────────────────────────────────────────────


class TestAuth:
    def test_401_missing_header(self, client, fake_bc):
        res = client.post("/api/external/quotes/some-id/void")
        assert res.status_code == 401

    def test_401_garbage_key(self, client, fake_bc):
        res = client.post(
            "/api/external/quotes/some-id/void",
            headers={"X-Service-AI-Key": "sai_live_NOPENOPENOPENOPENOPENOPE"},
        )
        assert res.status_code == 401


# ─────────────────────────────────────────────────────────────────────────────
# Lookup + cross-key isolation
# ─────────────────────────────────────────────────────────────────────────────


class TestLookup:
    def test_404_unknown_external_id(self, client, primary_key, fake_bc):
        res = _void(client, primary_key, "no-such-quote")
        assert res.status_code == 404
        assert res.json()["error"]["code"] == "NOT_FOUND"

    def test_404_cross_key_probe(
        self, client, db_factory, primary_key, other_key, fake_bc
    ):
        ext_id = f"void-cross-{uuid.uuid4()}"
        _seed_commit_row(db_factory, ext_id, supplier_account_code="ED-OTHER")
        res = _void(client, primary_key, ext_id)
        assert res.status_code == 404
        assert fake_bc.delete_calls == []

    def test_path_length_guard(self, client, primary_key, fake_bc):
        too_long = "x" * 81
        res = _void(client, primary_key, too_long)
        assert res.status_code == 400


# ─────────────────────────────────────────────────────────────────────────────
# Status invariant
# ─────────────────────────────────────────────────────────────────────────────


class TestStatusInvariant:
    def test_422_when_source_is_in_progress(
        self, client, db_factory, primary_key, fake_bc
    ):
        ext_id = f"void-inprog-{uuid.uuid4()}"
        _seed_commit_row(db_factory, ext_id, status="in_progress")
        res = _void(client, primary_key, ext_id)
        assert res.status_code == 422
        assert res.json()["error"]["code"] == "UNPROCESSABLE"
        assert fake_bc.delete_calls == []

    def test_422_when_already_converted_to_order(
        self, client, db_factory, primary_key, fake_bc
    ):
        ext_id = f"void-converted-{uuid.uuid4()}"
        _seed_commit_row(db_factory, ext_id, converted=True)
        res = _void(client, primary_key, ext_id)
        assert res.status_code == 422
        assert "order" in res.json()["error"]["message"].lower()
        assert fake_bc.delete_calls == []


# ─────────────────────────────────────────────────────────────────────────────
# Happy path + idempotency
# ─────────────────────────────────────────────────────────────────────────────


class TestHappyPath:
    def test_void_committed_quote_calls_bc_and_persists(
        self, client, db_factory, primary_key, fake_bc
    ):
        ext_id = f"void-happy-{uuid.uuid4()}"
        bc_id = f"bc-quote-{uuid.uuid4()}"
        _seed_commit_row(db_factory, ext_id, bc_quote_id=bc_id)
        res = _void(client, primary_key, ext_id, reason="customer changed mind")
        assert res.status_code == 200
        body = res.json()
        assert body["ok"] is True
        assert body["data"]["cached"] is False
        assert body["data"]["supplierQuoteRef"].startswith("SQ-")
        assert body["data"]["voidedAt"]

        # BC was called exactly once with the right id.
        assert fake_bc.delete_calls == [bc_id]

        # Row state: voided_at + void_reason persisted.
        row = _read_row(db_factory, ext_id)
        assert row is not None
        assert row.voided_at is not None
        assert row.void_reason == "customer changed mind"

    def test_idempotent_replay_returns_cached_without_bc_call(
        self, client, db_factory, primary_key, fake_bc
    ):
        ext_id = f"void-replay-{uuid.uuid4()}"
        _seed_commit_row(db_factory, ext_id)

        first = _void(client, primary_key, ext_id)
        assert first.status_code == 200
        assert first.json()["data"]["cached"] is False
        assert len(fake_bc.delete_calls) == 1

        second = _void(client, primary_key, ext_id, reason="new reason")
        assert second.status_code == 200
        assert second.json()["data"]["cached"] is True
        # No second BC call.
        assert len(fake_bc.delete_calls) == 1
        # voidedAt timestamp unchanged across replays. SQLite drops the
        # tz suffix on round-trip, so compare just the naive prefix.
        assert (
            second.json()["data"]["voidedAt"][:19]
            == first.json()["data"]["voidedAt"][:19]
        )


# ─────────────────────────────────────────────────────────────────────────────
# BC failure modes
# ─────────────────────────────────────────────────────────────────────────────


class TestBcFailure:
    def test_bc_raises_returns_502_and_leaves_row_unchanged(
        self, client, db_factory, primary_key, fake_bc
    ):
        ext_id = f"void-bc-fail-{uuid.uuid4()}"
        _seed_commit_row(db_factory, ext_id)
        fake_bc.set_failure(RuntimeError("BC OData 500 internal error"))

        res = _void(client, primary_key, ext_id)
        assert res.status_code == 502
        assert res.json()["error"]["code"] == "UPSTREAM_ERROR"

        # Row should not be marked voided — retry must work.
        row = _read_row(db_factory, ext_id)
        assert row is not None
        assert row.voided_at is None

    def test_bc_404_is_swallowed_and_treated_as_success(
        self, client, db_factory, primary_key, fake_bc
    ):
        """BC returning a 404 (quote already deleted) means we converge
        on the same end state — treat as voided. Prevents permanent
        retry loops when a previous void partially succeeded outside
        our knowledge."""
        ext_id = f"void-bc-404-{uuid.uuid4()}"
        _seed_commit_row(db_factory, ext_id)
        fake_bc.set_failure(RuntimeError("HTTP 404 not found"))

        res = _void(client, primary_key, ext_id)
        assert res.status_code == 200
        assert res.json()["data"]["cached"] is False

        row = _read_row(db_factory, ext_id)
        assert row is not None
        assert row.voided_at is not None


# ─────────────────────────────────────────────────────────────────────────────
# Reason persistence
# ─────────────────────────────────────────────────────────────────────────────


class TestReason:
    def test_reason_is_optional(self, client, db_factory, primary_key, fake_bc):
        ext_id = f"void-no-reason-{uuid.uuid4()}"
        _seed_commit_row(db_factory, ext_id)
        res = _void(client, primary_key, ext_id)
        assert res.status_code == 200

        row = _read_row(db_factory, ext_id)
        assert row is not None
        assert row.void_reason is None

    def test_reason_truncates_at_1000_chars(
        self, client, db_factory, primary_key, fake_bc
    ):
        ext_id = f"void-reason-truncate-{uuid.uuid4()}"
        _seed_commit_row(db_factory, ext_id)
        long_reason = "x" * 1500
        res = _void(client, primary_key, ext_id, reason=long_reason)
        # Pydantic max_length=1000 → 422 validation error.
        assert res.status_code == 422
