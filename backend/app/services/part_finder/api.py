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

import hashlib
import json
import logging
import threading
import time
import urllib.parse
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel

from .config import IngestConfig
from .store import PartFinderStore
from .vision import identify_image
from . import telemetry


class _CandidateSummary(BaseModel):
    brand: str
    family_or_model: Optional[str] = None
    confidence: Optional[float] = None


class _FeedbackBody(BaseModel):
    photo_hash: str
    candidates_shown: list[_CandidateSummary] = []
    was_correct: bool
    correct_brand: Optional[str] = None


class _PilotRequestBody(BaseModel):
    name: str
    email: str
    company: str

logger = logging.getLogger(__name__)

MAX_IMAGE_BYTES = 8 * 1024 * 1024  # 8 MB

# Distributor search-URL templates for the buy-links endpoint (S3-02).
# {token} is replaced at request time with the URL-encoded part-number token.
_DISTRIBUTOR_TEMPLATES = [
    {"name": "Grainger",         "logo_key": "grainger",    "url_tmpl": "https://www.grainger.com/search?searchQuery={token}"},
    {"name": "Johnstone Supply", "logo_key": "johnstone",   "url_tmpl": "https://www.johnstonesupply.com/catalog/productList.ep?keyword={token}"},
    {"name": "SupplyHouse",      "logo_key": "supplyhouse", "url_tmpl": "https://www.supplyhouse.com/SearchResult?keywords={token}"},
    {"name": "Parts Town",       "logo_key": "partstown",   "url_tmpl": "https://www.partstown.com/search?q={token}"},
    {"name": "Amazon Business",  "logo_key": "amazon",      "url_tmpl": "https://www.amazon.com/s?k={token}&i=industrial"},
]

# Maps content-type → file extension for uploaded image persistence.
_MEDIA_TO_EXT: dict[str, str] = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}

# Default access policy: everyone is in preview. Hosts inject their own.
def preview_only(_request: Request) -> str:
    return "preview"


