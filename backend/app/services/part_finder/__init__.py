"""Part Finder — visual product identification + manual lookup over the DoorPart-Library corpus.

This package owns the ingestion pipeline that turns the offline library of
manufacturer PDFs (panels, hardware, springs, dock equipment, dock seals,
operators) into a structured, searchable index that the API and the
Claude-Vision identification layer consume.

Pipeline stages (this module set):
  metadata.py     -> parse category/region/brand from paths; join manifest + manufacturers CSV
  partnumbers.py  -> domain-tuned model/part-number extraction from page text
  ingest.py       -> orchestrate: extract text, render covers, write SQLite + JSONL, quarantine broken files

The CLI entry point lives at backend/scripts/partfinder_ingest.py.
"""

from .config import IngestConfig  # noqa: F401
