"""Block-import utility for shop drawings.

The reference DXF (`tmp_shop_drawings/sample_reference.dxf`) contains named
blocks for panel stamps and hardware that we want to reuse in generated
drawings so output visually matches what fabricators already recognize.

Stage 2+ will call `import_blocks_from_reference()` once per `build_dxf()`
call, then `msp.add_blockref(name, insertion_point)` to place them.

Candidate blocks to import (from reference inspection):
    Panel stamps   : "Raised 20 x 14 stamp", "Raised Long",
                     "Carriage Long", "Carriage Short"
    Hardware       : "TOP BRACKET", "BTM BRACKET", "Astrigal",
                     "Black Retainer"

Loading an 11 MB DXF every time is expensive. In Stage 2 we'll extract the
blocks we actually use into a lean library DXF checked into the repo, and
import from that. For now this module just provides the primitive.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable, Optional

import ezdxf
from ezdxf.document import Drawing

logger = logging.getLogger(__name__)

# Path to the OneDrive-provided reference DXF. Copied into the repo at commit
# d89994c-ish; real value once we extract a lean library DXF will point to
# that instead.
# blocks.py lives at backend/app/services/shop_drawings/blocks.py
# parents: [0]=shop_drawings [1]=services [2]=app [3]=backend [4]=repo-root
DEFAULT_REFERENCE_DXF = (
    Path(__file__).resolve().parents[4] / "tmp_shop_drawings" / "sample_reference.dxf"
)

# Blocks we plan to reuse, grouped by role so Stage 2 can request a set.
PANEL_STAMP_BLOCKS = [
    "Raised 20 x 14 stamp",
    "Raised Long",
    "Carriage Long",
    "Carriage Short",
]
HARDWARE_BLOCKS = [
    "TOP BRACKET",
    "BTM BRACKET",
    "Astrigal",
    "Black Retainer",
]


def import_blocks_from_reference(
    target: Drawing,
    block_names: Iterable[str],
    source_path: Optional[Path] = None,
) -> list[str]:
    """Copy specific named blocks from a source DXF into `target`.

    Returns the list of block names that were successfully imported. Missing
    blocks are logged but don't raise (so callers can request a superset).

    Implementation uses ezdxf's `Importer` which handles nested block refs,
    layer dependencies, text styles, and linetypes automatically.
    """
    src_path = Path(source_path or DEFAULT_REFERENCE_DXF)
    if not src_path.exists():
        logger.warning(f"Reference DXF not found at {src_path}; no blocks imported")
        return []

    try:
        source = ezdxf.readfile(str(src_path))
    except Exception as e:
        logger.error(f"Failed to read reference DXF {src_path}: {e}")
        return []

    # Filter to blocks that actually exist in the source
    available = {name for name in block_names if name in source.blocks}
    missing = set(block_names) - available
    if missing:
        logger.warning(f"Blocks not in reference DXF: {sorted(missing)}")

    if not available:
        return []

    from ezdxf.addons import Importer
    importer = Importer(source, target)
    importer.import_blocks(sorted(available))
    importer.finalize()
    logger.info(f"Imported {len(available)} block(s) from {src_path.name}")
    return sorted(available)


def list_reference_blocks(source_path: Optional[Path] = None) -> list[str]:
    """Dev helper — list all human-named blocks in the reference DXF."""
    src_path = Path(source_path or DEFAULT_REFERENCE_DXF)
    if not src_path.exists():
        return []
    source = ezdxf.readfile(str(src_path))
    return sorted(
        blk.name
        for blk in source.blocks
        if not blk.name.startswith(("*", "A$C", "_"))
    )
