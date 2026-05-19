"""External quote commit endpoint tests (SQB-05).

Covers:
    - Auth: 401 missing key, 401 garbage key, 404 account mismatch.
    - Body validation: empty items, qty 0, missing fields → 422.
    - Happy path: returns SQ-XXXXXX + valid_until.
    - Idempotent replay: same external_quote_id → cached response,
      no second BC call.
    - Idempotency conflict: same external_quote_id used for a
      different account_code → 409.
    - Different external_quote_ids → distinct BC calls + distinct refs.
    - **10× concurrent commits** with the same external_quote_id all
      collapse to one BC create call + one ref.
    - Failure handling: BC raises on create → 502, status='failed',
      caller can retry.
"""
from __future__ import annotations

import os
import sys
import threading
import uuid
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
    BCCustomer,
    ExternalApiKey,
    ExternalQuoteCommit,
    User,
    UserRole,
)
from app.services import external_quote_service
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
    BCCustomer.__table__.create(engine, checkfirst=True)
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
    u = User(email="admin@test.local", password_hash="x", role=UserRole.ADMIN, is_active=True)
    session.add(u)
    session.commit()
    session.refresh(u)
    return u


@pytest.fixture
def api_key(session, admin_user):
    _row, plaintext = create_key(
        session,
        name="SQB-05 test key",
        supplier_account_code="ED-001",
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
    """Records BC calls. create_sales_quote returns a deterministic
    GUID + sequential SQ-NNNNNN. add_quote_line is a no-op recorder."""

    def __init__(self) -> None:
        self.create_calls: List[Dict[str, Any]] = []
        self.line_calls: List[tuple[str, Dict[str, Any]]] = []
        self._serial = 100_000
        self._raise_on_create: Optional[Exception] = None
        self._raise_on_line: Optional[Exception] = None
        self._create_delay_s: float = 0.0
        self._lock = threading.Lock()

    def set_create_failure(self, exc: Exception) -> None:
        self._raise_on_create = exc

    def set_line_failure(self, exc: Exception) -> None:
        self._raise_on_line = exc

    def set_create_delay(self, seconds: float) -> None:
        self._create_delay_s = seconds

    def create_sales_quote(self, quote_data: Dict[str, Any], company_id: Optional[str] = None) -> Dict[str, Any]:
        if self._raise_on_create is not None:
            raise self._raise_on_create
        if self._create_delay_s > 0:
            # Hold for a moment so racers actually overlap.
            import time
            time.sleep(self._create_delay_s)
        with self._lock:
            self._serial += 1
            serial = self._serial
            self.create_calls.append(quote_data)
        return {
            "id": f"bc-{serial}",
            "number": f"SQ-{serial:06d}",
        }

    def add_quote_line(self, quote_id: str, line_data: Dict[str, Any], company_id: Optional[str] = None) -> Dict[str, Any]:
        if self._raise_on_line is not None:
            raise self._raise_on_line
        with self._lock:
            self.line_calls.append((quote_id, line_data))
        return {"id": f"line-{uuid.uuid4()}"}


@pytest.fixture
def fake_bc(monkeypatch):
    fake = FakeBcClient()
    monkeypatch.setattr(external_quote_service, "bc_client", fake)
    yield fake


def _post(client: TestClient, api_key: str, body: Dict[str, Any]):
    return client.post(
        "/api/external/quotes",
        headers={"X-Service-AI-Key": api_key},
        json=body,
    )


def _make_body(external_quote_id: Optional[str] = None, account: str = "ED-001"):
    return {
        "supplierAccountCode": account,
        "externalQuoteId": external_quote_id or str(uuid.uuid4()),
        "items": [
            {"sku": "PN10-A", "quantity": 2, "unitPriceCents": 12345},
            {"sku": "OP-LM-8500W", "quantity": 1, "unitPriceCents": 84900},
        ],
        "currency": "CAD",
        "notes": "Test commit",
    }


# ─────────────────────────────────────────────────────────────────────────────
# Auth + body validation
# ─────────────────────────────────────────────────────────────────────────────


class TestAuth:
    def test_401_missing_header(self, client, fake_bc):
        res = client.post("/api/external/quotes", json=_make_body())
        assert res.status_code == 401

    def test_401_garbage_key(self, client, fake_bc):
        res = client.post(
            "/api/external/quotes",
            headers={"X-Service-AI-Key": "sai_live_NOPENOPENOPENOPENOPENOPE"},
            json=_make_body(),
        )
        assert res.status_code == 401

    def test_404_account_code_mismatch(self, client, api_key, fake_bc):
        body = _make_body(account="SOMEONE-ELSE")
        res = _post(client, api_key, body)
        assert res.status_code == 404

    def test_422_empty_items(self, client, api_key, fake_bc):
        body = _make_body()
        body["items"] = []
        res = _post(client, api_key, body)
        assert res.status_code == 422

    def test_422_zero_qty(self, client, api_key, fake_bc):
        body = _make_body()
        body["items"][0]["quantity"] = 0
        res = _post(client, api_key, body)
        assert res.status_code == 422


# ─────────────────────────────────────────────────────────────────────────────
# Happy path + caching
# ─────────────────────────────────────────────────────────────────────────────


class TestHappyPath:
    def test_returns_ref_and_id(self, client, api_key, fake_bc):
        res = _post(client, api_key, _make_body())
        assert res.status_code == 200
        data = res.json()["data"]
        assert data["supplierQuoteRef"].startswith("SQ-")
        assert data["supplierQuoteId"].startswith("bc-")
        assert data["currency"] == "CAD"
        assert data["cached"] is False
        # One create, two line calls.
        assert len(fake_bc.create_calls) == 1
        assert len(fake_bc.line_calls) == 2

    def test_idempotent_replay_returns_cached(self, client, api_key, fake_bc):
        body = _make_body()
        first = _post(client, api_key, body).json()["data"]
        second = _post(client, api_key, body).json()["data"]
        assert second["supplierQuoteRef"] == first["supplierQuoteRef"]
        assert second["cached"] is True
        # Still only ONE BC create + 2 line calls — the replay did not
        # hit BC at all.
        assert len(fake_bc.create_calls) == 1
        assert len(fake_bc.line_calls) == 2

    def test_distinct_external_ids_yield_distinct_refs(self, client, api_key, fake_bc):
        a = _post(client, api_key, _make_body("ext-a")).json()["data"]
        b = _post(client, api_key, _make_body("ext-b")).json()["data"]
        assert a["supplierQuoteRef"] != b["supplierQuoteRef"]
        assert len(fake_bc.create_calls) == 2


# ─────────────────────────────────────────────────────────────────────────────
# Idempotency edge cases
# ─────────────────────────────────────────────────────────────────────────────


class TestIdempotency:
    def test_conflict_on_account_code_swap(self, session, client, api_key, fake_bc):
        ext = str(uuid.uuid4())
        # First commit lands under ED-001.
        _post(client, api_key, _make_body(ext, account="ED-001"))
        # Forge a key bound to a DIFFERENT account.
        _row, other_plaintext = create_key(
            session,
            name="other",
            supplier_account_code="OTHER-CODE",
        )
        # Same external_quote_id but body says OTHER-CODE. The body's
        # account_code matches the new key — but the server has the
        # external_quote_id bound to ED-001, so 409.
        res = client.post(
            "/api/external/quotes",
            headers={"X-Service-AI-Key": other_plaintext},
            json=_make_body(ext, account="OTHER-CODE"),
        )
        assert res.status_code == 409
        assert res.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"

    def test_replay_with_different_body_still_returns_cached_ref(
        self, client, api_key, fake_bc
    ):
        ext = str(uuid.uuid4())
        first = _post(client, api_key, _make_body(ext)).json()["data"]

        # Replay with a different quantity. The first ref wins.
        body = _make_body(ext)
        body["items"][0]["quantity"] = 99
        second = _post(client, api_key, body).json()["data"]
        assert second["supplierQuoteRef"] == first["supplierQuoteRef"]
        assert len(fake_bc.create_calls) == 1


# ─────────────────────────────────────────────────────────────────────────────
# Concurrency — the load-bearing test
# ─────────────────────────────────────────────────────────────────────────────


class TestConcurrency:
    def test_10x_concurrent_commits_yield_one_bc_doc(self, db_factory, fake_bc):
        """The HTTP TestClient isn't reliably thread-safe under pytest;
        this test exercises the same idempotency contract directly
        against the service — that's the load-bearing piece. The HTTP
        layer is a thin Pydantic wrapper around the service call."""
        from app.services.external_quote_service import (
            CommitLine,
            CommitResult,
            commit_external_quote,
        )

        # Slow the BC create so the 10 threads genuinely overlap inside
        # the critical section.
        fake_bc.set_create_delay(0.05)
        ext = str(uuid.uuid4())
        items = [
            CommitLine(sku="PN10-A", quantity=2, unit_price_cents=12345),
            CommitLine(sku="OP-LM-8500W", quantity=1, unit_price_cents=84900),
        ]

        results: List[Any] = []
        errors: List[Exception] = []
        lock = threading.Lock()

        def worker():
            db = db_factory()
            try:
                res = commit_external_quote(
                    db,
                    api_key_id=None,
                    account_code="ED-001",
                    external_quote_id=ext,
                    items=items,
                    currency="CAD",
                    notes=None,
                )
                with lock:
                    results.append(res)
            except Exception as exc:
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
        # Exactly one BC create call.
        assert len(fake_bc.create_calls) == 1, (
            f"expected 1 BC create, got {len(fake_bc.create_calls)}"
        )
        # All 10 came back as CommitResult, all with the same ref. At
        # most one carries cached=False (the winner); the rest carry
        # cached=True.
        refs = {r.supplier_quote_ref for r in results if isinstance(r, CommitResult)}
        assert refs == {"SQ-100001"}, f"expected single ref, got {refs}"
        cached_counts = sum(
            1 for r in results if isinstance(r, CommitResult) and r.cached
        )
        non_cached = sum(
            1 for r in results if isinstance(r, CommitResult) and not r.cached
        )
        assert non_cached == 1, f"expected exactly 1 winner, got {non_cached}"
        assert cached_counts == 9, f"expected 9 cached replays, got {cached_counts}"


# ─────────────────────────────────────────────────────────────────────────────
# Failure handling
# ─────────────────────────────────────────────────────────────────────────────


class TestFailureHandling:
    def test_bc_create_failure_returns_502(self, client, api_key, fake_bc):
        fake_bc.set_create_failure(RuntimeError("BC tenant offline"))
        res = _post(client, api_key, _make_body())
        assert res.status_code == 502
        assert res.json()["error"]["code"] == "UPSTREAM_ERROR"
        assert res.json()["error"]["retryable"] is True

    def test_retry_after_failure_creates_new_bc_doc(self, session, client, api_key, fake_bc):
        ext = str(uuid.uuid4())
        fake_bc.set_create_failure(RuntimeError("BC tenant offline"))
        first = _post(client, api_key, _make_body(ext))
        assert first.status_code == 502

        # Clear failure and retry the SAME external_quote_id. Should
        # now succeed — the prior row was status='failed' so retry
        # falls through to actually call BC.
        fake_bc.set_create_failure(None)  # type: ignore[arg-type]
        # Reach in to clear since set_create_failure typed for Exception:
        fake_bc._raise_on_create = None

        second = _post(client, api_key, _make_body(ext))
        assert second.status_code == 200
        assert second.json()["data"]["supplierQuoteRef"].startswith("SQ-")
        assert len(fake_bc.create_calls) == 1  # only the retry succeeded
