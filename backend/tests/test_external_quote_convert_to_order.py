"""External quote-to-order conversion endpoint tests (QOC-04 / M1 audit fix).

Covers:
    - Auth: 401 missing key, 401 garbage key.
    - Lookup: 404 unknown external_quote_id, 404 cross-key probe.
    - Status invariant: 422 when source quote is not status='committed'
      (in_progress, failed).
    - Happy path: returns SO-XXXXXX + supplier_order_id + orderedAt,
      persists bc_order_id/bc_order_ref/converted_at on the same
      external_quote_commits row.
    - Idempotent replay: a second call returns the cached SO-XXXXXX
      without a second BC call. Verified by counting calls on the fake
      BC client.
    - Empty BC return: BC returns no id or no number → UPSTREAM_ERROR,
      bc_order_* stays null so the next call retries.
    - BC failure: BC raises → 502 UPSTREAM_ERROR. The row's status
      column stays 'committed' (NOT marked 'failed'); only the
      bc_order_* columns stay null. A retry succeeds.
    - Path-traversal safety: weird external_quote_id values are
      rejected at the route layer before any DB work.
"""
from __future__ import annotations

import os
import sys
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

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
from app.services import external_order_conversion_service
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
        name="QOC-04 test key",
        supplier_account_code="ED-001",
        created_by_user_id=admin_user.id,
    )
    return plaintext


@pytest.fixture
def other_key(session, admin_user):
    _row, plaintext = create_key(
        session,
        name="QOC-04 other-account key",
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
    """Records BC calls. convert_quote_to_order returns a deterministic
    GUID + sequential SO-NNNNNN unless wired to fail."""

    def __init__(self) -> None:
        self.convert_calls: List[str] = []
        self._serial = 200_000
        self._raise: Optional[Exception] = None
        self._empty_return = False
        self._delay_s: float = 0.0
        self._lock = __import__("threading").Lock()

    def set_failure(self, exc: Exception) -> None:
        self._raise = exc

    def set_empty_return(self) -> None:
        self._empty_return = True

    def set_delay(self, seconds: float) -> None:
        self._delay_s = seconds

    def convert_quote_to_order(
        self, quote_id: str, company_id: Optional[str] = None
    ) -> Dict[str, Any]:
        if self._raise is not None:
            raise self._raise
        if self._delay_s:
            __import__("time").sleep(self._delay_s)
        with self._lock:
            self.convert_calls.append(quote_id)
        if self._empty_return:
            return {}  # exercise the empty-id guard
        self._serial += 1
        return {
            "id": str(uuid.uuid4()),
            "number": f"SO-{self._serial:06d}",
        }


@pytest.fixture
def fake_bc(monkeypatch):
    fake = FakeBcClient()
    monkeypatch.setattr(
        external_order_conversion_service, "bc_client", fake,
    )
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
) -> int:
    db = db_factory()
    try:
        row = ExternalQuoteCommit(
            external_quote_id=external_quote_id,
            supplier_account_code=supplier_account_code,
            status=status,
            bc_quote_id=bc_quote_id or f"bc-quote-{uuid.uuid4()}",
            supplier_quote_ref=f"SQ-{uuid.uuid4().hex[:6].upper()}",
            item_count=2,
            subtotal_cents=10_000,
            currency="CAD",
            committed_at=datetime.now(timezone.utc) if status == "committed" else None,
        )
        db.add(row)
        db.commit()
        return row.id
    finally:
        db.close()


def _convert(client: TestClient, api_key: str, external_quote_id: str):
    return client.post(
        f"/api/external/quotes/{external_quote_id}/convert-to-order",
        headers={"X-Service-AI-Key": api_key},
    )


# ─────────────────────────────────────────────────────────────────────────────
# Auth
# ─────────────────────────────────────────────────────────────────────────────


class TestAuth:
    def test_401_missing_header(self, client, fake_bc):
        res = client.post("/api/external/quotes/some-id/convert-to-order")
        assert res.status_code == 401

    def test_422_rejects_extra_body_fields(self, client, primary_key, fake_bc):
        # TD-QOC-A6: the convert body is keyed on the path; extra fields are
        # rejected (model_config extra='forbid'). An empty body still works.
        res = client.post(
            "/api/external/quotes/some-id/convert-to-order",
            headers={"X-Service-AI-Key": primary_key},
            json={"unexpected": "field"},
        )
        assert res.status_code == 422

    def test_401_garbage_key(self, client, fake_bc):
        res = client.post(
            "/api/external/quotes/some-id/convert-to-order",
            headers={"X-Service-AI-Key": "sai_live_NOPENOPENOPENOPENOPENOPE"},
        )
        assert res.status_code == 401


