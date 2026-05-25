"""Part Finder — portal host adapter.

The Part Finder logic lives in the SHARED core at
`app/services/part_finder/` (synced from the standalone ohd-part-finder repo via
its tools/sync_core.py — do not edit the core here; edit it there and re-sync).

This file is the portal-specific adapter: it wires the core's host-agnostic
`build_router(...)` factory to the portal's auth (a logged-in JWT grants full
access) and the portal's settings. It is NOT part of the synced core.

Mounted in main.py as `part_finder.router`.
"""

from __future__ import annotations

from fastapi import Request

from app.config import settings
from app.services.part_finder.api import build_router
from app.services.part_finder.config import IngestConfig


def access_level(request: Request) -> str:
    """'full' for a valid logged-in portal token, else 'preview'. Never raises —
    the Part Finder is usable anonymously, just gated."""
    auth = request.headers.get("authorization") or ""
    if not auth.lower().startswith("bearer "):
        return "preview"
    token = auth.split(" ", 1)[1].strip()
    try:
        from app.services.auth_service import auth_service

        payload = auth_service.decode_token(token)
        if payload and payload.get("sub"):
            return "full"
    except Exception:
        pass
    return "preview"


router = build_router(
    cfg=IngestConfig(),
    access_level=access_level,
    anthropic_api_key=settings.ANTHROPIC_API_KEY,
)
