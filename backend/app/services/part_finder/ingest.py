"""Ingestion orchestrator.

Walks the DoorPart-Library corpus and, for each PDF:
  * derives metadata (category/region/brand + manifest + manufacturer join)
  * extracts per-page text via PyMuPDF (born-digital text layer)
  * flags scanned/image-only pages and documents
  * extracts model/part numbers
  * renders a downscaled WebP cover thumbnail
  * writes documents/pages/part_numbers/quarantine into SQLite + JSONL exports

Broken/unreadable PDFs (0 pages, truncated, encrypted) are quarantined with a
reason and emitted to quarantine.csv for a later re-download pass — they never
abort the run.
"""

from __future__ import annotations

import hashlib
import io
import json
import sqlite3
import time
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional

import fitz  # PyMuPDF

from .config import (
    IngestConfig,
    SCANNED_DOC_CHAR_THRESHOLD,
    SCANNED_PAGE_CHAR_THRESHOLD,
    META_FOLDERS,
)
from .metadata import MetadataIndex, build_doc_meta, DocMeta
from .partnumbers import extract_part_numbers

warnings.filterwarnings("ignore")
fitz.TOOLS.mupdf_display_errors(False)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _doc_id(sha256: Optional[str], rel_path: str) -> str:
    """Stable id: first 16 hex of sha256 when known, else hash of rel_path."""
    if sha256 and len(sha256) >= 16:
        return sha256[:16]
    return hashlib.sha256(rel_path.encode("utf-8")).hexdigest()[:16]


def iter_pdfs(library_root: Path, limit: int = 0) -> Iterator[Path]:
    count = 0
    for p in sorted(library_root.rglob("*.pdf")):
        # Skip anything under a meta folder (_INDEX, _DOWNLOADS-LOG, _PLAYBOOK).
        if any(part in META_FOLDERS for part in p.relative_to(library_root).parts):
            continue
        yield p
        count += 1
        if limit and count >= limit:
            return


def _classify_broken(path: Path) -> str:
    """Best-effort human-readable reason for a PDF PyMuPDF could not read.

    Used only to label quarantine rows — never as a gate (PyMuPDF tolerates
    leading junk bytes and missing %%EOF, so byte checks alone over-reject)."""
    try:
        size = path.stat().st_size
    except OSError as e:
        return f"stat-failed:{e}"
    if size < 1024:
        return "too-small"
    try:
        with open(path, "rb") as fh:
            head = fh.read(1024)
            fh.seek(max(0, size - 2048))
            tail = fh.read(2048)
    except OSError as e:
        return f"read-failed:{e}"
    if b"%PDF" not in head:
        return "not-pdf-header"
    if b"%%EOF" not in tail:
        return "truncated-no-eof"
    return "unreadable"


