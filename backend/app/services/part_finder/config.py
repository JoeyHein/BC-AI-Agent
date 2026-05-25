"""Configuration for the Part Finder ingestion pipeline.

Paths default to the local OneDrive corpus and the in-repo output directory,
but every value is overridable via env var or CLI flag.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# Default location of the corpus. Override with PARTFINDER_LIBRARY_ROOT.
DEFAULT_LIBRARY_ROOT = Path(
    os.environ.get(
        "PARTFINDER_LIBRARY_ROOT",
        r"C:\Users\jhein\OneDrive\Open DC\DoorPart-Library",
    )
)

# Default output dir, resolved depth-independently so this file is identical
# whether the package sits at backend/part_finder (standalone) or
# backend/app/services/part_finder (portal): walk up to the nearest "backend"
# ancestor and use backend/data/partfinder; otherwise fall back beside the pkg.
def _default_output_dir() -> Path:
    here = Path(__file__).resolve()
    for ancestor in here.parents:
        if ancestor.name == "backend":
            return ancestor / "data" / "partfinder"
    return here.parent / "data" / "partfinder"


DEFAULT_OUTPUT_DIR = Path(
    os.environ.get("PARTFINDER_OUTPUT_DIR", str(_default_output_dir()))
)

CATEGORY_LABELS = {
    "01-Garage-Door-Panels": "Garage Door Panels",
    "02-Garage-Door-Hardware": "Garage Door Hardware",
    "03-Garage-Door-Springs": "Garage Door Springs",
    "04-Dock-Equipment": "Dock Equipment",
    "05-Dock-Seals-Shelters": "Dock Seals & Shelters",
    "06-Garage-Door-Operators": "Garage Door Operators",
}

META_FOLDERS = {"_INDEX", "_DOWNLOADS-LOG", "_PLAYBOOK"}

SCANNED_PAGE_CHAR_THRESHOLD = 20
SCANNED_DOC_CHAR_THRESHOLD = 60


@dataclass
class IngestConfig:
    library_root: Path = field(default_factory=lambda: DEFAULT_LIBRARY_ROOT)
    output_dir: Path = field(default_factory=lambda: DEFAULT_OUTPUT_DIR)

    render_covers: bool = True
    cover_long_edge_px: int = 1024
    cover_quality: int = 80
    render_pages: int = 0
    max_page_text_chars: int = 20000
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
