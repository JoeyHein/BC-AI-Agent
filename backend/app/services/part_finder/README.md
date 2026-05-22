# Part Finder — ingestion pipeline

Turns the offline **DoorPart-Library** corpus (manufacturer manuals, install
guides, brochures, spec sheets for panels, hardware, springs, dock equipment,
dock seals, operators) into a structured, searchable index that powers:

- **Visual product ID** — user uploads a photo; Claude Vision identifies
  brand/family and matches against the indexed catalog.
- **Process-of-elimination ID** — guided Q&A narrows brand → family → model.
- **Manual lookup** — by brand, by part/model number, or by free-text search.

This package is **stage 1: ingestion**. The search API and vision layer build
on the index it produces.

## Layout

```
part_finder/
  config.py        IngestConfig — paths, thresholds, render options (env-overridable)
  metadata.py      path -> category/region/brand; joins manifest.csv + manufacturers-master.csv
  partnumbers.py   domain-tuned model/part-number extraction with noise filtering
  schema.sql       SQLite DDL (documents, pages, pages_fts, part_numbers, quarantine, ingest_runs)
  ingest.py        orchestrator: extract text, render covers, write SQLite + JSONL, quarantine broken PDFs
```

CLI: `backend/scripts/partfinder_ingest.py`

## Run

```bash
# Full ingest (defaults read from config / env vars):
python backend/scripts/partfinder_ingest.py

# Smoke test:
python backend/scripts/partfinder_ingest.py --limit 15

# Text-only, fastest (skip cover rendering):
python backend/scripts/partfinder_ingest.py --no-covers
```

Env overrides: `PARTFINDER_LIBRARY_ROOT`, `PARTFINDER_OUTPUT_DIR`.

## Output (`backend/data/partfinder/`, gitignored)

| File | What |
|---|---|
| `index.db` | SQLite index (documents, pages + FTS5, part_numbers, quarantine, ingest_runs) |
| `documents.jsonl` / `pages.jsonl` | portable exports of the same data |
| `images/<doc_id>/cover.webp` | downscaled page-1 cover thumbnails |
| `quarantine.csv` | broken PDFs + reason, for a re-download pass |
| `needs_ocr.csv` | image-only pages to OCR / vision-read later |
| `stats.json` | last run summary |

## Design notes

- **PyMuPDF is the arbiter of readability.** Byte-level checks only *label* a
  failure reason; they never gate, because PyMuPDF tolerates leading junk bytes
  and missing `%%EOF` that naive checks would over-reject.
- **Per-page resilience.** A partially broken page tree skips the bad page and
  keeps the rest of the document rather than discarding it.
- **Born-digital first.** ~90% of the corpus has a rich text layer; OCR is an
  optional plug-in for the ~6% scanned pages (flagged in `needs_ocr.csv`).
- **Portable schema.** Column set maps cleanly onto Postgres for the portal.

## Last verified run (Session 1)

303 documents OK · 6,718 pages · 6,717 distinct part-number tokens ·
brand→manufacturer join 277/277 · 54 quarantined (45 truncated, 9 too-small) ·
18 scanned. ~80s.

## Next stages (not in this package yet)

1. **Search API** — FastAPI router (`app/api/part_finder.py`) over `index.db`:
   brand browse, part-number lookup, full-text search, facet filters.
2. **Claude Vision ID** — photo → candidate brands/families via multimodal
   model, verified against indexed covers + page text.
3. **Re-download pass** — refetch the 54 quarantined files from `source_url`
   (manifest) / web search; many are high-value (Hörmann, Wayne Dalton, CHI).
4. **React UI** — gated public Part Finder (free preview, paid full results).
