"""Manual rows for the shop TV board.

Sales orders in Business Central stay in Draft, and fullyShipped does not
reliably mean the order has left, so the board's sales-order lanes are
often empty. Staff type the day here. Receiving rows land in Incoming.

Nothing in this module calls a Business Central POST, PATCH, or DELETE.
A customer name is read from the sales order only when a create leaves
that name blank.
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, time as clock_time, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from app.services.shop_tv_board import (
    SHOP_TZ,
    _group,
    _serialize_when,
    customer_name,
    shop_today,
)

logger = logging.getLogger(__name__)

LANES = ("pickup", "delivery", "receiving", "production")
BOARD_LANE = {
    "pickup": "pickups",
    "delivery": "deliveries",
    "receiving": "incoming",
    "production": "production",
}
WHEN_LABEL = {
    "pickups": "Pickup",
    "deliveries": "Delivery",
    "incoming": "Receiving",
    "production": "Production",
}
NOTE_MAX = 200
SO_MAX = 40
NAME_MAX = 200

_SO_IN_LABEL = re.compile(r"(SO-[\w-]+)", re.IGNORECASE)


def norm_so(value) -> str:
    return str(value or "").strip().upper()


def _clean_so(value) -> Optional[str]:
    text = norm_so(value)
    if not text:
        return None
    if len(text) > SO_MAX:
        raise ValueError("Sales order number is too long")
    return text


def _clean_name(value) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if len(text) > NAME_MAX:
        raise ValueError("Customer name is too long")
    return text


def _clean_note(value) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if len(text) > NOTE_MAX:
        raise ValueError("Note is too long")
    return text


def _clean_lane(value) -> str:
    lane = str(value or "").strip().lower()
    if lane not in LANES:
        raise ValueError("Lane must be pickup, delivery, receiving, or production")
    return lane


def _clean_date(value) -> date:
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, date):
        found = value
    else:
        text = str(value or "").strip()
        if not text or text.startswith("0001") or text.startswith("0000"):
            raise ValueError("Date is required")
        try:
            found = date.fromisoformat(text[:10])
        except ValueError as exc:
            raise ValueError("Date is required") from exc
    if found.year < 1900:
        raise ValueError("Date is required")
    return found


def _clean_time(value) -> Optional[clock_time]:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        value = value.time()
    if isinstance(value, clock_time):
        return value.replace(second=0, microsecond=0)
    text = str(value).strip()
    if not text:
        return None
    parts = text.split(":")
    if len(parts) < 2:
        raise ValueError("Time must be HH:MM")
    try:
        hour = int(parts[0])
        minute = int(parts[1])
    except ValueError as exc:
        raise ValueError("Time must be HH:MM") from exc
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        raise ValueError("Time must be HH:MM")
    return clock_time(hour, minute)


def lookup_bc_customer_name(so_number: str) -> Optional[str]:
    """Read the sales-order customer. Returns None when BC has no name.

    This is a GET. A failure leaves the name blank so staff can still
    save the row.
    """
    try:
        from app.integrations.bc.client import bc_client
        order = bc_client.get_sales_order_by_number(so_number)
    except Exception:
        logger.warning("Shop schedule could not read sales order %s", so_number, exc_info=True)
        return None
    if not isinstance(order, dict):
        return None
    return customer_name(order) or None


def _fill_customer(so_number: Optional[str], name: Optional[str], lookup) -> Optional[str]:
    if name or not so_number:
        return name
    try:
        found = lookup(so_number) if lookup is not None else None
    except Exception:
        logger.warning("Shop schedule customer lookup failed for %s", so_number, exc_info=True)
        return None
    text = str(found or "").strip()
    if len(text) > NAME_MAX:
        text = text[:NAME_MAX].rstrip()
    return text or None


def public_entry(row) -> dict:
    clock = row.entry_time
    created = row.created_at.isoformat() + "Z" if row.created_at else None
    updated = row.updated_at.isoformat() + "Z" if row.updated_at else None
    return {
        "id": row.id,
        "so_number": row.so_number,
        "customer_name": row.customer_name,
        "lane": row.lane,
        "date": row.entry_date.isoformat() if row.entry_date else None,
        "time": clock.strftime("%H:%M") if clock else None,
        "note": row.note,
        "done": bool(row.done),
        "created_by": row.created_by,
        "created_at": created,
        "updated_at": updated,
    }


def list_entries(db: Session) -> list:
    from app.db.models import ShopScheduleEntry
    rows = db.query(ShopScheduleEntry).all()
    rows.sort(key=lambda row: (
        row.entry_date or date.min,
        row.entry_time.strftime("%H:%M") if row.entry_time else "99:99",
        row.id or 0,
    ))
    return rows


def create_entry(db: Session, fields: dict, *, created_by: Optional[int], lookup=None) -> object:
    from app.db.models import ShopScheduleEntry
    so_number = _clean_so(fields.get("so_number"))
    name = _fill_customer(so_number, _clean_name(fields.get("customer_name")), lookup or lookup_bc_customer_name)
    row = ShopScheduleEntry(
        so_number=so_number,
        customer_name=name,
        lane=_clean_lane(fields.get("lane")),
        entry_date=_clean_date(fields.get("date")),
        entry_time=_clean_time(fields.get("time")),
        note=_clean_note(fields.get("note")),
        done=False,
        created_by=created_by,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def update_entry(db: Session, entry_id: int, changes: dict) -> Optional[object]:
    from app.db.models import ShopScheduleEntry
    row = db.query(ShopScheduleEntry).filter(ShopScheduleEntry.id == entry_id).first()
    if row is None:
        return None
    if "so_number" in changes:
        row.so_number = _clean_so(changes.get("so_number"))
    if "customer_name" in changes:
        row.customer_name = _clean_name(changes.get("customer_name"))
    if "lane" in changes:
        row.lane = _clean_lane(changes.get("lane"))
    if "date" in changes:
        if changes.get("date") is None:
            raise ValueError("Date is required")
        row.entry_date = _clean_date(changes.get("date"))
    if "time" in changes:
        row.entry_time = _clean_time(changes.get("time"))
    if "note" in changes:
        row.note = _clean_note(changes.get("note"))
    if "done" in changes and changes.get("done") is not None:
        row.done = bool(changes.get("done"))
    row.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(row)
    return row


def delete_entry(db: Session, entry_id: int) -> bool:
    from app.db.models import ShopScheduleEntry
    row = db.query(ShopScheduleEntry).filter(ShopScheduleEntry.id == entry_id).first()
    if row is None:
        return False
    db.delete(row)
    db.commit()
    return True


def _snapshot(row) -> dict:
    return {
        "id": row.id,
        "so_number": row.so_number,
        "customer_name": row.customer_name,
        "lane": row.lane,
        "date": row.entry_date,
        "time": row.entry_time,
        "note": row.note,
        "done": bool(row.done),
    }


def load_open_entries(db: Optional[Session]) -> list:
    """Open rows only. A missing table leaves the board on its BC rows."""
    if db is None:
        return []
    nested = None
    try:
        from app.db.models import ShopScheduleEntry
        nested = db.begin_nested()
        rows = (
            db.query(ShopScheduleEntry)
            .filter(ShopScheduleEntry.done.is_(False))
            .all()
        )
        copied = [_snapshot(row) for row in rows]
        nested.commit()
        return copied
    except Exception:
        logger.warning("Shop TV could not read schedule entries", exc_info=True)
        if nested is not None:
            try:
                nested.rollback()
            except Exception:
                pass
        return []


def _as_date(value) -> Optional[date]:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _as_clock(value) -> Optional[clock_time]:
    try:
        return _clean_time(value)
    except ValueError:
        return None


def _row_keys(item: dict) -> set:
    found = set()
    number = norm_so(item.get("order_number"))
    if number and number != "—":
        found.add(number)
    for so in item.get("sales_orders") or []:
        if isinstance(so, dict):
            found.add(norm_so(so.get("number") or so.get("order_number")))
        else:
            found.add(norm_so(so))
    label = str(item.get("sales_label") or "")
    match = _SO_IN_LABEL.match(label.strip())
    if match:
        found.add(norm_so(match.group(1)))
    return {key for key in found if key}


def manual_item(entry: dict, *, today: date, now: Optional[datetime], horizon: int) -> Optional[dict]:
    """One board row, or None when the entry is done or outside the window."""
    if entry.get("done"):
        return None
    day = _as_date(entry.get("date"))
    if day is None:
        return None
    if day > today + timedelta(days=horizon):
        return None
    lane = BOARD_LANE.get(str(entry.get("lane") or "").strip().lower())
    if lane is None:
        return None
    clock = _as_clock(entry.get("time"))
    timing = _serialize_when(day, clock, today, now, lane, "manual")
    so = norm_so(entry.get("so_number"))
    note = str(entry.get("note") or "").strip() or None
    timing["kind"] = "manual"
    timing["when_label"] = WHEN_LABEL[lane]
    return {
        "id": f"manual:{entry.get('id')}",
        "entry_id": entry.get("id"),
        "lane": lane,
        "order_number": so or "—",
        "customer": str(entry.get("customer_name") or "").strip(),
        "detail": None,
        "note": note,
        "destination": None,
        "manual": True,
        "so_number": so or None,
        **timing,
    }


def _flatten(days) -> list:
    items = []
    for day in days or []:
        items.extend(day.get("items") or [])
    return items


def apply_schedule_entries(board: dict, entries, *, now: Optional[datetime] = None) -> dict:
    """Merge typed rows into a board. Done rows and dates past the window stay off.

    A typed row hides the Business Central row for the same sales order
    on that lane. Receiving uses Incoming. Overdue and late follow the
    same rules as the other rows.
    """
    board = dict(board or {})
    lanes = {}
    for name, payload in (board.get("lanes") or {}).items():
        copied = dict(payload or {})
        days = []
        for day in copied.get("days") or []:
            day_copy = dict(day)
            day_copy["items"] = list(day.get("items") or [])
            days.append(day_copy)
        copied["days"] = days
        lanes[name] = copied

    current = now or datetime.now(SHOP_TZ)
    today_text = board.get("today")
    today = _as_date(today_text) or shop_today(current)
    try:
        horizon = int(board.get("horizon_days") or 7)
    except (TypeError, ValueError):
        horizon = 7

    manual = {lane: [] for lane in BOARD_LANE.values()}
    suppress = {lane: set() for lane in BOARD_LANE.values()}
    for raw in entries or []:
        entry = raw if isinstance(raw, dict) else _snapshot(raw)
        item = manual_item(entry, today=today, now=current, horizon=horizon)
        if item is None:
            continue
        manual[item["lane"]].append(item)
        if item.get("so_number"):
            suppress[item["lane"]].add(item["so_number"])

    for lane_name, added in manual.items():
        blocked = suppress[lane_name]
        if not added and not blocked:
            continue
        existing = _flatten((lanes.get(lane_name) or {}).get("days"))
        kept = []
        for item in existing:
            if item.get("manual"):
                kept.append(item)
                continue
            if blocked and _row_keys(item) & blocked:
                continue
            kept.append(item)
        kept.extend(added)
        payload = dict(lanes.get(lane_name) or {})
        payload["days"] = _group(kept, today, horizon)
        lanes[lane_name] = payload

    board["lanes"] = lanes
    return board


def merge_schedule_entries(db: Optional[Session], board: dict, *, now: Optional[datetime] = None) -> dict:
    return apply_schedule_entries(board, load_open_entries(db), now=now)
