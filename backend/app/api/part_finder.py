"""Part Finder API — visual product identification + manual lookup.

Public-facing (gated) endpoints over the Part Finder index built by
backend/app/services/part_finder. Anonymous users get a free *preview*
(brand browse, limited search hits, an identification guess); authenticated
users get full results, complete part-number cross-references, and manual
(PDF) downloads.

Routes are mounted under /api/part-finder.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.config import settings
from app.services.part_finder.config import IngestConfig
from app.services.part_finder.store import PartFinderStore

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/part-finder", tags=["part-finder"])

_cfg = IngestConfig()
_store = PartFinderStore(_cfg.db_path)

# How many results an anonymous (preview) user may see before the paywall.
PREVIEW_LIMIT = 3


# ---------------------------------------------------------------------------
# Access level (optional auth -> preview vs full)
# ---------------------------------------------------------------------------
def access_level(request: Request) -> str:
    """'full' for a valid logged-in token, else 'preview'. Never raises —
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


def _require_index():
    if not _store.available:
        raise HTTPException(
            status_code=503,
            detail="Part Finder index not built yet. Run scripts/partfinder_ingest.py.",
        )


def _gate_list(items: list, level: str) -> dict:
    """Wrap a result list with paywall metadata for preview users."""
    if level == "full":
        return {"locked": False, "total": len(items), "shown": len(items), "results": items}
    shown = items[:PREVIEW_LIMIT]
    return {
        "locked": len(items) > len(shown),
        "total": len(items),
        "shown": len(shown),
        "results": shown,
        "upgrade_message": "Sign in to see all matches, open the manuals, and view full part cross-references.",
    }


# ---------------------------------------------------------------------------
# Summary & navigation
# ---------------------------------------------------------------------------
@router.get("/stats")
def stats():
    _require_index()
    return _store.stats()


@router.get("/facets")
def facets():
    """Distinct categories/regions/doc-types/statuses for the elimination wizard."""
    _require_index()
    return _store.facets()


@router.get("/categories")
def categories():
    _require_index()
    return {"categories": _store.categories()}


@router.get("/brands")
def brands(
    category: Optional[str] = None,
    region: Optional[str] = None,
    status: Optional[str] = None,
):
    _require_index()
    return {"brands": _store.brands(category=category, region=region, status=status)}


# ---------------------------------------------------------------------------
# Browse documents
# ---------------------------------------------------------------------------
@router.get("/documents")
def list_documents(
    category: Optional[str] = None,
    region: Optional[str] = None,
    brand: Optional[str] = None,
    doc_type: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = Query(60, le=200),
    offset: int = 0,
):
    _require_index()
    return _store.list_documents(
        category=category, region=region, brand=brand, doc_type=doc_type,
        status=status, limit=limit, offset=offset,
    )


@router.get("/documents/{doc_id}")
def get_document(doc_id: str, request: Request):
    _require_index()
    level = access_level(request)
    doc = _store.get_document(doc_id, include_part_numbers=True)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    doc["can_download"] = level == "full"
    if level != "full":
        # Preview: tease the part numbers but withhold the full cross-ref.
        pns = doc.get("part_numbers", [])
        doc["part_numbers_total"] = len(pns)
        doc["part_numbers"] = pns[:PREVIEW_LIMIT]
        doc["locked"] = len(pns) > PREVIEW_LIMIT
    return doc


@router.get("/documents/{doc_id}/pages")
def document_pages(doc_id: str, include_text: bool = False):
    _require_index()
    pages = _store.document_pages(doc_id, include_text=include_text)
    if not pages:
        raise HTTPException(status_code=404, detail="Document not found or has no pages")
    return {"doc_id": doc_id, "pages": pages}


# ---------------------------------------------------------------------------
# Search & part-number lookup
# ---------------------------------------------------------------------------
@router.get("/search")
def search(
    request: Request,
    q: str = Query(..., min_length=2),
    category: Optional[str] = None,
    limit: int = Query(30, le=100),
):
    _require_index()
    level = access_level(request)
    results = _store.search(q, limit=limit, category=category)
    return {"query": q, **_gate_list(results, level)}


@router.get("/part-number/{token}")
def part_number(token: str, request: Request, limit: int = Query(40, le=100)):
    _require_index()
    level = access_level(request)
    results = _store.lookup_part_number(token, limit=limit)
    return {"token": token.upper(), **_gate_list(results, level)}


# ---------------------------------------------------------------------------
# Assets: cover thumbnails (public) and source PDFs (gated)
# ---------------------------------------------------------------------------
@router.get("/cover/{doc_id}")
def cover(doc_id: str):
    _require_index()
    doc = _store.get_document(doc_id, include_part_numbers=False)
    if not doc or not doc.get("cover_image"):
        raise HTTPException(status_code=404, detail="No cover image")
    path = _cfg.images_dir / doc["cover_image"]
    if not path.exists():
        # Fall back to the PNG variant if WebP wasn't produced.
        alt = path.with_suffix(".png")
        if alt.exists():
            path = alt
        else:
            raise HTTPException(status_code=404, detail="Cover file missing")
    media = "image/webp" if path.suffix == ".webp" else "image/png"
    return FileResponse(str(path), media_type=media)


@router.get("/pdf/{doc_id}")
def pdf(doc_id: str, request: Request):
    """Serve the source manual PDF — full-access (authenticated) only."""
    _require_index()
    if access_level(request) != "full":
        raise HTTPException(status_code=402, detail="Sign in to open the full manual.")
    doc = _store.get_document(doc_id, include_part_numbers=False)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    path = _cfg.library_root / Path(doc["rel_path"])
    if not path.exists():
        raise HTTPException(status_code=404, detail="Manual file not found on disk")
    return FileResponse(str(path), media_type="application/pdf", filename=doc["filename"])


# ---------------------------------------------------------------------------
# Visual identification (Claude Vision)
# ---------------------------------------------------------------------------
MAX_IMAGE_BYTES = 8 * 1024 * 1024  # 8 MB


@router.post("/identify")
async def identify(
    request: Request,
    image: UploadFile = File(...),
    category: Optional[str] = Form(None),
    note: Optional[str] = Form(None),
):
    """Identify a product from an uploaded photo. Anonymous users get the guess
    but the matched manuals are gated until sign-in."""
    _require_index()
    from app.services.part_finder.vision import identify_image

    data = await image.read()
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="Image too large (max 8 MB).")
    media_type = image.content_type or "image/jpeg"

    result = identify_image(
        image_bytes=data,
        media_type=media_type,
        store=_store,
        api_key=settings.ANTHROPIC_API_KEY,
        hint_category=category,
        note=note,
    )
    if "error" in result:
        # vision_unavailable / call_failed -> surface cleanly to the UI.
        status = 503 if result["error"] in ("vision_unavailable", "vision_call_failed") else 422
        raise HTTPException(status_code=status, detail=result)

    level = access_level(request)
    if level != "full":
        # Preview: keep the identification + first manual per candidate, lock the rest.
        for cand in result.get("candidates", []):
            matches = cand.get("catalog_matches", [])
            cand["catalog_matches_total"] = len(matches)
            cand["catalog_matches"] = matches[:1]
        result["locked"] = True
        result["upgrade_message"] = (
            "Sign in to see every matching manual and open the documents."
        )
    else:
        result["locked"] = False
    return result
