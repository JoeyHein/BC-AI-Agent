"""Part Finder API — visual product identification + manual lookup.

Public-facing (gated) endpoints over the Part Finder index. Anonymous users get
a free *preview* (brand browse, limited search hits, an identification guess);
callers the host marks as "full" get complete results, full part-number
cross-references, and manual (PDF) downloads.

This module is HOST-AGNOSTIC: it exposes a `build_router(...)` factory that
takes its config, its Anthropic key, and — crucially — an `access_level`
callable injected by the host. That keeps this file byte-identical across the
standalone service and the embedded portal build; each host supplies its own
auth (shared token, JWT, session, …) without editing the core.

Routes are mounted under /api/part-finder.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable, Optional

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse

from .config import IngestConfig
from .store import PartFinderStore
from .vision import identify_image

logger = logging.getLogger(__name__)

MAX_IMAGE_BYTES = 8 * 1024 * 1024  # 8 MB

# Default access policy: everyone is in preview. Hosts inject their own.
def preview_only(_request: Request) -> str:
    return "preview"


def build_router(
    *,
    cfg: Optional[IngestConfig] = None,
    access_level: Callable[[Request], str] = preview_only,
    anthropic_api_key: Optional[str] = None,
    preview_limit: int = 3,
) -> APIRouter:
    """Construct the Part Finder router.

    Args:
        cfg: index/corpus locations (defaults to IngestConfig()).
        access_level: request -> "full" | "preview". Decides gating. Must not
            raise (the API is usable anonymously).
        anthropic_api_key: key for the Claude Vision /identify endpoint. If
            None, /identify returns 503 vision_unavailable.
        preview_limit: how many results a preview (anonymous) caller may see.
    """
    cfg = cfg or IngestConfig()
    store = PartFinderStore(cfg.db_path)
    router = APIRouter(prefix="/api/part-finder", tags=["part-finder"])

    def require_index():
        if not store.available:
            raise HTTPException(
                status_code=503,
                detail="Part Finder index not built yet. Run the ingest script.",
            )

    def gate_list(items: list, level: str) -> dict:
        if level == "full":
            return {"locked": False, "total": len(items), "shown": len(items), "results": items}
        shown = items[:preview_limit]
        return {
            "locked": len(items) > len(shown),
            "total": len(items),
            "shown": len(shown),
            "results": shown,
            "upgrade_message": "Sign in to see all matches, open the manuals, and view full part cross-references.",
        }

    # ---- summary & navigation -------------------------------------------
    @router.get("/stats")
    def stats():
        require_index()
        return store.stats()

    @router.get("/facets")
    def facets():
        """Distinct categories/regions/doc-types/statuses for the elimination wizard."""
        require_index()
        return store.facets()

    @router.get("/categories")
    def categories():
        require_index()
        return {"categories": store.categories()}

    @router.get("/brands")
    def brands(
        category: Optional[str] = None,
        region: Optional[str] = None,
        status: Optional[str] = None,
    ):
        require_index()
        return {"brands": store.brands(category=category, region=region, status=status)}

    # ---- browse documents -----------------------------------------------
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
        require_index()
        return store.list_documents(
            category=category, region=region, brand=brand, doc_type=doc_type,
            status=status, limit=limit, offset=offset,
        )

    @router.get("/documents/{doc_id}")
    def get_document(doc_id: str, request: Request):
        require_index()
        level = access_level(request)
        doc = store.get_document(doc_id, include_part_numbers=True)
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")
        doc["can_download"] = level == "full"
        if level != "full":
            pns = doc.get("part_numbers", [])
            doc["part_numbers_total"] = len(pns)
            doc["part_numbers"] = pns[:preview_limit]
            doc["locked"] = len(pns) > preview_limit
        return doc

    @router.get("/documents/{doc_id}/pages")
    def document_pages(doc_id: str, include_text: bool = False):
        require_index()
        pages = store.document_pages(doc_id, include_text=include_text)
        if not pages:
            raise HTTPException(status_code=404, detail="Document not found or has no pages")
        return {"doc_id": doc_id, "pages": pages}

    # ---- search & part-number lookup ------------------------------------
    @router.get("/search")
    def search(
        request: Request,
        q: str = Query(..., min_length=2),
        category: Optional[str] = None,
        limit: int = Query(30, le=100),
    ):
        require_index()
        results = store.search(q, limit=limit, category=category)
        return {"query": q, **gate_list(results, access_level(request))}

    @router.get("/part-number/{token}")
    def part_number(token: str, request: Request, limit: int = Query(40, le=100)):
        require_index()
        results = store.lookup_part_number(token, limit=limit)
        return {"token": token.upper(), **gate_list(results, access_level(request))}

    # ---- assets: covers (public) + source PDFs (gated) ------------------
    @router.get("/cover/{doc_id}")
    def cover(doc_id: str):
        require_index()
        doc = store.get_document(doc_id, include_part_numbers=False)
        if not doc or not doc.get("cover_image"):
            raise HTTPException(status_code=404, detail="No cover image")
        path = cfg.images_dir / doc["cover_image"]
        if not path.exists():
            alt = path.with_suffix(".png")
            if alt.exists():
                path = alt
            else:
                raise HTTPException(status_code=404, detail="Cover file missing")
        media = "image/webp" if path.suffix == ".webp" else "image/png"
        return FileResponse(str(path), media_type=media)

    @router.get("/pdf/{doc_id}")
    def pdf(doc_id: str, request: Request):
        """Serve the source manual PDF — full access only."""
        require_index()
        if access_level(request) != "full":
            raise HTTPException(status_code=402, detail="Sign in to open the full manual.")
        doc = store.get_document(doc_id, include_part_numbers=False)
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")
        path = cfg.library_root / Path(doc["rel_path"])
        if not path.exists():
            raise HTTPException(status_code=404, detail="Manual file not found on disk")
        return FileResponse(str(path), media_type="application/pdf", filename=doc["filename"])

    # ---- visual identification (Claude Vision) --------------------------
    @router.post("/identify")
    async def identify(
        request: Request,
        image: UploadFile = File(...),
        side_image: Optional[UploadFile] = File(None),
        category: Optional[str] = Form(None),
        note: Optional[str] = Form(None),
    ):
        """Identify a product from an uploaded photo. An optional second photo
        (`side_image`) is the edge-on side profile — for panels it shows the
        thickness + joint profile that best discriminates them. Preview callers
        get the guess but the matched manuals are gated."""
        require_index()
        data = await image.read()
        if len(data) > MAX_IMAGE_BYTES:
            raise HTTPException(status_code=413, detail="Image too large (max 8 MB).")
        media_type = image.content_type or "image/jpeg"

        side_data = side_media_type = None
        if side_image is not None:
            side_data = await side_image.read()
            if len(side_data) > MAX_IMAGE_BYTES:
                raise HTTPException(status_code=413, detail="Side image too large (max 8 MB).")
            side_media_type = side_image.content_type or "image/jpeg"

        result = identify_image(
            image_bytes=data,
            media_type=media_type,
            store=store,
            api_key=anthropic_api_key,
            hint_category=category,
            note=note,
            side_image_bytes=side_data,
            side_media_type=side_media_type,
        )
        if "error" in result:
            code = 503 if result["error"] in ("vision_unavailable", "vision_call_failed") else 422
            raise HTTPException(status_code=code, detail=result)

        if access_level(request) != "full":
            for cand in result.get("candidates", []):
                matches = cand.get("catalog_matches", [])
                cand["catalog_matches_total"] = len(matches)
                cand["catalog_matches"] = matches[:1]
            result["locked"] = True
            result["upgrade_message"] = "Sign in to see every matching manual and open the documents."
        else:
            result["locked"] = False
        return result

    return router
