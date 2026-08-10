"""Metadata layer: derive document facts from the corpus layout and join the
two source-of-truth CSVs (download manifest + manufacturers master).

The folder layout is authoritative for category/region/brand:
    {category}/{region}/{brand}/{file}.pdf
The manifest supplies sha256/source_url/size where present (it covers most
but not all files). The manufacturers master enriches each brand with parent
company, HQ, status, website, and product lines.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .config import CATEGORY_LABELS, META_FOLDERS

# Region folder names (also used to detect files dropped directly under a
# region with no brand subfolder).
REGIONS = {
    "North-America",
    "Europe",
    "Asia-Pacific",
    "Latin-America",
    "Other",
}

# Tokens stripped when normalizing a company/brand name for matching.
_BRAND_NOISE = {
    "the", "garage", "door", "doors", "manufacturing", "mfg", "industries",
    "industrial", "corporation", "corp", "company", "co", "inc", "llc", "ltd",
    "limited", "gmbh", "kg", "spa", "usa", "us", "americas", "america",
    "operators", "operator", "automation", "products", "equipment", "solutions",
    "group", "international", "enterprises", "systems", "entrance", "hardware",
    "springs", "spring",
}

# Folder-brand -> canonical brand-name string used for CSV lookup. Only the
# cases that normalization alone does not resolve.
_BRAND_ALIASES = {
    "BnD-Doors-AU": "B&D",
    "CHI": "C.H.I.",
    "Hormann": "Hörmann",
    "Steel-Line-AU": "Steel-Line",
    "Centurion-AU": "Centurion",
    "Gliderol-AU": "Gliderol",
    "Sears-Craftsman": "Craftsman",
    "Allister-Allstar": "Allister",
    "Multi-Code-Linear": "Multi-Code",
    "Apollo-Gate-Operators": "Apollo",
    "Eagle-Access-Control": "Eagle",
    "Crawford-ASSA-ABLOY": "Crawford",
    "Albany-ASSA-ABLOY": "Albany",
    "Hafa-ASSA-ABLOY": "Hafa",
    "GfA-Elektromaten": "GfA",
    "Windsor-Door-NZ": "Windsor",
    "Manaras-Opera": "Manaras",
    "Goffs": "Goff's",
    "Service-Spring": "SSC",
    "IDC-Spring": "IDC",
    "Mid-America-Door": "Mid-America",
}


def normalize_brand(name: str) -> str:
    """Lowercase, drop punctuation and corporate-noise tokens, collapse."""
    if not name:
        return ""
    # Normalize the common Hörmann mojibake and umlauts.
    name = name.replace("�", "o").replace("ö", "o").replace("Ö", "o")
    name = name.lower()
    name = name.replace("&", " and ")
    tokens = re.split(r"[^a-z0-9]+", name)
    kept = [t for t in tokens if t and t not in _BRAND_NOISE]
    if not kept:  # name was entirely noise (e.g. "Garage Door Co") -> keep raw
        kept = [t for t in tokens if t]
    return "".join(kept)


def category_label(category: str) -> str:
    return CATEGORY_LABELS.get(category, category)


@dataclass
class ManufacturerRow:
    manufacturer: str
    brand_family: str
    parent_company: str
    hq_country: str
    hq_state: str
    hq_city: str
    status: str
    website: str
    product_lines: str
    sub_category: str
    category: str  # raw CSV value, e.g. "01-Panels"


def _read_csv_resilient(path: Path) -> list[dict]:
    """Read a CSV that may be utf-8, utf-8-sig, or cp1252 (mojibake source)."""
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            with open(path, encoding=enc, newline="") as f:
                return list(csv.DictReader(f))
        except (UnicodeDecodeError, UnicodeError):
            continue
    # Last resort: replace undecodable bytes.
    with open(path, encoding="utf-8", errors="replace", newline="") as f:
        return list(csv.DictReader(f))


class MetadataIndex:
    """Loads the two CSVs and answers per-file metadata lookups."""

    def __init__(self, manifest_csv: Path, manufacturers_csv: Path):
        self._manifest_by_filename: dict[str, dict] = {}
        self._mfr_index: dict[str, list[ManufacturerRow]] = {}
        self._load_manifest(manifest_csv)
        self._load_manufacturers(manufacturers_csv)

    # ---- manifest --------------------------------------------------------
    def _load_manifest(self, path: Path) -> None:
        if not path.exists():
            return
        for row in _read_csv_resilient(path):
            fn = (row.get("filename") or "").strip()
            if fn and fn != "filename":
                # Keep the first OK row per filename; otherwise any row.
                if fn not in self._manifest_by_filename or row.get("status") == "OK":
                    self._manifest_by_filename[fn] = row

    # ---- manufacturers ---------------------------------------------------
    def _load_manufacturers(self, path: Path) -> None:
        if not path.exists():
            return
        for row in _read_csv_resilient(path):
            mr = ManufacturerRow(
                manufacturer=(row.get("Manufacturer") or "").strip(),
                brand_family=(row.get("Brand_Family") or "").strip(),
                parent_company=(row.get("Parent_Company") or "").strip(),
                hq_country=(row.get("HQ_Country") or "").strip(),
                hq_state=(row.get("HQ_State_Province") or "").strip(),
                hq_city=(row.get("HQ_City") or "").strip(),
                status=(row.get("Status") or "").strip(),
                website=(row.get("Website") or "").strip(),
                product_lines=(row.get("Product_Lines") or "").strip(),
                sub_category=(row.get("SubCategory") or "").strip(),
                category=(row.get("Category") or "").strip(),
            )
            for key in {normalize_brand(mr.manufacturer), normalize_brand(mr.brand_family)}:
                if key:
                    self._mfr_index.setdefault(key, []).append(mr)

    def lookup_manufacturer(
        self, brand_folder: str, category: str
    ) -> Optional[ManufacturerRow]:
        """Resolve a brand folder name to its manufacturers-master row.

        Disambiguates same-named brands across categories by preferring the
        row whose CSV Category shares the document's leading category number
        (e.g. doc '01-Garage-Door-Panels' -> CSV '01-Panels')."""
        canonical = _BRAND_ALIASES.get(brand_folder, brand_folder)
        key = normalize_brand(canonical)
        rows = self._mfr_index.get(key)
        if not rows:
            return None
        if len(rows) == 1:
            return rows[0]
        cat_num = category[:2] if category else ""
        for r in rows:
            if r.category[:2] == cat_num:
                return r
        return rows[0]

    def manifest_for(self, filename: str) -> dict:
        return self._manifest_by_filename.get(filename, {})


@dataclass
class DocMeta:
    rel_path: str
    filename: str
    category: str
    category_label: str
    region: Optional[str]
    brand: Optional[str]
    doc_type: Optional[str]
    sha256: Optional[str] = None
    source_url: Optional[str] = None
    size_bytes: Optional[int] = None
    # manufacturer enrichment
    manufacturer: Optional[str] = None
    parent_company: Optional[str] = None
    hq_country: Optional[str] = None
    hq_state: Optional[str] = None
    hq_city: Optional[str] = None
    brand_status: Optional[str] = None
    website: Optional[str] = None
    product_lines: Optional[str] = None
    sub_category: Optional[str] = None
    # hosting rights: None = link-out only (default); 'allowed' = may serve directly
    host_rights: Optional[str] = None


# Doc-type is the trailing segment(s) of the filename after the brand/model.
# We map the manifest's controlled vocabulary plus filename-suffix heuristics.
_DOCTYPE_PATTERNS = [
    (re.compile(r"owners?-?manual|^om(-|$)|-om(-|$)", re.I), "Owner-Manual"),
    (re.compile(r"install", re.I), "Install"),
    (re.compile(r"brochure", re.I), "Brochure"),
    (re.compile(r"catalog|catalogue|full-?line", re.I), "Catalog"),
    (re.compile(r"\bspec\b|spec-?sheet|technical|tds|datasheet", re.I), "Spec"),
    (re.compile(r"warranty", re.I), "Warranty"),
    (re.compile(r"program", re.I), "Programming"),
    (re.compile(r"guide", re.I), "Guide"),
    (re.compile(r"parts?", re.I), "Parts"),
]


def _guess_doc_type(filename: str, manifest_doc_type: str) -> Optional[str]:
    if manifest_doc_type and manifest_doc_type not in ("", "doc_type"):
        return manifest_doc_type
    stem = filename.rsplit(".", 1)[0]
    for pat, label in _DOCTYPE_PATTERNS:
        if pat.search(stem):
            return label
    return None


def build_doc_meta(pdf_path: Path, library_root: Path, idx: MetadataIndex) -> DocMeta:
    rel = pdf_path.relative_to(library_root)
    parts = rel.parts
    rel_posix = rel.as_posix()
    filename = pdf_path.name

    category = parts[0] if len(parts) >= 1 else ""
    region = parts[1] if len(parts) >= 2 else None
    # brand is the folder under region, unless the file sits directly in a
    # region folder (then there is no brand level).
    brand: Optional[str] = None
    if len(parts) >= 4:
        brand = parts[2]
    elif len(parts) == 3:
        # {category}/{region}/{file}.pdf  -> no brand folder
        brand = None
    if brand in REGIONS or brand in META_FOLDERS:
        brand = None

    man = idx.manifest_for(filename)
    doc_type = _guess_doc_type(filename, (man.get("doc_type") or "").strip())

    size_bytes = None
    if man.get("size_bytes", "").strip().isdigit():
        size_bytes = int(man["size_bytes"])

    meta = DocMeta(
        rel_path=rel_posix,
        filename=filename,
        category=category,
        category_label=category_label(category),
        region=region,
        brand=brand,
        doc_type=doc_type,
        sha256=(man.get("sha256") or "").strip() or None,
        source_url=(man.get("source_url") or "").strip() or None,
        size_bytes=size_bytes,
        host_rights=(man.get("host_rights") or "").strip() or None,
    )

    if brand:
        mr = idx.lookup_manufacturer(brand, category)
        if mr:
            meta.manufacturer = mr.manufacturer or None
            meta.parent_company = mr.parent_company or None
            meta.hq_country = mr.hq_country or None
            meta.hq_state = mr.hq_state or None
            meta.hq_city = mr.hq_city or None
            meta.brand_status = mr.status or None
            meta.website = mr.website or None
            meta.product_lines = mr.product_lines or None
            meta.sub_category = mr.sub_category or None
    return meta
