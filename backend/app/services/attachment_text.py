"""Text and openings from email attachments.

PDF text comes from the text layer. A page with almost no text, and an
image, go through OCR when tesseract is installed. The page is still
listed when OCR is not available, so staff can see the file. DXF drawings
contribute their text entities. Nothing here sends mail.
"""
from __future__ import annotations

import base64
import logging
import re
import shutil
from dataclasses import dataclass, field
from io import BytesIO
from typing import Any, Callable, List, Optional

logger = logging.getLogger(__name__)

PDF_TYPES = {"application/pdf"}
IMAGE_TYPES = {"image/png", "image/jpeg", "image/jpg", "image/tiff", "image/bmp", "image/webp"}
DXF_TYPES = {"application/dxf", "image/vnd.dxf", "application/acad"}
MAX_TEXT_CHARS = 20000
_OCR_MIN_CHARS = 20

_FT_IN = re.compile(
    r"(\d{1,2})\s*'\s*(?:(\d{1,2})\s*(?:\"|in)?)?\s*[x×]\s*(\d{1,2})\s*'\s*(?:(\d{1,2})\s*(?:\"|in)?)?",
    re.I,
)
_FEET = re.compile(
    r"(\d{1,2}(?:\.\d+)?)\s*(?:ft|feet)\s*[x×]\s*(\d{1,2}(?:\.\d+)?)\s*(?:ft|feet)",
    re.I,
)
_INCHES = re.compile(
    r"(\d{2,3})\s*(?:\"|in(?:ch(?:es)?)?)\s*[x×]\s*(\d{2,3})\s*(?:\"|in(?:ch(?:es)?)?)",
    re.I,
)
_NEAR_DOOR = re.compile(
    r"(?:door|opening|size)[^\n]{0,40}?(\d{1,2})\s*[x×]\s*(\d{1,2})\b",
    re.I,
)


@dataclass
class PageText:
    file_name: str
    page: int
    text: str
    method: str


@dataclass
class AttachmentRead:
    pages: List[PageText] = field(default_factory=list)
    openings: List[dict] = field(default_factory=list)
    combined_text: str = ""

    def staff_payload(self, applied: bool) -> dict:
        files = []
        seen = []
        for page in self.pages:
            if page.file_name not in seen:
                seen.append(page.file_name)
        for name in seen:
            rows = [page for page in self.pages if page.file_name == name]
            files.append({
                "name": name,
                "pages": [
                    {
                        "page": page.page,
                        "method": page.method,
                        "excerpt": (page.text or "").strip()[:180],
                    }
                    for page in rows
                ],
            })
        return {
            "applied": applied,
            "opening_count": len(self.openings),
            "openings": self.openings,
            "files": files,
        }

    def as_email_log(self) -> list:
        """Shape quote_email_text already reads. Text here counts as the email."""
        by_name = []
        seen = []
        for page in self.pages:
            if page.file_name not in seen:
                seen.append(page.file_name)
        for name in seen:
            rows = [page for page in self.pages if page.file_name == name]
            text = "\n".join(page.text for page in rows if page.text)
            by_name.append({
                "name": name,
                "extracted_text": text,
                "pages": [{"page": page.page, "method": page.method} for page in rows],
            })
        return by_name


def ocr_engine_available() -> bool:
    if shutil.which("tesseract") is None:
        return False
    try:
        import pytesseract  # noqa: F401
        from PIL import Image  # noqa: F401
    except Exception:
        return False
    return True


def ocr_image_bytes(data: bytes) -> str:
    """Read words off an image. Empty when tesseract is not installed."""
    if not data or not ocr_engine_available():
        return ""
    try:
        import pytesseract
        from PIL import Image
        image = Image.open(BytesIO(data))
        return pytesseract.image_to_string(image) or ""
    except Exception:
        logger.info("OCR could not read an image", exc_info=True)
        return ""


def read_graph_attachments(raw_attachments: Optional[list]) -> AttachmentRead:
    pages: List[PageText] = []
    for item in raw_attachments or []:
        if not isinstance(item, dict):
            continue
        name = item.get("name") or "attachment"
        content_type = (item.get("contentType") or "").split(";")[0].strip().lower()
        encoded = item.get("contentBytes")
        if not encoded:
            pages.append(PageText(name, 1, "", "no_bytes"))
            continue
        try:
            data = base64.b64decode(encoded)
        except Exception:
            logger.info("Could not decode attachment %s", name)
            pages.append(PageText(name, 1, "", "decode_failed"))
            continue
        pages.extend(_read_one(name, content_type, data))
    openings = find_openings(pages)
    combined = _combined(pages)
    return AttachmentRead(pages=pages, openings=openings, combined_text=combined)


def find_openings(pages: List[PageText]) -> List[dict]:
    found = []
    seen = set()
    for page in pages:
        for opening in _openings_in_text(page.text or ""):
            key = (page.file_name, page.page, opening["width_in"], opening["height_in"])
            if key in seen:
                continue
            seen.add(key)
            found.append({
                "index": len(found) + 1,
                "label": opening["label"],
                "width_in": opening["width_in"],
                "height_in": opening["height_in"],
                "file": page.file_name,
                "page": page.page,
                "method": page.method,
                "excerpt": opening["excerpt"],
            })
    return found


