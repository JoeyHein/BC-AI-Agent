# Part Finder index output

This directory holds the generated Part Finder index. **The artifacts are not
committed** (see `.gitignore`) — they are regenerated from the DoorPart-Library
corpus by the ingestion pipeline.

## Regenerate

```bash
cd backend
python scripts/partfinder_ingest.py            # builds index.db + covers + JSONL
```

Outputs (all gitignored):

| File | Description |
|---|---|
| `index.db` | SQLite index (documents, pages + FTS5, part_numbers, quarantine) |
| `documents.jsonl` / `pages.jsonl` | portable exports |
| `images/<doc_id>/cover.webp` | page-1 cover thumbnails |
| `quarantine.csv` | broken PDFs + reason |
| `needs_ocr.csv` | image-only pages |
| `stats.json` | last run summary |
| `recover/` | re-download URL discovery working files |
| `redownload_report.csv` | last re-download tool run |

The API reads `index.db` read-only via `app.services.part_finder.store`.
Override locations with `PARTFINDER_LIBRARY_ROOT` / `PARTFINDER_OUTPUT_DIR`.

> Production note: `index.db` and `images/` are local-only. For deploy, either
> build the index on the server (the source PDFs must be present) or ship the
> index + covers to object storage.
