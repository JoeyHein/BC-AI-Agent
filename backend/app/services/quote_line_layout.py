"""Quote line order and subtotal check marks.

Every delivery quote gets exactly one FREIGHT line, after every door
package. WRAP stays with its door. The freight line is labeled
``Freight (estimate)``; the quote builder adds the estimate comment
after it is priced.

Off (the default) leaves operators inside the door they were built for.
Every operator-category line — including the chain or belt rail — gets
BC's Output check mark, which starts a new subtotal group.

``quote_line_layout_v2`` (AppSettings, missing row is off) also:

* keeps one WRAP line inside each door package, after that package's
  parts, so the package subtotal includes wrapping;
* lifts operators and their add-ons out to after every door package;
* puts a chain or belt rail directly under its operator head, without
  its own check mark, so the two share one operator subtotal.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

QUOTE_LINE_LAYOUT_V2 = "quote_line_layout_v2"

# LiftMaster trolley rails the builder auto-adds. A description match below
# also catches a 6' rail or a renamed card that isn't in this set.
_RAIL_PART_NUMBERS = frozenset({
    "OP19-02001-00",  # 7 ft belt
    "OP19-02002-00",  # 8 ft belt
    "OP19-02003-00",  # 10 ft belt
    "OP19-02004-00",  # 7 ft chain
    "OP19-02005-00",  # 8 ft chain
    "OP19-02006-00",  # 10 ft chain
})

# Aluminum section extrusions say "rail" too. They stay in the door package.
_SECTION_RAIL_MARKERS = (
    "MALE RAIL",
    "FEMALE RAIL",
    "END RAIL",
    "BUILD UP RAIL",
    "BUILD-UP RAIL",
)

# "7ft Full Chain Rail", "8 ft. Belt Rail", "6' chain rail".
# A trailing \\b after the foot mark fails: the apostrophe and the period in
# "ft." are not word characters, so there is no boundary before the space.
_LENGTH_RAIL = re.compile(
    r"(?ix)"
    r"(?:\b\d+\s*(?:ft\.?|foot)(?!\w).{0,60}?\brails?\b)"
    r"|(?:\b\d+\s*'.{0,60}?\brails?\b)"
    r"|(?:\brails?\b.{0,60}?\b\d+\s*(?:ft\.?|foot)(?!\w))"
    r"|(?:\brails?\b.{0,60}?\b\d+\s*')"
)

_ON_VALUES = {"on", "true", "1", "yes"}


def _is_on(raw) -> bool:
    if isinstance(raw, dict):
        if "enabled" in raw:
            raw = raw.get("enabled")
        else:
            raw = raw.get("mode") or raw.get("value") or ""
    if isinstance(raw, bool):
        return raw
    return str(raw or "").strip().lower() in _ON_VALUES


def quote_line_layout_v2_enabled(db: Optional[Session]) -> bool:
    """Missing setting, missing table, or anything other than on is off."""
    if db is None:
        return False
    nested = None
    try:
        from app.db.models import AppSettings
        nested = db.begin_nested()
        row = db.query(AppSettings).filter(
            AppSettings.setting_key == QUOTE_LINE_LAYOUT_V2
        ).first()
        value = row.setting_value if row is not None else None
        nested.commit()
    except Exception:
        logger.warning(
            "Could not read %s; treating quote line layout v2 as off",
            QUOTE_LINE_LAYOUT_V2,
            exc_info=True,
        )
        if nested is not None:
            try:
                nested.rollback()
            except Exception:
                pass
        return False
    return _is_on(value)


def set_quote_line_layout_v2(db: Session, enabled: bool, user_id: Optional[int] = None) -> str:
    """Persist the switch. A missing row stays off, so this is not a migration."""
    from app.db.models import AppSettings
    mode = "on" if enabled else "off"
    row = db.query(AppSettings).filter(
        AppSettings.setting_key == QUOTE_LINE_LAYOUT_V2
    ).first()
    if row is None:
        row = AppSettings(
            setting_key=QUOTE_LINE_LAYOUT_V2,
            setting_value=mode,
            description=(
                "Quote line layout v2. Freight is one trailing line either way. "
                "On also keeps wrapping inside each door subtotal and groups "
                "a chain rail with its operator."
            ),
            updated_by=user_id,
        )
        db.add(row)
    else:
        row.setting_value = mode
        row.updated_by = user_id
        row.updated_at = datetime.utcnow()
    db.flush()
    return mode


def is_operator_rail(line: dict) -> bool:
    """Chain or belt rail that travels with an operator head.

    Known rail item numbers, plus a length-plus-rail description so a 6'
    rail (or a renamed card) groups the same way. Aluminum section rails
    are not operator rails.
    """
    if not isinstance(line, dict):
        return False
    part_number = (line.get("part_number") or line.get("lineObjectNumber") or "").upper()
    if part_number in _RAIL_PART_NUMBERS:
        return True
    description = line.get("description") or ""
    upper = description.upper()
    if any(marker in upper for marker in _SECTION_RAIL_MARKERS):
        return False
    return bool(_LENGTH_RAIL.search(description))


def _is_wrap_line(line: dict) -> bool:
    part_number = (line.get("part_number") or "").upper()
    category = (line.get("category") or "").lower()
    return part_number == "WRAP" or category == "wrapping"


def _is_operator_addon(line: dict) -> bool:
    """Operator head, rail, hoist, spreader, photo eye, and other operator add-ons.

    Door accessories (man door, pusher springs) stay in the package. They
    are category ``accessory``, not ``operator``.
    """
    if (line.get("category") or "").lower() == "operator":
        return True
    return is_operator_rail(line)


def _is_freight_placeholder(line: dict, freight_item: str) -> bool:
    if not isinstance(line, dict):
        return False
    if line.get("is_door_freight"):
        return True
    part_number = (line.get("part_number") or "").upper()
    category = (line.get("category") or "").lower()
    return part_number == (freight_item or "FREIGHT").upper() and category == "freight"


def line_needs_output(line: dict, *, layout_v2: bool) -> bool:
    """BC Output check mark. Checked lines start a subtotal of the lines below.

    Door headers always start a package subtotal. Operator lines start their
    own subtotal, except a chain/belt rail under layout v2, which stays in
    the operator head's group. Freight's check mark is set when that line
    is priced, not here.
    """
    if not isinstance(line, dict):
        return False
    if layout_v2 and line.get("suppress_output"):
        return False
    if line.get("is_door_desc"):
        return True
    if (line.get("category") or "").lower() != "operator":
        return False
    # A rail keeps its own check mark unless group_operator_with_rails put it
    # under an operator head (suppress_output). A lone rail must not fall
    # into the previous door package.
    return True


def group_operator_with_rails(lines: list) -> list:
    """Put each rail directly under the operator head and clear its check mark.

    Other add-ons keep their own check marks and follow the head+rail pair,
    so a photo eye between the head and the rail cannot split them into two
    subtotals. A rail with no operator head keeps its check mark; otherwise
    it would fall into the previous door package.
    """
    if not lines:
        return []
    head_index = None
    for index, line in enumerate(lines):
        if not is_operator_rail(line) and (line.get("category") or "").lower() == "operator":
            head_index = index
            break
    if head_index is None:
        return list(lines)
    head = lines[head_index]
    rails = []
    rest = []
    for index, line in enumerate(lines):
        if index == head_index:
            continue
        if is_operator_rail(line):
            marked = dict(line)
            marked["suppress_output"] = True
            rails.append(marked)
        else:
            rest.append(line)
    return [head, *rails, *rest]


def _quote_freight_line(freight_item: str) -> dict:
    from app.services.quote_adjustments import FREIGHT_ESTIMATE_LABEL
    return {
        "lineType": "Item",
        "part_number": freight_item or "FREIGHT",
        "description": FREIGHT_ESTIMATE_LABEL,
        "quantity": 1,
        "category": "freight",
        # Not a door line. One slot still receives the full quote freight
        # amount: door_freight_amounts weights a single placeholder at 100%.
        "door_index": None,
        "is_door_freight": True,
        "fixed_unit_price": 0,
    }


def _without_freight(lines: list, freight_item: str) -> list:
    return [
        line for line in lines
        if not _is_freight_placeholder(line, freight_item) and not line.get("is_freight_note")
    ]


def arrange_quote_lines(
    lines: list,
    *,
    layout_v2: bool,
    include_freight: bool,
    freight_item: str = "FREIGHT",
) -> list:
    """Return the lines in post order.

    Both flags post one freight line after every door. Flag on also lifts
    operator add-ons out of each package and leaves one WRAP at the end of
    the package. Flag off keeps the door order it was given, including WRAP.
    """
    if not lines:
        return []
    if not layout_v2:
        ordered = _without_freight(lines, freight_item)
        if include_freight:
            ordered.append(_quote_freight_line(freight_item))
        return ordered

    preamble = []
    packages = []
    current = None
    for line in lines:
        if _is_freight_placeholder(line, freight_item):
            continue
        if line.get("is_door_desc"):
            current = [line]
            packages.append(current)
            continue
        if current is None:
            preamble.append(line)
        else:
            current.append(line)

    ordered = list(preamble)
    addons = []
    for package in packages:
        door_lines = []
        wraps = []
        package_addons = []
        for line in package:
            if _is_operator_addon(line):
                package_addons.append(line)
            elif _is_wrap_line(line):
                wraps.append(line)
            else:
                door_lines.append(line)
        ordered.extend(door_lines)
        ordered.extend(wraps)
        addons.extend(group_operator_with_rails(package_addons))
    ordered.extend(addons)
    if include_freight:
        ordered.append(_quote_freight_line(freight_item))
    return ordered


def apply_quote_line_layout(
    lines: list,
    *,
    db: Optional[Session],
    include_freight: bool,
    freight_item: str = "FREIGHT",
) -> tuple:
    """Arrange ``lines`` for the current flag. Returns ``(lines, layout_v2)``."""
    enabled = quote_line_layout_v2_enabled(db)
    if enabled:
        logger.info("Quote line layout v2: operators follow the doors, wrap inside each door")
    return (
        arrange_quote_lines(
            lines,
            layout_v2=enabled,
            include_freight=include_freight,
            freight_item=freight_item,
        ),
        enabled,
    )