# ─────────────────────────────────────────────────────────────────────────────
# Lookup + cross-key isolation
# ─────────────────────────────────────────────────────────────────────────────


class TestLookup:
    def test_404_unknown_external_id(self, client, primary_key, fake_bc):
        res = _convert(client, primary_key, "no-such-quote")
        assert res.status_code == 404
        body = res.json()
        assert body["error"]["code"] == "NOT_FOUND"

    def test_404_cross_key_probe(self, client, db_factory, primary_key, other_key, fake_bc):
        """A quote committed under ED-OTHER must NOT be visible to the
        ED-001 key — same 404 semantics as the rest of the external
        surface."""
        ext_id = f"qoc-cross-{uuid.uuid4()}"
        _seed_commit_row(db_factory, ext_id, supplier_account_code="ED-OTHER")
        res = _convert(client, primary_key, ext_id)
        assert res.status_code == 404
        # And no BC traffic happened (the lookup short-circuited).
        assert fake_bc.convert_calls == []

    def test_path_length_guard(self, client, primary_key, fake_bc):
        too_long = "x" * 81
        res = _convert(client, primary_key, too_long)
        assert res.status_code == 400


# ─────────────────────────────────────────────────────────────────────────────
# Status invariant
# ─────────────────────────────────────────────────────────────────────────────


class TestStatusInvariant:
    def test_422_when_source_is_in_progress(
        self, client, db_factory, primary_key, fake_bc
    ):
        ext_id = f"qoc-inprog-{uuid.uuid4()}"
        _seed_commit_row(db_factory, ext_id, status="in_progress")
        res = _convert(client, primary_key, ext_id)
        assert res.status_code == 422
        assert res.json()["error"]["code"] == "UNPROCESSABLE"
        assert fake_bc.convert_calls == []

    def test_422_when_source_is_failed(
        self, client, db_factory, primary_key, fake_bc
    ):
        ext_id = f"qoc-failed-{uuid.uuid4()}"
        _seed_commit_row(db_factory, ext_id, status="failed")
        res = _convert(client, primary_key, ext_id)
        assert res.status_code == 422
        assert fake_bc.convert_calls == []


# ─────────────────────────────────────────────────────────────────────────────
# Happy path + idempotency replay
# ─────────────────────────────────────────────────────────────────────────────


class TestHappyPath:
    def test_returns_so_ref_and_persists(
        self, client, db_factory, primary_key, fake_bc
    ):
        ext_id = f"qoc-happy-{uuid.uuid4()}"
        row_id = _seed_commit_row(db_factory, ext_id)

        res = _convert(client, primary_key, ext_id)
        assert res.status_code == 200
        body = res.json()
        assert body["ok"] is True
        assert body["data"]["supplierOrderRef"].startswith("SO-")
        assert body["data"]["supplierOrderId"]
        assert body["data"]["orderedAt"]
        assert body["data"]["cached"] is False
        assert len(fake_bc.convert_calls) == 1

        # Row was updated.
        db = db_factory()
        try:
            row = (
                db.query(ExternalQuoteCommit)
                .filter(ExternalQuoteCommit.id == row_id)
                .first()
            )
            assert row is not None
            assert row.bc_order_ref == body["data"]["supplierOrderRef"]
            assert row.bc_order_id == body["data"]["supplierOrderId"]
            assert row.converted_at is not None
            # Status column is untouched — the commit succeeded earlier.
            assert row.status == "committed"
        finally:
            db.close()

    def test_idempotent_replay_returns_cached_and_skips_bc(
        self, client, db_factory, primary_key, fake_bc
    ):
        ext_id = f"qoc-replay-{uuid.uuid4()}"
        _seed_commit_row(db_factory, ext_id)

        first = _convert(client, primary_key, ext_id)
        assert first.status_code == 200
        first_data = first.json()["data"]
        assert first_data["cached"] is False

        second = _convert(client, primary_key, ext_id)
        assert second.status_code == 200
        second_data = second.json()["data"]
        assert second_data["cached"] is True
        assert second_data["supplierOrderRef"] == first_data["supplierOrderRef"]
        assert second_data["supplierOrderId"] == first_data["supplierOrderId"]

        # Crucial: BC was called exactly once across both attempts.
        assert len(fake_bc.convert_calls) == 1


