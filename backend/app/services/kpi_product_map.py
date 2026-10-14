"""Configurable product-line, operator-brand, and freight matching.

The default list lives in ``kpi_product_lines.json`` beside this file.
Replace it without a code change by setting ``KPI_PRODUCT_LINE_MAP_FILE``
to another JSON file, or ``KPI_PRODUCT_LINE_MAP`` to a JSON object.

A line matches the first product line whose token appears in the item
number, description, or item category. Tokens match on word boundaries,
so TX450 matches TX450-0907 and does not match TX4500.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

_DEFAULT_PATH = Path(__file__).with_name("kpi_product_lines.json")


@dataclass(frozen=True)
class MatchGroup:
    id: str
    label: str
    match: tuple[str, ...]


@dataclass(frozen=True)
class ProductMap:
    lines: tuple[MatchGroup, ...]
    operators: tuple[MatchGroup, ...]
    freight: tuple[str, ...]
    low_margin_pct: float = 20.0
    so_to_po_late_days: int = 5
    slow_mover_days: int = 90
    source: str = "default"

    def public(self) -> dict:
        def groups(rows: tuple[MatchGroup, ...]) -> list[dict]:
            return [{"id": row.id, "label": row.label, "match": list(row.match)} for row in rows]

        return {
            "source": self.source,
            "low_margin_pct": self.low_margin_pct,
            "so_to_po_late_days": self.so_to_po_late_days,
            "slow_mover_days": self.slow_mover_days,
            "lines": groups(self.lines),
            "operators": groups(self.operators),
            "freight": list(self.freight),
        }


def _groups(raw: list, fallback_label: str) -> tuple[MatchGroup, ...]:
    out: list[MatchGroup] = []
    for row in raw or []:
        tokens = tuple(
            str(token).strip().upper()
            for token in (row.get("match") or [])
            if str(token).strip()
        )
        group_id = str(row.get("id") or "").strip()
        if not group_id or not tokens:
            continue
        out.append(MatchGroup(
            id=group_id,
            label=str(row.get("label") or fallback_label),
            match=tokens,
        ))
    return tuple(out)


def product_map_from_dict(data: dict, source: str = "default") -> ProductMap:
    return ProductMap(
        lines=_groups(data.get("lines") or [], "Product line"),
        operators=_groups(data.get("operators") or [], "Operator"),
        freight=tuple(
            str(token).strip().upper()
            for token in (data.get("freight") or [])
            if str(token).strip()
        ),
        low_margin_pct=float(data.get("low_margin_pct") or 20),
        so_to_po_late_days=int(data.get("so_to_po_late_days") or 5),
        slow_mover_days=int(data.get("slow_mover_days") or 90),
        source=source,
    )


def load_product_map() -> ProductMap:
    """File on disk, unless an environment override is set."""
    inline = (os.environ.get("KPI_PRODUCT_LINE_MAP") or "").strip()
    if inline:
        return product_map_from_dict(json.loads(inline), source="KPI_PRODUCT_LINE_MAP")
    path = Path(os.environ.get("KPI_PRODUCT_LINE_MAP_FILE") or _DEFAULT_PATH)
    data = json.loads(path.read_text(encoding="utf-8"))
    source = "file" if path.resolve() != _DEFAULT_PATH.resolve() else "default"
    loaded = product_map_from_dict(data, source=source)
    return ProductMap(
        lines=loaded.lines,
        operators=loaded.operators,
        freight=loaded.freight,
        low_margin_pct=loaded.low_margin_pct,
        so_to_po_late_days=loaded.so_to_po_late_days,
        slow_mover_days=loaded.slow_mover_days,
        source=str(path) if source == "file" else "default",
    )


def _contains_token(haystack: str, token: str) -> bool:
    token = (token or "").upper()
    if not token:
        return False
    start = 0
    while True:
        found = haystack.find(token, start)
        if found < 0:
            return False
        before = haystack[found - 1] if found else " "
        after_at = found + len(token)
        after = haystack[after_at] if after_at < len(haystack) else " "
        if not before.isalnum() and not after.isalnum():
            return True
        start = found + 1


def _haystack(*parts: Optional[str]) -> str:
    return " ".join(str(part or "") for part in parts).upper()


def _first_group(groups: tuple[MatchGroup, ...], text: str) -> Optional[MatchGroup]:
    for group in groups:
        if any(_contains_token(text, token) for token in group.match):
            return group
    return None


def classify_product_line(product_map: ProductMap, item_number: str, description: str,
                          category: str = "") -> Optional[MatchGroup]:
    return _first_group(product_map.lines, _haystack(item_number, description, category))


def classify_operator(product_map: ProductMap, item_number: str, description: str) -> Optional[MatchGroup]:
    return _first_group(product_map.operators, _haystack(item_number, description))


def is_freight(product_map: ProductMap, item_number: str, description: str) -> bool:
    text = _haystack(item_number, description)
    return any(_contains_token(text, token) for token in product_map.freight)
