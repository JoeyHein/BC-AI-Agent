"""Glass-kit workarounds — why a missing glass kit may not really block a job.

Joey's product knowledge, encoded:
  - RESIDENTIAL kits are GK15; COMMERCIAL kits are GK16.
  - We PAINT frames for RESIDENTIAL (GK15) only — residential has many colours,
    so a different-colour kit off the shelf can be painted to what's needed.
  - We do NOT paint COMMERCIAL (GK16) — commercial only comes black or white.
    Its workaround is flexible substitution (size/glass), not colour.
  - Residential kits also come SHORT vs LONG by panel length.

The glass-kit description carries series, size, glass type and (for framed kits)
frame colour as its last comma field. So "same kit, different colour" =
identical description up to that last field. For a residential kit, if such a
kit is in stock, the blocker is workaroundable by painting; if the glass or size
differs, it is not.
"""

import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# Both carry a frame colour in the description; GK17 is aluminium glazing.
FRAMED_GK_PREFIXES = {"GK15", "GK16"}
# Only residential frames get painted. Commercial is black/white only.
PAINTABLE_GK_PREFIXES = {"GK15"}


def parse_gk(sku: str, description: str) -> Optional[dict]:
    """Structured view of a glass kit, or None if it isn't one.

    ``paint_key`` is the description with the frame colour stripped — two framed
    kits share a paint_key exactly when only their colour differs (same series,
    size and glass), which is precisely when one can be painted to serve the
    other.
    """
    sku = (sku or "").strip().upper()
    if not sku.startswith("GK"):
        return None
    d = (description or "").upper().strip()
    prefix = sku[:4]
    framed = prefix in FRAMED_GK_PREFIXES
    paintable = prefix in PAINTABLE_GK_PREFIXES   # residential (GK15) only
    # Residential = GK15, commercial = GK16 (authoritative by prefix).
    is_residential = prefix == "GK15"
    is_commercial = prefix == "GK16"

    frame_color = None
    paint_key = d
    if framed and "," in d:
        idx = d.rfind(",")
        frame_color = d[idx + 1:].strip()
        paint_key = d[:idx].strip()

    return {
        "sku": sku,
        "framed": framed,
        "paintable": paintable,
        "is_commercial": is_commercial,
        "is_residential": is_residential,
        "frame_color": frame_color,
        "paint_key": paint_key,
    }


class GlassKitService:
    def paint_substitutes(
        self, target_sku: str, target_desc: str, catalog: Dict[str, str],
        in_stock: Dict[str, float],
    ) -> List[dict]:
        """In-stock kits that could be PAINTED to serve ``target_sku`` — same
        series/size/glass, only a different frame colour.

        ``catalog``  {sku: description} for all glass kits.
        ``in_stock`` {sku: on_hand} (only kits with stock need be passed).
        """
        tgt = parse_gk(target_sku, target_desc)
        # Only RESIDENTIAL frames get painted — commercial is black/white only.
        if not tgt or not tgt["paintable"]:
            return []

        subs = []
        for sku, oh in in_stock.items():
            if sku == target_sku or (oh or 0) <= 0:
                continue
            cand = parse_gk(sku, catalog.get(sku, ""))
            if not cand or not cand["paintable"]:
                continue
            # Same kit in every respect but colour = paintable.
            if cand["paint_key"] == tgt["paint_key"] and cand["frame_color"] != tgt["frame_color"]:
                subs.append({
                    "sku": sku, "on_hand": oh,
                    "frame_color": cand["frame_color"],
                    "target_color": tgt["frame_color"],
                })
        return subs

    def workaround(
        self, blocker_sku: str, blocker_desc: str,
        catalog: Dict[str, str], in_stock: Dict[str, float],
    ) -> Optional[dict]:
        """Classify a glass-kit blocker's workaround, or None if it's just a GK
        with no help (glass genuinely missing)."""
        gk = parse_gk(blocker_sku, blocker_desc)
        if not gk:
            return None

        paint = self.paint_substitutes(blocker_sku, blocker_desc, catalog, in_stock)
        if paint:
            best = max(paint, key=lambda p: p["on_hand"])
            return {
                "type": "paint_frame",
                "detail": (f"paint {best['sku']} ({best['frame_color']}, {best['on_hand']} in stock) "
                           f"to {best['target_color']}"),
                "options": paint,
            }
        if gk["is_commercial"]:
            return {"type": "commercial_flex",
                    "detail": "commercial kit — flexible, check for a substitutable size/glass"}
        if gk["is_residential"]:
            return {"type": "residential",
                    "detail": "residential kit — check long vs short by panel length"}
        return None


glass_kit_service = GlassKitService()
