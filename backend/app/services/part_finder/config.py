"""Configuration for the Part Finder ingestion pipeline.

Paths default to the user's local OneDrive library and the in-repo output
directory, but every value is overridable via env var or CLI flag so the
same code runs unchanged on the DigitalOcean droplet (where the library and
output live on disk / object storage).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# Default location of the corpus on the dev machine. Override with
# PARTFINDER_LIBRARY_ROOT in production / CI.
DEFAULT_LIBRARY_ROOT = Path(
    os.environ.get(
        "PARTFINDER_LIBRARY_ROOT",
        r"C:\Users\jhein\OneDrive\Open DC\DoorPart-Library",
    )
)

# Default output location: in-repo so the backend can find it, but the heavy
# generated artifacts (images, .db, .jsonl) are gitignored.
DEFAULT_OUTPUT_DIR = Path(
    os.environ.get(
        "PARTFINDER_OUTPUT_DIR",
        str(Path(__file__).resolve().parents[3] / "data" / "partfinder"),
    )
)

# Human-readable labels for the numbered top-level category folders.
CATEGORY_LABELS = {
    "01-Garage-Door-Panels": "Garage Door Panels",
    "02-Garage-Door-Hardware": "Garage Door Hardware",
    "03-Garage-Door-Springs": "Garage Door Springs",
    "04-Dock-Equipment": "Dock Equipment",
    "05-Dock-Seals-Shelters": "Dock Seals & Shelters",
    "06-Garage-Door-Operators": "Garage Door Operators",
}

# Folders that are metadata, not product content.
META_FOLDERS = {"_INDEX", "_DOWNLOADS-LOG", "_PLAYBOOK"}

# A page with fewer than this many extractable characters is treated as
# scanned / image-only and flagged for OCR or vision-read at query time.
SCANNED_PAGE_CHAR_THRESHOLD = 20

# A document whose mean chars/page over its first few pages is below this is
# flagged is_scanned at the document level.
SCANNED_DOC_CHAR_THRESHOLD = 60


@dataclass
class IngestConfig:
    library_root: Path = field(default_factory=lambda: DEFAULT_LIBRARY_ROOT)
    output_dir: Path = field(default_factory=lambda: DEFAULT_OUTPUT_DIR)

    # Cover-thumbnail rendering
    render_covers: bool = True
    cover_long_edge_px: int = 1024  # downscale longest edge to this
    cover_quality: int = 80  # WebP quality

    # Limit pages of full-page rendering (0 = covers only). Reserved for a
    # later "render hero pages" phase; default keeps disk usage small.
    render_pages: int = 0

    # Cap stored page text to avoid pathological pages bloating the DB.
    max_page_text_chars: int = 20000

    # Process only this many PDFs (for smoke tests); 0 = all.
    limit: int = 0

    @property
    def manifest_csv(self) -> Path:
        return self.library_root / "_DOWNLOADS-LOG" / "manifest.csv"

    @property
    def manufacturers_csv(self) -> Path:
        return self.library_root / "_INDEX" / "manufacturers-master.csv"

    @property
    def db_path(self) -> Path:
        return self.output_dir / "index.db"

    @property
    def images_dir(self) -> Path:
        return self.output_dir / "images"

    @property
    def documents_jsonl(self) -> Path:
        return self.output_dir / "documents.jsonl"

    @property
    def pages_jsonl(self) -> Path:
        return self.output_dir / "pages.jsonl"

    @property
    def quarantine_csv(self) -> Path:
        return self.output_dir / "quarantine.csv"

    @property
    def needs_ocr_csv(self) -> Path:
        return self.output_dir / "needs_ocr.csv"

    @property
    def stats_json(self) -> Path:
        return self.output_dir / "stats.json"