def _render_cover(doc: "fitz.Document", out_path: Path, long_edge: int, quality: int) -> bool:
    """Render page 1 to a downscaled WebP. Returns True on success."""
    try:
        page = doc[0]
        rect = page.rect
        longest = max(rect.width, rect.height) or 1
        zoom = min(long_edge / longest, 2.0)
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        # PyMuPDF can write webp via Pillow if available; fall back to PNG.
        try:
            from PIL import Image

            img = Image.open(io.BytesIO(pix.tobytes("png")))
            img.save(out_path, "WEBP", quality=quality, method=4)
            return True
        except Exception:
            png_path = out_path.with_suffix(".png")
            pix.save(png_path)
            return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def _connect_and_init(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    schema = (Path(__file__).parent / "schema.sql").read_text(encoding="utf-8")
    conn.executescript(schema)
    _migrate_schema(conn)
    conn.commit()
    return conn


def _migrate_schema(conn: sqlite3.Connection) -> None:
    """Add columns introduced after the initial schema without requiring re-ingest."""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(documents)")}
    if "host_rights" not in existing:
        conn.execute("ALTER TABLE documents ADD COLUMN host_rights TEXT DEFAULT NULL")


def _reset_tables(conn: sqlite3.Connection) -> None:
    for tbl in ("part_numbers", "pages", "pages_fts", "documents", "quarantine"):
        conn.execute(f"DELETE FROM {tbl}")
    conn.commit()


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_ingest(cfg: IngestConfig, fresh: bool = True, verbose: bool = True) -> dict:
    started = _now_iso()
    t0 = time.time()
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    cfg.output_dir.mkdir(parents=True, exist_ok=True)
    meta_idx = MetadataIndex(cfg.manifest_csv, cfg.manufacturers_csv)
    conn = _connect_and_init(cfg.db_path)
    if fresh:
        _reset_tables(conn)

    docs_ok = docs_broken = docs_scanned = pages_total = pn_total = 0

    # JSONL writers (portable export alongside the DB).
    docs_fp = open(cfg.documents_jsonl, "w", encoding="utf-8")
    pages_fp = open(cfg.pages_jsonl, "w", encoding="utf-8")
    quarantine_rows: list[dict] = []
    needs_ocr_rows: list[dict] = []

    try:
        for pdf_path in iter_pdfs(cfg.library_root, cfg.limit):
            meta = build_doc_meta(pdf_path, cfg.library_root, meta_idx)

            # PyMuPDF is the arbiter: try to open everything. Only quarantine
            # when it cannot yield readable pages.
            ok, reason = True, ""
            doc = None
            try:
                doc = fitz.open(str(pdf_path))
                if doc.needs_pass:
                    ok, reason = False, "encrypted"
                elif doc.page_count == 0:
                    ok, reason = False, _classify_broken(pdf_path)
            except Exception:
                ok, reason = False, _classify_broken(pdf_path)

            if not ok:
                docs_broken += 1
                q = {
                    "rel_path": meta.rel_path,
                    "filename": meta.filename,
                    "brand": meta.brand,
                    "category": meta.category,
                    "reason": reason,
                    "size_bytes": meta.size_bytes,
                    "source_url": meta.source_url,
                }
                quarantine_rows.append(q)
                conn.execute(
                    "INSERT OR REPLACE INTO quarantine "
                    "(rel_path, filename, brand, category, reason, size_bytes, source_url) "
                    "VALUES (:rel_path,:filename,:brand,:category,:reason,:size_bytes,:source_url)",
                    q,
                )
                if doc:
                    doc.close()
                if verbose:
                    print(f"  [BROKEN:{reason}] {meta.rel_path}")
                continue

            # --- good document: extract ---
            doc_id = _doc_id(meta.sha256, meta.rel_path)
            page_count = doc.page_count
            title = (doc.metadata or {}).get("title") or ""
            title = title.strip() or meta.filename.rsplit(".", 1)[0].replace("-", " ")

            total_chars = 0
            doc_part_numbers: dict[str, dict] = {}
            page_records = []

            bad_pages = 0
            for i in range(page_count):
                try:
                    text = doc[i].get_text("text")
                except Exception:
                    # Partially broken page tree: skip this page, keep the doc.
                    bad_pages += 1
                    text = ""
                text = text[: cfg.max_page_text_chars]
                cc = len(text.strip())
                total_chars += cc
                needs_ocr = 1 if cc < SCANNED_PAGE_CHAR_THRESHOLD else 0
                page_no = i + 1
                page_records.append((doc_id, page_no, cc, needs_ocr, text))

                if needs_ocr:
                    needs_ocr_rows.append(
                        {"rel_path": meta.rel_path, "page_no": page_no, "char_count": cc}
                    )

                for token, info in extract_part_numbers(text).items():
                    agg = doc_part_numbers.setdefault(
                        token, {"raw": info["raw"], "kind": info["kind"], "freq": 0,
                                "page_no": page_no}
                    )
                    agg["freq"] += info["freq"]

            mean_chars = total_chars / page_count if page_count else 0
            is_scanned = 1 if mean_chars < SCANNED_DOC_CHAR_THRESHOLD else 0
            if is_scanned:
                docs_scanned += 1

            # Cover thumbnail.
            cover_rel = None
            if cfg.render_covers:
                cover_rel = f"{doc_id}/cover.webp"
                cover_abs = cfg.images_dir / cover_rel
                if not _render_cover(doc, cover_abs, cfg.cover_long_edge_px, cfg.cover_quality):
                    cover_rel = None

            doc.close()

            # --- persist document ---
            doc_row = {
                "doc_id": doc_id,
                "rel_path": meta.rel_path,
                "filename": meta.filename,
                "category": meta.category,
                "category_label": meta.category_label,
                "region": meta.region,
                "brand": meta.brand,
                "doc_type": meta.doc_type,
                "title": title,
                "page_count": page_count,
                "size_bytes": meta.size_bytes or pdf_path.stat().st_size,
                "sha256": meta.sha256,
                "source_url": meta.source_url,
                "manufacturer": meta.manufacturer,
                "parent_company": meta.parent_company,
                "hq_country": meta.hq_country,
                "hq_state": meta.hq_state,
                "hq_city": meta.hq_city,
                "brand_status": meta.brand_status,
                "website": meta.website,
                "product_lines": meta.product_lines,
                "sub_category": meta.sub_category,
                "text_chars": total_chars,
                "is_scanned": is_scanned,
                "cover_image": cover_rel,
                "ingested_at": _now_iso(),
                "host_rights": meta.host_rights,
            }
            conn.execute(
                """INSERT OR REPLACE INTO documents (
                    doc_id, rel_path, filename, category, category_label, region,
                    brand, doc_type, title, page_count, size_bytes, sha256, source_url,
                    manufacturer, parent_company, hq_country, hq_state, hq_city,
                    brand_status, website, product_lines, sub_category,
                    text_chars, is_scanned, cover_image, ingested_at, host_rights
                ) VALUES (
                    :doc_id,:rel_path,:filename,:category,:category_label,:region,
                    :brand,:doc_type,:title,:page_count,:size_bytes,:sha256,:source_url,
                    :manufacturer,:parent_company,:hq_country,:hq_state,:hq_city,
                    :brand_status,:website,:product_lines,:sub_category,
                    :text_chars,:is_scanned,:cover_image,:ingested_at,:host_rights
                )""",
                doc_row,
            )

            # pages + FTS
            conn.executemany(
                "INSERT OR REPLACE INTO pages (doc_id, page_no, char_count, needs_ocr, text) "
                "VALUES (?,?,?,?,?)",
                page_records,
            )
            conn.executemany(
                "INSERT INTO pages_fts (text, doc_id, page_no, brand) VALUES (?,?,?,?)",
                [(r[4], r[0], r[1], meta.brand or "") for r in page_records],
            )

            # part numbers
            if doc_part_numbers:
                conn.executemany(
                    "INSERT INTO part_numbers (doc_id, page_no, token, raw, kind, freq) "
                    "VALUES (?,?,?,?,?,?)",
                    [
                        (doc_id, info["page_no"], token, info["raw"], info["kind"], info["freq"])
                        for token, info in doc_part_numbers.items()
                    ],
                )
                pn_total += len(doc_part_numbers)

            # JSONL exports
            docs_fp.write(json.dumps(doc_row, ensure_ascii=False) + "\n")
            for r in page_records:
                pages_fp.write(
                    json.dumps(
                        {"doc_id": r[0], "page_no": r[1], "char_count": r[2],
                         "needs_ocr": r[3], "text": r[4]},
                        ensure_ascii=False,
                    )
                    + "\n"
                )

            docs_ok += 1
            pages_total += page_count
            conn.commit()
            if verbose and docs_ok % 25 == 0:
                print(f"  ...{docs_ok} docs ok, {pages_total} pages, {docs_broken} broken")

    finally:
        docs_fp.close()
        pages_fp.close()

    # Write CSV side-outputs.
    _write_csv(cfg.quarantine_csv,
               ["rel_path", "filename", "brand", "category", "reason", "size_bytes", "source_url"],
               quarantine_rows)
    _write_csv(cfg.needs_ocr_csv, ["rel_path", "page_no", "char_count"], needs_ocr_rows)

    finished = _now_iso()
    conn.execute(
        """INSERT OR REPLACE INTO ingest_runs
           (run_id, started_at, finished_at, library_root, docs_ok, docs_broken,
            docs_scanned, pages, part_numbers, notes)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (run_id, started, finished, str(cfg.library_root), docs_ok, docs_broken,
         docs_scanned, pages_total, pn_total, ""),
    )
    conn.commit()
    conn.close()

    stats = {
        "run_id": run_id,
        "started_at": started,
        "finished_at": finished,
        "elapsed_sec": round(time.time() - t0, 1),
        "library_root": str(cfg.library_root),
        "output_dir": str(cfg.output_dir),
        "docs_ok": docs_ok,
        "docs_broken": docs_broken,
        "docs_scanned": docs_scanned,
        "pages": pages_total,
        "part_numbers_unique_doc_tokens": pn_total,
        "quarantine_csv": str(cfg.quarantine_csv),
        "needs_ocr_pages": len(needs_ocr_rows),
    }
    cfg.stats_json.write_text(json.dumps(stats, indent=2), encoding="utf-8")
    return stats


def _write_csv(path: Path, header: list[str], rows: list[dict]) -> None:
    import csv

    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=header)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in header})