def _read_one(name: str, content_type: str, data: bytes) -> List[PageText]:
    lower = name.lower()
    if content_type in PDF_TYPES or lower.endswith(".pdf"):
        return _read_pdf(name, data)
    if content_type in IMAGE_TYPES or lower.endswith((".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp")):
        return [_read_image(name, data)]
    if content_type in DXF_TYPES or lower.endswith(".dxf"):
        return [_read_dxf(name, data)]
    return [PageText(name, 1, "", "unsupported")]


def _read_pdf(name: str, data: bytes) -> List[PageText]:
    try:
        from pypdf import PdfReader
        reader = PdfReader(BytesIO(data))
    except Exception:
        logger.info("Could not open PDF %s", name, exc_info=True)
        return [PageText(name, 1, "", "unreadable")]
    pages = []
    for index, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        method = "text_layer"
        if len(text.strip()) < _OCR_MIN_CHARS:
            ocr_text, method = _ocr_pdf_page(page, text)
            if ocr_text.strip():
                text = ocr_text
        pages.append(PageText(name, index, text, method))
    return pages or [PageText(name, 1, "", "unreadable")]


def _ocr_pdf_page(page, text: str):
    images = []
    try:
        images = list(getattr(page, "images", []) or [])
    except Exception:
        images = []
    chunks = []
    for image in images:
        blob = getattr(image, "data", None)
        if not blob:
            continue
        got = ocr_image_bytes(blob)
        if got.strip():
            chunks.append(got)
    if chunks:
        return "\n".join(chunks), "ocr"
    if images:
        return text, "ocr_unavailable" if not ocr_engine_available() else "ocr"
    if text.strip():
        return text, "text_layer"
    return text, "no_text_layer"


def _read_image(name: str, data: bytes) -> PageText:
    text = ocr_image_bytes(data)
    if text.strip():
        return PageText(name, 1, text, "ocr")
    method = "ocr_unavailable" if not ocr_engine_available() else "ocr"
    return PageText(name, 1, "", method)


def _read_dxf(name: str, data: bytes) -> PageText:
    try:
        import ezdxf
        try:
            doc = ezdxf.read(BytesIO(data))
        except TypeError:
            # ASCII DXF is a text file. BytesIO makes the tagger expect bytes.
            from io import StringIO
            doc = ezdxf.read(StringIO(data.decode("utf-8", errors="replace")))
    except Exception:
        logger.info("Could not open DXF %s", name, exc_info=True)
        return PageText(name, 1, "", "unreadable")
    lines = []
    try:
        space = doc.modelspace()
    except Exception:
        return PageText(name, 1, "", "unreadable")
    for entity in space:
        kind = entity.dxftype()
        if kind == "TEXT":
            value = getattr(entity.dxf, "text", "") or ""
        elif kind == "MTEXT":
            value = entity.plain_text() if hasattr(entity, "plain_text") else (getattr(entity, "text", "") or "")
        else:
            continue
        if str(value).strip():
            lines.append(str(value))
    return PageText(name, 1, "\n".join(lines), "dxf")


def _combined(pages: List[PageText]) -> str:
    blocks = []
    used = 0
    for page in pages:
        body = (page.text or "").strip()
        if not body:
            continue
        header = f"[{page.file_name} page {page.page}]"
        piece = f"{header}\n{body}"
        if used + len(piece) > MAX_TEXT_CHARS:
            remaining = MAX_TEXT_CHARS - used
            if remaining > len(header) + 20:
                blocks.append(piece[:remaining])
            blocks.append("[attachment text truncated]")
            break
        blocks.append(piece)
        used += len(piece)
    return "\n\n".join(blocks)


def _openings_in_text(text: str) -> List[dict]:
    found = []
    for match in _FT_IN.finditer(text):
        width = _feet_inches(match.group(1), match.group(2))
        height = _feet_inches(match.group(3), match.group(4))
        _add(found, width, height, match.group(0), text, match.start())
    for match in _FEET.finditer(text):
        width = int(round(float(match.group(1)) * 12))
        height = int(round(float(match.group(2)) * 12))
        _add(found, width, height, match.group(0), text, match.start())
    for match in _INCHES.finditer(text):
        _add(found, int(match.group(1)), int(match.group(2)), match.group(0), text, match.start())
    for match in _NEAR_DOOR.finditer(text):
        width = int(match.group(1))
        height = int(match.group(2))
        if width <= 40 and height <= 40:
            width *= 12
            height *= 12
        _add(found, width, height, match.group(0), text, match.start())
    return found


def _feet_inches(feet: str, inches: Optional[str]) -> int:
    total = int(feet) * 12
    if inches:
        total += int(inches)
    return total


def _add(found: list, width: int, height: int, label: str, text: str, start: int) -> None:
    if width < 36 or height < 36 or width > 480 or height > 480:
        return
    excerpt = text[max(0, start - 30): start + len(label) + 30].replace("\n", " ").strip()
    found.append({
        "width_in": width,
        "height_in": height,
        "label": " ".join(label.split()),
        "excerpt": excerpt,
    })


# Kept so a test can pass a page list through the same finder the reader uses.
def openings_from_pages(pages: List[PageText], ocr: Optional[Callable[..., Any]] = None) -> List[dict]:
    del ocr
    return find_openings(pages)
