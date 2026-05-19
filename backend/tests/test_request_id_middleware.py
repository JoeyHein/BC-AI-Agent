"""Request-ID middleware tests (SQB-11).

Asserts:
    - When the inbound request carries `X-Request-ID`, the response
      echoes the same value back.
    - When no inbound header is present, the middleware generates a
      UUID and includes it on the response.
    - `request.state.request_id` is populated for downstream handlers.

The middleware is the outermost layer in main.py; here we mount only
the middleware on a stub FastAPI app so the test stays fast and
doesn't drag in the BC OData client init.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.main import RequestIdMiddleware


def _build_app() -> FastAPI:
    app = FastAPI()

    @app.get("/probe")
    async def probe(request: Request):
        return {
            "ok": True,
            "request_id_seen_by_handler": request.state.request_id,
        }

    app.add_middleware(RequestIdMiddleware)
    return app


class TestRequestIdMiddleware:
    def test_echoes_inbound_request_id(self):
        client = TestClient(_build_app())
        res = client.get("/probe", headers={"X-Request-ID": "trace-abc-123"})
        assert res.status_code == 200
        assert res.headers["X-Request-ID"] == "trace-abc-123"
        body = res.json()
        assert body["request_id_seen_by_handler"] == "trace-abc-123"

    def test_generates_uuid_when_no_inbound_header(self):
        client = TestClient(_build_app())
        res = client.get("/probe")
        assert res.status_code == 200
        rid = res.headers.get("X-Request-ID")
        assert rid is not None
        # UUIDv4 shape: 8-4-4-4-12 hex
        import re
        assert re.match(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
            rid,
            re.IGNORECASE,
        ), f"expected a UUID, got {rid!r}"
        # The handler sees the same id.
        assert res.json()["request_id_seen_by_handler"] == rid

    def test_each_request_gets_a_distinct_generated_id(self):
        client = TestClient(_build_app())
        a = client.get("/probe").headers["X-Request-ID"]
        b = client.get("/probe").headers["X-Request-ID"]
        assert a != b