# ─────────────────────────────────────────────────────────────────────────────
# BC failure modes
# ─────────────────────────────────────────────────────────────────────────────


class TestBcFailures:
    def test_bc_raises_returns_502_and_does_not_mark_row_failed(
        self, client, db_factory, primary_key, fake_bc
    ):
        ext_id = f"qoc-bcfail-{uuid.uuid4()}"
        row_id = _seed_commit_row(db_factory, ext_id)
        fake_bc.set_failure(RuntimeError("simulated BC outage"))

        res = _convert(client, primary_key, ext_id)
        assert res.status_code == 502
        body = res.json()
        assert body["error"]["code"] == "UPSTREAM_ERROR"

        db = db_factory()
        try:
            row = (
                db.query(ExternalQuoteCommit)
                .filter(ExternalQuoteCommit.id == row_id)
                .first()
            )
            assert row is not None
            # The commit succeeded earlier — only the conversion failed.
            # status must NOT be 'failed' (that would mask the successful commit).
            assert row.status == "committed"
            assert row.bc_order_id is None
            assert row.bc_order_ref is None
            assert row.converted_at is None
        finally:
            db.close()

    def test_retry_after_bc_recovers_succeeds(
        self, client, db_factory, primary_key, fake_bc
    ):
        ext_id = f"qoc-retry-{uuid.uuid4()}"
        _seed_commit_row(db_factory, ext_id)
        fake_bc.set_failure(RuntimeError("transient"))

        first = _convert(client, primary_key, ext_id)
        assert first.status_code == 502

        # BC recovers.
        fake_bc._raise = None  # noqa: SLF001 — test-only access
        second = _convert(client, primary_key, ext_id)
        assert second.status_code == 200
        assert second.json()["data"]["cached"] is False

    def test_empty_bc_return_returns_502(
        self, client, db_factory, primary_key, fake_bc
    ):
        ext_id = f"qoc-empty-{uuid.uuid4()}"
        _seed_commit_row(db_factory, ext_id)
        fake_bc.set_empty_return()

        res = _convert(client, primary_key, ext_id)
        assert res.status_code == 502
        body = res.json()
        assert body["error"]["code"] == "UPSTREAM_ERROR"


# ─────────────────────────────────────────────────────────────────────────────
# Concurrency (TD-QOC-A1)
# ─────────────────────────────────────────────────────────────────────────────


class TestConcurrency:
    def test_10x_concurrent_conversions_yield_one_bc_call(self, db_factory, fake_bc):
        """The HTTP TestClient isn't reliably thread-safe under pytest;
        like the commit concurrency test, this exercises the idempotency
        contract directly against the service — the load-bearing piece.
        Ten threads convert the same external_quote_id; the per-key lock
        plus the converted_at replay guard must collapse them to at most
        one BC convert_quote_to_order call."""
        import threading

        from app.services.external_order_conversion_service import (
            ConvertResult,
            convert_external_quote_to_order,
        )

        # Slow the BC convert so the 10 threads genuinely overlap inside
        # the critical section.
        fake_bc.set_delay(0.05)
        ext_id = f"qoc-concurrent-{uuid.uuid4()}"
        _seed_commit_row(db_factory, ext_id)

        results: List[Any] = []
        errors: List[Exception] = []
        lock = threading.Lock()

        def worker():
            db = db_factory()
            try:
                res = convert_external_quote_to_order(
                    db,
                    api_key_id=None,
                    account_code="ED-001",
                    external_quote_id=ext_id,
                )
                with lock:
                    results.append(res)
            except Exception as exc:  # noqa: BLE001
                with lock:
                    errors.append(exc)
            finally:
                db.close()

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"thread errors: {errors}"
        # At most one BC convert call across all 10 racers.
        assert len(fake_bc.convert_calls) <= 1, (
            f"expected ≤1 BC convert, got {len(fake_bc.convert_calls)}"
        )
        # All 10 came back as ConvertResult with the same order ref.
        refs = {r.supplier_order_ref for r in results if isinstance(r, ConvertResult)}
        assert len(refs) == 1, f"expected one distinct order ref, got {refs}"
