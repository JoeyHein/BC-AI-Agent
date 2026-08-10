"""Telemetry event scaffold — OHD Part Finder §3 pilot metrics.

All events share a stable JSON schema:
  { "event": str, "ts_utc": ISO-8601, "session_id": str, ...event-specific fields }

Events: id_started · id_result · manual_opened · search · feedback

Default sink: Python logger at INFO.  An optional JSONL file sink is built-in;
additional sinks (remote ingest, DB) can be registered at app startup via add_sink().

PII policy: no raw IP, no email, no query text.  Retained fields: session_id
(opaque token from header/cookie or hashed IP), photo_hash (SHA-256 hex of the
uploaded bytes), query_len (integer).
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)

Sink = Callable[[dict], None]

_sinks: list[Sink] = []
_sinks_lock = threading.Lock()


def _log_sink(event: dict) -> None:
    logger.info("telemetry %s", json.dumps(event, default=str))


# Log sink is always present.
_sinks.append(_log_sink)


def add_sink(sink: Sink) -> None:
    """Register an additional event sink (thread-safe)."""
    with _sinks_lock:
        _sinks.append(sink)


def _make_jsonl_sink(path: Path) -> Sink:
    lock = threading.Lock()

    def sink(event: dict) -> None:
        line = json.dumps(event, default=str) + "\n"
        with lock:
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(line)

    return sink


def enable_jsonl_sink(path: str | Path) -> None:
    """Activate the JSONL file sink.  Call once at app startup."""
    add_sink(_make_jsonl_sink(Path(path)))


def _emit(event_name: str, **fields) -> None:
    record: dict = {
        "event": event_name,
        "ts_utc": datetime.now(timezone.utc).isoformat(),
        **fields,
    }
    with _sinks_lock:
        sinks = list(_sinks)
    for sink in sinks:
        try:
            sink(record)
        except Exception:
            logger.exception("telemetry sink error (event=%s)", event_name)


# ---- Helpers -----------------------------------------------------------------

def photo_hash(image_bytes: bytes) -> str:
    """SHA-256 hex of the raw image bytes — ties id_started to id_result."""
    return hashlib.sha256(image_bytes).hexdigest()


def session_id_from_request(request) -> str:
    """Derive an opaque session ID from a FastAPI Request.

    Priority: X-Session-ID header > session_id cookie > hashed remote IP.
    No raw IP is stored; the hash is truncated to 16 hex chars.
    """
    sid = request.headers.get("x-session-id")
    if sid:
        return str(sid)[:64]
    cookie = request.cookies.get("session_id")
    if cookie:
        return str(cookie)[:64]
    ip = (request.client.host if request.client else "unknown")
    return "ip:" + hashlib.sha256(ip.encode()).hexdigest()[:16]


# ---- Public event emitters ---------------------------------------------------

def id_started(
    session_id: str,
    photo_hash_hex: str,
    category_hint: Optional[str],
) -> None:
    """Emitted at the start of a /identify request, before the Vision call."""
    _emit(
        "id_started",
        session_id=session_id,
        photo_hash=photo_hash_hex,
        category_hint=category_hint,
    )


def id_result(
    session_id: str,
    photo_hash_hex: str,
    *,
    success: bool,
    top_brand: Optional[str],
    top_confidence: Optional[float],
    candidate_count: int,
    latency_ms: float,
    cache_read_tokens: int,
) -> None:
    """Emitted after /identify completes (success or error)."""
    _emit(
        "id_result",
        session_id=session_id,
        photo_hash=photo_hash_hex,
        success=success,
        top_brand=top_brand,
        top_confidence=top_confidence,
        candidate_count=candidate_count,
        latency_ms=round(latency_ms, 1),
        cache_read_tokens=cache_read_tokens,
    )


def manual_opened(session_id: str, doc_id: str, filename: str) -> None:
    """Emitted when an authenticated user successfully opens a PDF manual."""
    _emit(
        "manual_opened",
        session_id=session_id,
        doc_id=doc_id,
        filename=filename,
    )


def search(
    session_id: str,
    query_len: int,
    category: Optional[str],
    result_count: int,
) -> None:
    """Emitted on every /search call.  Raw query text is not recorded."""
    _emit(
        "search",
        session_id=session_id,
        query_len=query_len,
        category=category,
        result_count=result_count,
    )


def feedback(
    session_id: str,
    photo_hash_hex: str,
    *,
    was_correct: bool,
    corrected_brand: Optional[str],
) -> None:
    """Emitted when a user submits feedback on an identification result."""
    _emit(
        "feedback",
        session_id=session_id,
        photo_hash=photo_hash_hex,
        was_correct=was_correct,
        corrected_brand=corrected_brand,
    )