def build_router(
    *,
    cfg: Optional[IngestConfig] = None,
    access_level: Callable[[Request], str] = preview_only,
    user_id_fn: Callable[[Request], Optional[str]] = lambda r: None,
    anthropic_api_key: Optional[str] = None,
    preview_limit: int = 3,
    cdn_base_url: Optional[str] = None,
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
    _feedback_lock = threading.Lock()
    _history_lock = threading.Lock()

    def _write_history(uid: str, record: dict) -> None:
        uid_hash = hashlib.sha256(uid.encode()).hexdigest()[:16]
        history_dir = cfg.output_dir / "history"
        try:
            history_dir.mkdir(parents=True, exist_ok=True)
            with _history_lock:
                with open(history_dir / f"{uid_hash}.jsonl", "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(record) + "\n")
        except Exception:
            logger.exception("failed to write history record")

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
        response = {"query": q, **gate_list(results, access_level(request))}
        telemetry.search(
            session_id=telemetry.session_id_from_request(request),
            query_len=len(q),
            category=category,
            result_count=response.get("total", 0),
        )
        return response

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
        if cdn_base_url:
            cdn_url = f"{cdn_base_url.rstrip('/')}/images/{doc['cover_image']}"
            return RedirectResponse(url=cdn_url, status_code=302)
        path = cfg.images_dir / doc["cover_image"]
        if not path.exists():
            alt = path.with_suffix(".png")
            if alt.exists():
                path = alt
            else:
                raise HTTPException(status_code=404, detail="Cover file missing")
        media = "image/webp" if path.suffix == ".webp" else "image/png"
        return FileResponse(str(path), media_type=media)

    @router.get("/open/{doc_id}")
    def open_manual(doc_id: str, request: Request):
        """Return the URL to open this manual — link-out or serve, per host_rights."""
        require_index()
        if access_level(request) != "full":
            raise HTTPException(status_code=402, detail="Sign in to open the full manual.")
        doc = store.get_document(doc_id, include_part_numbers=False)
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")
        telemetry.manual_opened(
            session_id=telemetry.session_id_from_request(request),
            doc_id=doc_id,
            filename=doc["filename"],
        )
        host_rights = doc.get("host_rights")
        if host_rights == "allowed":
            if cdn_base_url:
                return {"url": f"{cdn_base_url.rstrip('/')}/pdfs/{doc['filename']}", "mode": "serve"}
            return {"url": None, "mode": "serve"}
        # Default: link-out to original source URL.
        source_url = doc.get("source_url")
        if not source_url:
            raise HTTPException(status_code=404, detail="No source URL available for this manual.")
        return {"url": source_url, "mode": "link-out"}

    @router.get("/pdf/{doc_id}")
    def pdf(doc_id: str, request: Request):
        """Serve the source manual PDF from disk — full access only, host_rights='allowed' docs."""
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

        session_id = telemetry.session_id_from_request(request)
        ph = telemetry.photo_hash(data)
        telemetry.id_started(session_id=session_id, photo_hash_hex=ph, category_hint=category)

        # Persist uploaded image so the feedback→eval-manifest converter can
        # match feedback records to their photos without a second upload. The
        # side profile is saved next to it as "{hash}-side{ext}" — it is the
        # stronger cue for panels, so the labeled field set needs both angles.
        _ext = _MEDIA_TO_EXT.get(media_type, ".jpg")
        try:
            _uploads_dir = cfg.output_dir / "uploads"
            _uploads_dir.mkdir(parents=True, exist_ok=True)
            _upload_path = _uploads_dir / f"{ph}{_ext}"
            if not _upload_path.exists():
                _upload_path.write_bytes(data)
            if side_data is not None:
                _side_ext = _MEDIA_TO_EXT.get(side_media_type, ".jpg")
                _side_path = _uploads_dir / f"{ph}-side{_side_ext}"
                if not _side_path.exists():
                    _side_path.write_bytes(side_data)
        except Exception:
            logger.exception("failed to save uploaded image for eval pipeline")

        t0 = time.monotonic()
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
        latency_ms = (time.monotonic() - t0) * 1000

        if "error" in result:
            telemetry.id_result(
                session_id=session_id,
                photo_hash_hex=ph,
                success=False,
                top_brand=None,
                top_confidence=None,
                candidate_count=0,
                latency_ms=latency_ms,
                cache_read_tokens=0,
            )
            code = 503 if result["error"] in ("vision_unavailable", "vision_call_failed") else 422
            raise HTTPException(status_code=code, detail=result)

        candidates = result.get("candidates", [])
        top = candidates[0] if candidates else {}
        telemetry.id_result(
            session_id=session_id,
            photo_hash_hex=ph,
            success=True,
            top_brand=top.get("brand"),
            top_confidence=top.get("confidence"),
            candidate_count=len(candidates),
            latency_ms=latency_ms,
            cache_read_tokens=result.get("usage", {}).get("cache_read_input_tokens", 0),
        )

        result["photo_hash"] = ph

        if access_level(request) != "full":
            for cand in candidates:
                matches = cand.get("catalog_matches", [])
                cand["catalog_matches_total"] = len(matches)
                cand["catalog_matches"] = matches[:1]
            result["locked"] = True
            result["upgrade_message"] = "Sign in to see every matching manual and open the documents."
        else:
            result["locked"] = False
            uid = user_id_fn(request)
            if uid:
                _write_history(uid, {
                    "ts_utc": datetime.now(timezone.utc).isoformat(),
                    "photo_hash": ph,
                    "category_hint": category,
                    "top_brand": top.get("brand"),
                    "top_confidence": top.get("confidence"),
                    "candidate_count": len(candidates),
                })
        return result

    # ---- feedback (anonymous) -------------------------------------------
    @router.post("/feedback")
    def submit_feedback(body: _FeedbackBody, request: Request):
        """Record user feedback on an identification result. No auth required."""
        feedback_id = str(uuid.uuid4())
        session_id = telemetry.session_id_from_request(request)
        record = {
            "feedback_id": feedback_id,
            "photo_hash": body.photo_hash,
            "candidates_shown": [c.model_dump() for c in body.candidates_shown],
            "was_correct": body.was_correct,
            "correct_brand": body.correct_brand,
            "session_id": session_id,
            "ts_utc": datetime.now(timezone.utc).isoformat(),
        }
        feedback_path = cfg.output_dir / "feedback.jsonl"
        try:
            feedback_path.parent.mkdir(parents=True, exist_ok=True)
            with _feedback_lock:
                with open(feedback_path, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(record) + "\n")
        except Exception:
            logger.exception("failed to write feedback record")
        telemetry.feedback(
            session_id=session_id,
            photo_hash_hex=body.photo_hash,
            was_correct=body.was_correct,
            corrected_brand=body.correct_brand if not body.was_correct else None,
        )
        return {"recorded": True, "feedback_id": feedback_id}

    # ---- part buy-links (S3-02, no auth required) -----------------------
    @router.get("/parts/{token}/buy-links")
    def buy_links(token: str):
        """Return distributor search URLs for a part-number token. No auth required."""
        t = token.strip()
        if not t:
            raise HTTPException(status_code=400, detail="Token must not be blank.")
        encoded = urllib.parse.quote_plus(t)
        links = [
            {"name": d["name"], "logo_key": d["logo_key"], "url": d["url_tmpl"].replace("{token}", encoded)}
            for d in _DISTRIBUTOR_TEMPLATES
        ]
        return {"token": t.upper(), "links": links}

    # ---- lookup history (authenticated users only) -----------------------
    @router.get("/history")
    def lookup_history(request: Request, limit: int = Query(20, ge=1, le=50)):
        """Return the authenticated user's N most-recent identification lookups.

        Returns 401 when the request carries no valid user identity (no JWT
        auth configured, no token, or token lacks a `sub` claim). Returns an
        empty list when the user has history yet — never 404.
        """
        uid = user_id_fn(request)
        if not uid:
            raise HTTPException(
                status_code=401,
                detail="Authentication required to view lookup history.",
            )
        uid_hash = hashlib.sha256(uid.encode()).hexdigest()[:16]
        history_path = cfg.output_dir / "history" / f"{uid_hash}.jsonl"
        items: list[dict] = []
        if history_path.exists():
            with open(history_path, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        try:
                            items.append(json.loads(line))
                        except json.JSONDecodeError:
                            pass
        # Reverse-chronological: take the last `limit` entries and flip.
        items = items[-limit:][::-1]
        return {"items": items, "count": len(items)}

    # ---- pilot request (S3-05, no auth required) ------------------------
    _pilot_lock = threading.Lock()

    @router.post("/pilot-request")
    def pilot_request(body: _PilotRequestBody):
        """Record a pilot-access request. No auth required.

        Appends one JSON line to {output_dir}/pilot_requests.jsonl.
        Returns {"recorded": true} on success.
        """
        if "@" not in body.email:
            raise HTTPException(status_code=400, detail="Invalid email address.")
        record = {
            "ts_utc": datetime.now(timezone.utc).isoformat(),
            "name": body.name.strip(),
            "email": body.email.strip(),
            "company": body.company.strip(),
        }
        pilot_path = cfg.output_dir / "pilot_requests.jsonl"
        try:
            cfg.output_dir.mkdir(parents=True, exist_ok=True)
            with _pilot_lock:
                with open(pilot_path, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(record) + "\n")
        except Exception:
            logger.exception("failed to write pilot request")
            raise HTTPException(status_code=500, detail="Failed to record request.")
        return {"recorded": True}

    return router
