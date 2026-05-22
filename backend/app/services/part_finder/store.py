"""Read-only query layer over the Part Finder index (index.db).

The index is a standalone SQLite artifact produced by the ingestion pipeline,
not the main application database — so we access it with short-lived sqlite3
connections (SQLite opens are cheap and this keeps us thread-safe under
FastAPI's threadpool) rather than SQLAlchemy.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Optional

from .config import IngestConfig


def _fts_quote(query: str) -> str:
    """Make a user query safe for FTS5 MATCH: quote each term, drop FTS
    operators, AND the terms together. Keeps it forgiving for end users."""
    terms = [t for t in "".join(c if c.isalnum() else " " for c in query).split() if t]
    return " AND ".join(f'"{t}"' for t in terms)


class PartFinderStore:
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = Path(db_path or IngestConfig().db_path)

    @property
    def available(self) -> bool:
        return self.db_path.exists()

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        # Open read-only so the API can never mutate the index.
        uri = f"file:{self.db_path.as_posix()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    # ---- summary / facets ------------------------------------------------
    def stats(self) -> dict[str, Any]:
        with self._conn() as c:
            row = lambda q: c.execute(q).fetchone()[0]
            return {
                "documents": row("SELECT COUNT(*) FROM documents"),
                "pages": row("SELECT COUNT(*) FROM pages"),
                "brands": row("SELECT COUNT(DISTINCT brand) FROM documents WHERE brand IS NOT NULL"),
                "part_numbers": row("SELECT COUNT(DISTINCT token) FROM part_numbers"),
                "categories": row("SELECT COUNT(DISTINCT category) FROM documents"),
            }

    def facets(self) -> dict[str, Any]:
        """Distinct values for the process-of-elimination wizard."""
        with self._conn() as c:
            def col(q):
                return [r[0] for r in c.execute(q).fetchall() if r[0]]

            return {
                "categories": [
                    {"category": r["category"], "label": r["category_label"], "count": r["n"]}
                    for r in c.execute(
                        "SELECT category, category_label, COUNT(*) n FROM documents "
                        "GROUP BY category ORDER BY category"
                    )
                ],
                "regions": col("SELECT DISTINCT region FROM documents ORDER BY region"),
                "doc_types": col("SELECT DISTINCT doc_type FROM documents WHERE doc_type IS NOT NULL ORDER BY doc_type"),
                "brand_statuses": col("SELECT DISTINCT brand_status FROM documents WHERE brand_status IS NOT NULL ORDER BY brand_status"),
            }

    def categories(self) -> list[dict]:
        with self._conn() as c:
            return [
                dict(r)
                for r in c.execute(
                    "SELECT category, category_label, COUNT(*) doc_count, SUM(page_count) pages "
                    "FROM documents GROUP BY category ORDER BY category"
                )
            ]

    def brands(self, category: Optional[str] = None, region: Optional[str] = None,
               status: Optional[str] = None) -> list[dict]:
        clauses, params = ["brand IS NOT NULL"], []
        if category:
            clauses.append("category = ?"); params.append(category)
        if region:
            clauses.append("region = ?"); params.append(region)
        if status:
            clauses.append("brand_status = ?"); params.append(status)
        where = " AND ".join(clauses)
        with self._conn() as c:
            return [
                dict(r)
                for r in c.execute(
                    f"""SELECT brand,
                               MAX(manufacturer) manufacturer,
                               MAX(parent_company) parent_company,
                               MAX(brand_status) brand_status,
                               MAX(website) website,
                               MAX(product_lines) product_lines,
                               category, category_label,
                               COUNT(*) doc_count
                        FROM documents WHERE {where}
                        GROUP BY brand, category
                        ORDER BY brand""",
                    params,
                )
            ]

    # ---- documents -------------------------------------------------------
    _DOC_COLS = (
        "doc_id, rel_path, filename, category, category_label, region, brand, "
        "doc_type, title, page_count, size_bytes, source_url, manufacturer, "
        "parent_company, hq_country, hq_state, hq_city, brand_status, website, "
        "product_lines, sub_category, is_scanned, cover_image"
    )

    def list_documents(self, category=None, region=None, brand=None, doc_type=None,
                       status=None, limit=60, offset=0) -> dict:
        clauses, params = ["1=1"], []
        for col, val in (("category", category), ("region", region), ("brand", brand),
                         ("doc_type", doc_type), ("brand_status", status)):
            if val:
                clauses.append(f"{col} = ?"); params.append(val)
        where = " AND ".join(clauses)
        with self._conn() as c:
            total = c.execute(f"SELECT COUNT(*) FROM documents WHERE {where}", params).fetchone()[0]
            rows = c.execute(
                f"SELECT {self._DOC_COLS} FROM documents WHERE {where} "
                f"ORDER BY brand, title LIMIT ? OFFSET ?",
                params + [limit, offset],
            ).fetchall()
            return {"total": total, "limit": limit, "offset": offset,
                    "documents": [dict(r) for r in rows]}

    def get_document(self, doc_id: str, include_part_numbers=True) -> Optional[dict]:
        with self._conn() as c:
            row = c.execute(
                f"SELECT {self._DOC_COLS}, text_chars FROM documents WHERE doc_id = ?",
                (doc_id,),
            ).fetchone()
            if not row:
                return None
            doc = dict(row)
            if include_part_numbers:
                doc["part_numbers"] = [
                    dict(r)
                    for r in c.execute(
                        "SELECT token, raw, kind, page_no, freq FROM part_numbers "
                        "WHERE doc_id = ? ORDER BY freq DESC LIMIT 200",
                        (doc_id,),
                    )
                ]
            return doc

    def document_pages(self, doc_id: str, include_text=False) -> list[dict]:
        cols = "doc_id, page_no, char_count, needs_ocr" + (", text" if include_text else "")
        with self._conn() as c:
            return [
                dict(r)
                for r in c.execute(
                    f"SELECT {cols} FROM pages WHERE doc_id = ? ORDER BY page_no", (doc_id,)
                )
            ]

    # ---- search ----------------------------------------------------------
    def search(self, query: str, limit=30, category=None) -> list[dict]:
        """Full-text search over page text, grouped to best page per document."""
        match = _fts_quote(query)
        if not match:
            return []
        with self._conn() as c:
            rows = c.execute(
                """
                SELECT f.doc_id, f.page_no,
                       snippet(pages_fts, 0, '<b>', '</b>', ' … ', 12) AS snippet,
                       bm25(pages_fts) AS score
                FROM pages_fts f
                WHERE pages_fts MATCH ?
                ORDER BY score
                LIMIT 400
                """,
                (match,),
            ).fetchall()
            # Keep best (lowest bm25) page per doc.
            best: dict[str, sqlite3.Row] = {}
            for r in rows:
                if r["doc_id"] not in best:
                    best[r["doc_id"]] = r
            results = []
            for doc_id, r in best.items():
                d = c.execute(
                    f"SELECT {self._DOC_COLS} FROM documents WHERE doc_id = ?", (doc_id,)
                ).fetchone()
                if not d:
                    continue
                if category and d["category"] != category:
                    continue
                item = dict(d)
                item["match_page"] = r["page_no"]
                item["snippet"] = r["snippet"]
                item["score"] = r["score"]
                results.append(item)
            results.sort(key=lambda x: x["score"])
            return results[:limit]

    def lookup_part_number(self, token: str, limit=40) -> list[dict]:
        """Find documents that mention a model/part number. Prefix-tolerant."""
        norm = token.strip().upper()
        with self._conn() as c:
            rows = c.execute(
                """
                SELECT p.doc_id, p.token, p.raw, p.kind, p.page_no, p.freq
                FROM part_numbers p
                WHERE p.token = ? OR p.token LIKE ?
                ORDER BY (p.token = ?) DESC, p.freq DESC
                LIMIT ?
                """,
                (norm, norm + "%", norm, limit),
            ).fetchall()
            out = []
            seen = set()
            for r in rows:
                key = (r["doc_id"], r["token"])
                if key in seen:
                    continue
                seen.add(key)
                d = c.execute(
                    f"SELECT {self._DOC_COLS} FROM documents WHERE doc_id = ?", (r["doc_id"],)
                ).fetchone()
                if not d:
                    continue
                item = dict(d)
                item.update({"matched_token": r["token"], "matched_raw": r["raw"],
                             "kind": r["kind"], "page_no": r["page_no"], "freq": r["freq"]})
                out.append(item)
            return out

    # ---- vision support --------------------------------------------------
    def candidates_for_vision(self, category: Optional[str] = None,
                              brand: Optional[str] = None) -> list[dict]:
        """Documents with cover images, used to verify a Claude Vision guess."""
        clauses, params = ["cover_image IS NOT NULL"], []
        if category:
            clauses.append("category = ?"); params.append(category)
        if brand:
            clauses.append("brand = ?"); params.append(brand)
        where = " AND ".join(clauses)
        with self._conn() as c:
            return [
                dict(r)
                for r in c.execute(
                    f"SELECT doc_id, brand, manufacturer, category, category_label, "
                    f"doc_type, title, cover_image FROM documents WHERE {where} "
                    f"ORDER BY brand LIMIT 400",
                    params,
                )
            ]

    def brand_summaries(self) -> str:
        """Compact brand+category+product-lines text block for the vision prompt."""
        with self._conn() as c:
            rows = c.execute(
                "SELECT DISTINCT brand, category_label, MAX(product_lines) pl "
                "FROM documents WHERE brand IS NOT NULL GROUP BY brand, category_label "
                "ORDER BY category_label, brand"
            ).fetchall()
        lines = []
        for r in rows:
            pl = f" — lines: {r['pl']}" if r["pl"] else ""
            lines.append(f"- {r['brand']} ({r['category_label']}){pl}")
        return "\n".join(lines)
