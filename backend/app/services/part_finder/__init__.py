"""Part Finder — visual product identification + manual lookup over a corpus of
manufacturer manuals (garage door panels, hardware, springs, dock equipment,
dock seals, operators).

  config.py       paths + thresholds (env-overridable)
  metadata.py     path -> category/region/brand; joins manifest + manufacturers CSV
  partnumbers.py  domain-tuned model/part-number extraction
  schema.sql      SQLite DDL (documents, pages + FTS5, part_numbers, quarantine)
  ingest.py       orchestrator: extract text, render covers, write index
  store.py        read-only query layer over index.db
  vision.py       Claude Vision identification
  api.py          FastAPI router (/api/part-finder)
"""

from .config import IngestConfig  # noqa: F401
