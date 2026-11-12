"""Shop TV board: three lanes from Business Central, nothing invented.

Lane mapping (configurable in app_settings key ``shop_tv_board_lanes``):

PRODUCTION
    A job is on this lane only when Business Central already says it is
    being built, or the nightly SalesOrderMaster page says a line is still
    in production (status ``Unscheduled``: a production order exists and
    quantity is still left to make). The date is the first real one of:
    production order Due_Date (labeled Build), Ending_Date (Finish),
    the portal sales_orders.scheduled_date when that job is already known
    to be in production (Scheduled), Starting_Date (Start), then the
    sales order's shipment / promised / requested date (Ready).
    ``scheduled_date`` by itself is not a build. It is also the picking
    date, so an order with only that field stays off this lane.
    A production order with no date, and no date on the sales order, stays
    off the board.

PICKUPS and DELIVERIES
    Open sales orders that are not fully shipped and not Draft.
    The shipment method code decides the lane. Shipping agent does the
    same when it is listed in the config. An agent that is not listed does
    not become a delivery. A GUID in shipmentMethodId is not a code and
    does not pick a lane.
    Default method codes are the names this portal already sees
    (``shipmentMethodCode``, including ``TRUCK`` on order reads) plus the
    usual pickup words. They are a starting list, not a confirmed BC setup.
    The date is the first real one of: header shipmentDate, earliest line
    shipmentDate, promisedDeliveryDate, requestedDeliveryDate.
    A date of 0001-01-01 is Business Central's empty date and is ignored.
    orderDate is never a build, pickup, or delivery date.
    Midnight means the order has a day and no time. No clock is invented.
    Destination is the ship-to address. The ship-to name is left off when
    it repeats the customer. No address means the delivery still shows,
    with the destination blank.

Window
    Today plus the next 7 days, shop time America/Regina. Earlier open
    items are overdue. Today with a clock time already passed is late.
    Anything later than the window stays off.

Outlook
    ``OutlookShippingCalendarSource`` is the seam for a later Microsoft
    Graph read of shipping@opendc.ca. It is not called unless the lane
    config turns it on, and the stub returns no events.
"""
from __future__ import annotations

import logging
import re
import threading
import time
from collections import defaultdict
from datetime import date, datetime, time as clock_time, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

SHOP_TZ = ZoneInfo("America/Regina")
FLAG_KEY = "shop_tv_board"
LANE_KEY = "shop_tv_board_lanes"
REFRESH_SECONDS = 60
CACHE_SECONDS = 45

DEFAULT_PICKUP_METHODS = [
    "PICKUP",
    "PICK UP",
    "PICK-UP",
    "PU",
    "WILL CALL",
    "WILLCALL",
    "COLLECT",
    "CUSTOMER PICKUP",
]
DEFAULT_DELIVERY_METHODS = [
    "DELIVERY",
    "TRUCK",
    "FREIGHT",
    "OUR TRUCK",
    "COURIER",
]

_METHOD_FIELDS = (
    "shipmentMethodCode",
    "shipmentMethod",
    "Shipment_Method_Code",
    "Shipment_Method",
)
_AGENT_FIELDS = (
    "shippingAgentCode",
    "shippingAgent",
    "Shipping_Agent_Code",
    "Shipping_Agent_Service_Code",
    "Shipping_Agent",
)
_SHIPMENT_FIELDS = ("shipmentDate", "Shipment_Date")
_PROMISED_FIELDS = ("promisedDeliveryDate", "Promised_Delivery_Date")
_REQUESTED_FIELDS = ("requestedDeliveryDate", "Requested_Delivery_Date")

_GUID = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)

MAPPING_NOTES = [
    "Production: a released, planned, firm planned, or simulated production order, or a SalesOrderMaster line whose status is Unscheduled. Finished production orders stay off.",
    "Production date, first one that exists: Due_Date (Build), ending date (Finish), portal scheduled date (Scheduled, only after the order is already in production), starting date (Start), then the sales order ship / promised / requested date (Ready).",
    "A portal scheduled date alone is not a build. That column is also the picking date.",
    "Pickup vs delivery: shipment method code. Default pickup codes are PICKUP, PICK UP, PICK-UP, PU, WILL CALL, COLLECT, and CUSTOMER PICKUP. Default delivery codes are DELIVERY, TRUCK, FREIGHT, OUR TRUCK, and COURIER.",
    "A shipping agent counts only when its code is listed, or when Settings says any agent means a delivery. Otherwise the agent is ignored.",
    "shipmentMethodId is a GUID on the standard sales order API. A GUID does not choose a lane. The board reads shipmentMethodCode when Business Central sends it.",
    "Outbound date, first one that exists: shipment date (header, else earliest line), promised delivery date, requested delivery date. 0001-01-01 and the order date are not dates.",
    "Midnight is a date with no appointment time. The board does not invent a time.",
    "Destination is the ship-to address. It is blank when Business Central has no ship-to. The customer name is not copied in as an address.",
    "Today and the next 7 days are shown, in America/Regina. Open items before today are overdue. A time earlier today is late. Later than the window stays off.",
    "Outlook calendar for shipping@opendc.ca is stubbed and not read.",
]


def default_lane_config() -> dict:
    return {
        "horizon_days": 7,
        "pickup_shipment_methods": list(DEFAULT_PICKUP_METHODS),
        "delivery_shipment_methods": list(DEFAULT_DELIVERY_METHODS),
        "pickup_shipping_agents": [],
        "delivery_shipping_agents": [],
        "shipping_agent_means_delivery": False,
        "outlook_calendar_enabled": False,
        "production_master_statuses": ["Unscheduled"],
        "production_statuses": ["Planned", "Firm Planned", "Released", "Simulated"],
    }


class OutlookShippingCalendarSource:
    """Seam for shipping@opendc.ca. No Microsoft Graph call yet."""

    id = "outlook_calendar"
    mailbox = "shipping@opendc.ca"

    def status(self) -> dict:
        return {
            "id": self.id,
            "mailbox": self.mailbox,
            "available": False,
            "configured": False,
            "note": (
                "Microsoft Graph for shipping@opendc.ca is not connected. "
                "The board does not read that calendar."
            ),
        }

    def fetch(self) -> dict:
        """No events until Graph is wired. Never invents a pickup or delivery."""
        return {
            **self.status(),
            "orders": [],
            "production_orders": [],
        }


def shop_today(now: Optional[datetime] = None) -> date:
    current = now or datetime.now(SHOP_TZ)
    if current.tzinfo is None:
        current = current.replace(tzinfo=SHOP_TZ)
    else:
        current = current.astimezone(SHOP_TZ)
    return current.date()


def _read_setting(db: Optional[Session], key: str):
    if db is None:
        return None
    nested = None
    try:
        from app.db.models import AppSettings
        nested = db.begin_nested()
        row = db.query(AppSettings).filter(AppSettings.setting_key == key).first()
        value = row.setting_value if row is not None else None
        nested.commit()
        return value
    except Exception:
        logger.warning("Could not read %s; shop TV treats it as unset", key, exc_info=True)
        if nested is not None:
            try:
                nested.rollback()
            except Exception:
                pass
        return None


def _write_setting(db: Session, key: str, value, description: str, user_id: Optional[int]) -> None:
    from app.db.models import AppSettings
    row = db.query(AppSettings).filter(AppSettings.setting_key == key).first()
    if row is None:
        row = AppSettings(
            setting_key=key,
            setting_value=value,
            description=description,
            updated_by=user_id,
        )
        db.add(row)
    else:
        row.setting_value = value
        row.description = description
        row.updated_by = user_id
        row.updated_at = datetime.utcnow()
    db.commit()


def board_enabled(db: Optional[Session]) -> bool:
    """Missing setting, missing table, or anything other than on is off."""
    raw = _read_setting(db, FLAG_KEY)
    if isinstance(raw, dict):
        raw = raw.get("mode") or raw.get("value") or ""
    return str(raw or "").strip().lower() == "on"


def set_board_mode(db: Session, mode: str, user_id: Optional[int] = None) -> str:
    cleaned = str(mode or "").strip().lower()
    if cleaned not in {"off", "on"}:
        raise ValueError("mode must be off or on")
    _write_setting(
        db,
        FLAG_KEY,
        {"mode": cleaned},
        "Shop TV board. Off hides the board route and the nav link.",
        user_id,
    )
    return cleaned


def _as_list(value) -> list:
    if value is None:
        return []
    if isinstance(value, str):
        parts = re.split(r"[\n,]+", value)
        return [part.strip() for part in parts if part.strip()]
    if isinstance(value, (list, tuple)):
        return [str(part).strip() for part in value if str(part).strip()]
    return []


def _clean_codes(value) -> list:
    found = []
    for item in _as_list(value):
        if len(item) > 60 or item in found:
            continue
        found.append(item)
        if len(found) >= 40:
            break
    return found


def lane_config(db: Optional[Session]) -> dict:
    config = default_lane_config()
    raw = _read_setting(db, LANE_KEY)
    if not isinstance(raw, dict):
        return config
    for key, default in default_lane_config().items():
        if key not in raw:
            continue
        if isinstance(default, bool):
            config[key] = bool(raw[key])
        elif key == "horizon_days":
            try:
                config[key] = min(31, max(1, int(raw[key])))
            except (TypeError, ValueError):
                pass
        elif isinstance(default, list):
            config[key] = _clean_codes(raw[key])
    return config


def save_lane_config(db: Session, updates: dict, user_id: Optional[int] = None) -> dict:
    current = lane_config(db)
    for key in (
        "pickup_shipment_methods",
        "delivery_shipment_methods",
        "pickup_shipping_agents",
        "delivery_shipping_agents",
        "production_master_statuses",
        "production_statuses",
    ):
        if key in updates:
            current[key] = _clean_codes(updates[key])
    if "shipping_agent_means_delivery" in updates:
        current["shipping_agent_means_delivery"] = bool(updates["shipping_agent_means_delivery"])
    if "outlook_calendar_enabled" in updates:
        current["outlook_calendar_enabled"] = bool(updates["outlook_calendar_enabled"])
    if "horizon_days" in updates:
        try:
            current["horizon_days"] = min(31, max(1, int(updates["horizon_days"])))
        except (TypeError, ValueError):
            pass
    _write_setting(
        db,
        LANE_KEY,
        current,
        "Shop TV lane rules. Unlisted shipment methods stay off the board.",
        user_id,
    )
    return current


def norm_code(value) -> str:
    if value is None:
        return ""
    return re.sub(r"[\s_\-./]+", "", str(value).strip().upper())


def _code_set(values) -> set:
    return {norm_code(value) for value in values or [] if norm_code(value)}


def _first(row: dict, keys: tuple):
    if not isinstance(row, dict):
        return None
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return None


def _truthy(value) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes"}
    return bool(value)


def parse_when(value):
    """Return (date, time or None). Empty BC dates and blanks return None."""
    if value is None or value is False:
        return None
    if isinstance(value, datetime):
        moment = value
    elif isinstance(value, date):
        if value.year < 1900:
            return None
        return value, None
    else:
        text = str(value).strip()
        if not text or text.startswith("0001") or text.startswith("0000"):
            return None
        iso = text.replace("Z", "+00:00")
        try:
            if "T" in iso or " " in text:
                moment = datetime.fromisoformat(iso)
            else:
                found = date.fromisoformat(text[:10])
                if found.year < 1900:
                    return None
                return found, None
        except ValueError:
            try:
                found = date.fromisoformat(text[:10])
            except ValueError:
                return None
            if found.year < 1900:
                return None
            return found, None
    if moment.tzinfo is not None:
        moment = moment.astimezone(SHOP_TZ)
    if moment.year < 1900:
        return None
    clock = moment.time().replace(microsecond=0)
    if (clock.hour, clock.minute, clock.second) == (0, 0, 0):
        return moment.date(), None
    return moment.date(), clock.replace(second=0)


def _min_when(rows, key):
    found = []
    for row in rows or []:
        parsed = parse_when(row.get(key) if isinstance(row, dict) else None)
        if parsed:
            found.append(parsed)
    if not found:
        return None
    found.sort(key=lambda item: (item[0], item[1] or clock_time.min))
    return found[0]


def _method_code(order: dict) -> str:
    raw = _first(order, _METHOD_FIELDS)
    if raw is None:
        return ""
    text = str(raw).strip()
    if _GUID.match(text):
        return ""
    return text


def _agent_code(order: dict) -> str:
    raw = _first(order, _AGENT_FIELDS)
    if raw is None:
        return ""
    text = str(raw).strip()
    if _GUID.match(text):
        return ""
    return text


def classify_outbound(order: dict, config: dict) -> Optional[str]:
    """Return pickups, deliveries, or None when the method is not configured."""
    method = norm_code(_method_code(order))
    agent = norm_code(_agent_code(order))
    pickups = _code_set(config.get("pickup_shipment_methods"))
    deliveries = _code_set(config.get("delivery_shipment_methods"))
    pickup_agents = _code_set(config.get("pickup_shipping_agents"))
    delivery_agents = _code_set(config.get("delivery_shipping_agents"))
    if method and method in pickups:
        return "pickups"
    if method and method in deliveries:
        return "deliveries"
    if agent and agent in pickup_agents:
        return "pickups"
    if agent and agent in delivery_agents:
        return "deliveries"
    if agent and config.get("shipping_agent_means_delivery") and agent not in pickup_agents:
        return "deliveries"
    return None


def outbound_when(order: dict):
    """First real ship, promised, or requested date. Line shipment is the fallback."""
    for kind, keys in (
        ("shipment", _SHIPMENT_FIELDS),
        ("promised", _PROMISED_FIELDS),
        ("requested", _REQUESTED_FIELDS),
    ):
        parsed = parse_when(_first(order, keys))
        if parsed:
            return parsed[0], parsed[1], kind
    found = []
    for line in order.get("salesOrderLines") or order.get("lines") or []:
        parsed = parse_when(_first(line, _SHIPMENT_FIELDS))
        if parsed:
            found.append(parsed)
    if not found:
        return None, None, None
    found.sort(key=lambda item: (item[0], item[1] or clock_time.min))
    return found[0][0], found[0][1], "shipment"


def customer_name(order: dict) -> str:
    value = _first(order, (
        "customerName",
        "Customer_Name",
        "sellToCustomerName",
        "Sell_to_Customer_Name",
    ))
    return str(value).strip() if value else ""


def order_number(order: dict) -> str:
    value = _first(order, ("number", "No"))
    return str(value).strip() if value else ""


def destination_for(order: dict, customer: str) -> Optional[str]:
    name = _first(order, ("shipToName", "Ship_to_Name"))
    name_text = str(name).strip() if name else ""
    if customer and name_text.lower() == customer.lower():
        name_text = ""
    parts = [name_text]
    for keys in (
        ("shipToAddressLine1", "Ship_to_Address", "shipToAddress"),
        ("shipToAddressLine2", "Ship_to_Address_2"),
        ("shipToCity", "Ship_to_City"),
        ("shipToState", "Ship_to_County", "shipToCounty"),
        ("shipToPostCode", "Ship_to_Post_Code"),
    ):
        value = _first(order, keys)
        text = str(value).strip() if value else ""
        if text:
            parts.append(text)
    joined = ", ".join(part for part in parts if part)
    return joined or None


def _when_label(lane: str, kind: str) -> str:
    if kind == "shipment" and lane == "pickups":
        return "Pickup"
    if kind == "shipment" and lane == "deliveries":
        return "Delivery"
    return {
        "due": "Build",
        "ending": "Finish",
        "starting": "Start",
        "scheduled": "Scheduled",
        "ready": "Ready",
        "promised": "Promised",
        "requested": "Requested",
    }.get(kind, "")


def _status(order: dict) -> str:
    value = _first(order, ("status", "Status"))
    return str(value).strip().lower() if value else ""


def _is_draft(order: dict) -> bool:
    return _status(order) == "draft"


def _is_shipped(order: dict) -> bool:
    return _truthy(order.get("fullyShipped") if "fullyShipped" in order else order.get("Fully_Shipped"))


def _prod_status(row: dict) -> str:
    return str(row.get("status") or row.get("Status") or "").strip().lower()


def _active_production(row: dict, config: dict) -> bool:
    status = _prod_status(row)
    if status in {"finished"}:
        return False
    allowed = {item.strip().lower() for item in config.get("production_statuses") or [] if str(item).strip()}
    if not status:
        return True
    return status in allowed


def _master_in_production(lines, config: dict) -> bool:
    wanted = {
        str(item).strip().lower()
        for item in config.get("production_master_statuses") or []
        if str(item).strip()
    }
    for line in lines or []:
        if str(line.get("Status") or "").strip().lower() in wanted:
            return True
    return False


def _index_master(lines):
    by_so = defaultdict(list)
    by_prod = {}
    for line in lines or []:
        if not isinstance(line, dict):
            continue
        sales_no = str(line.get("Sales_Order_No") or "").strip()
        prod_no = str(line.get("Prodn_Order_No") or "").strip()
        if sales_no:
            by_so[sales_no].append(line)
        if prod_no and sales_no:
            by_prod[prod_no] = sales_no
    return by_so, by_prod


def _day_heading(day: date, today: date) -> dict:
    pretty = f"{day.strftime('%a %b')} {day.day}"
    if day < today:
        label, sublabel, overdue = "Overdue", pretty, True
    elif day == today:
        label, sublabel, overdue = "Today", pretty, False
    else:
        label, sublabel, overdue = pretty, "", False
    return {
        "date": day.isoformat(),
        "label": label,
        "sublabel": sublabel,
        "is_today": day == today,
        "overdue": overdue,
    }


def _group(items: list, today: date, horizon_days: int) -> list:
    by_date = defaultdict(list)
    for item in items:
        by_date[date.fromisoformat(item["date"])].append(item)
    for bucket in by_date.values():
        bucket.sort(key=lambda row: (row.get("time") is None, row.get("time") or "", row.get("order_number") or ""))

    days = []
    for day in sorted(found for found in by_date if found < today):
        heading = _day_heading(day, today)
        heading["items"] = by_date[day]
        days.append(heading)
    today_heading = _day_heading(today, today)
    today_heading["items"] = by_date.get(today, [])
    days.append(today_heading)
    window_end = today + timedelta(days=horizon_days)
    cursor = today + timedelta(days=1)
    while cursor <= window_end:
        if cursor in by_date:
            heading = _day_heading(cursor, today)
            heading["items"] = by_date[cursor]
            days.append(heading)
        cursor += timedelta(days=1)
    return days


def _serialize_when(day: date, clock: Optional[clock_time], today: date, now: Optional[datetime], lane: str, kind: str) -> dict:
    late = False
    if clock is not None and day == today and now is not None:
        current = now.astimezone(SHOP_TZ) if now.tzinfo is not None else now
        late = clock < current.time().replace(microsecond=0, second=0)
    return {
        "date": day.isoformat(),
        "time": clock.strftime("%H:%M") if clock else None,
        "kind": kind,
        "when_label": _when_label(lane, kind),
        "overdue": day < today,
        "late": late and day == today,
    }


def build_board(records: Optional[dict], *, today: date, now: Optional[datetime] = None, config: Optional[dict] = None) -> dict:
    """Group a snapshot. ``records`` is already loaded; this does not call BC."""
    records = records or {}
    config = config or default_lane_config()
    horizon = int(config.get("horizon_days") or 7)
    window_end = today + timedelta(days=horizon)
    sales_orders = [row for row in records.get("sales_orders") or [] if isinstance(row, dict)]
    sales_by_number = {}
    for order in sales_orders:
        number = order_number(order)
        if number:
            sales_by_number[number] = order
    scheduled = records.get("scheduled_dates") or {}
    by_so, by_prod = _index_master(records.get("sales_order_master") or [])

    omitted = {
        "no_date": 0,
        "unmapped_shipment": 0,
        "outside_window": 0,
        "draft_or_shipped": 0,
    }
    production_items = []
    pickup_items = []
    delivery_items = []

    groups = defaultdict(list)
    for row in records.get("production_orders") or []:
        if not isinstance(row, dict) or not _active_production(row, config):
            continue
        prod_no = str(row.get("order_no") or row.get("No") or "").strip()
        sales_no = str(row.get("sales_order_no") or row.get("Sales_Order_No") or "").strip()
        sales_no = sales_no or by_prod.get(prod_no, "")
        key = sales_no or prod_no
        if not key:
            continue
        groups[key].append(row)
    for sales_no, lines in by_so.items():
        if sales_no not in groups and _master_in_production(lines, config):
            groups[sales_no] = []

    for key, prod_rows in groups.items():
        sales = sales_by_number.get(key)
        if sales is not None and _is_shipped(sales):
            omitted["draft_or_shipped"] += 1
            continue
        chosen = None
        kind = None
        for field, label in (("due_date", "due"), ("ending_date", "ending"), ("starting_date", "starting")):
            found = _min_when(prod_rows, field)
            if found:
                chosen, kind = found, label
                break
        if chosen is None:
            scheduled_when = parse_when(scheduled.get(key))
            if scheduled_when and (prod_rows or _master_in_production(by_so.get(key), config)):
                chosen, kind = scheduled_when, "scheduled"
        if chosen is None and sales is not None:
            ready_day, ready_clock, _ready_kind = outbound_when(sales)
            if ready_day is not None:
                chosen, kind = (ready_day, ready_clock), "ready"
        if chosen is None:
            omitted["no_date"] += 1
            continue
        day, clock = chosen
        if day > window_end:
            omitted["outside_window"] += 1
            continue
        descriptions = []
        for row in prod_rows:
            text = str(row.get("description") or row.get("Description") or "").strip()
            if text and text not in descriptions:
                descriptions.append(text)
        if len(prod_rows) > 1:
            detail = f"{len(prod_rows)} jobs"
        elif descriptions:
            detail = descriptions[0]
        else:
            detail = None
        customer = customer_name(sales) if sales else ""
        timing = _serialize_when(day, clock, today, now, "production", kind)
        production_items.append({
            "id": f"production:{key}",
            "lane": "production",
            "order_number": key,
            "customer": customer,
            "detail": detail,
            "destination": None,
            **timing,
        })

    for order in sales_orders:
        number = order_number(order)
        if not number:
            continue
        if _is_draft(order) or _is_shipped(order):
            omitted["draft_or_shipped"] += 1
            continue
        lane = classify_outbound(order, config)
        if lane is None:
            omitted["unmapped_shipment"] += 1
            continue
        day, clock, kind = outbound_when(order)
        if day is None:
            omitted["no_date"] += 1
            continue
        if day > window_end:
            omitted["outside_window"] += 1
            continue
        customer = customer_name(order)
        timing = _serialize_when(day, clock, today, now, lane, kind)
        item = {
            "id": f"{lane}:{number}",
            "lane": lane,
            "order_number": number,
            "customer": customer,
            "detail": None,
            "destination": destination_for(order, customer) if lane == "deliveries" else None,
            **timing,
        }
        if lane == "pickups":
            pickup_items.append(item)
        else:
            delivery_items.append(item)

    generated = now or datetime.now(SHOP_TZ)
    if generated.tzinfo is None:
        generated = generated.replace(tzinfo=SHOP_TZ)
    return {
        "generated_at": generated.astimezone(SHOP_TZ).isoformat(),
        "timezone": "America/Regina",
        "today": today.isoformat(),
        "horizon_days": horizon,
        "window_end": window_end.isoformat(),
        "refresh_seconds": REFRESH_SECONDS,
        "lanes": {
            "production": {"days": _group(production_items, today, horizon)},
            "pickups": {"days": _group(pickup_items, today, horizon)},
            "deliveries": {"days": _group(delivery_items, today, horizon)},
        },
        "omitted": omitted,
        "sources": list(records.get("sources") or []),
        "mapping": MAPPING_NOTES,
    }


def normalize_production_row(item: dict, prod_so: Optional[dict] = None) -> dict:
    order_no = str(item.get("No") or item.get("order_no") or "").strip()
    sales_no = str(item.get("Sales_Order_No") or item.get("sales_order_no") or "").strip()
    if not sales_no and prod_so:
        sales_no = str(prod_so.get(order_no) or "").strip()
    return {
        "order_no": order_no,
        "sales_order_no": sales_no,
        "description": item.get("Description") or item.get("description") or "",
        "status": item.get("Status") or item.get("status") or "",
        "due_date": item.get("Due_Date") if "Due_Date" in item else item.get("due_date"),
        "starting_date": (
            item.get("Starting_Date_Time")
            or item.get("Starting_Date")
            or item.get("starting_date")
        ),
        "ending_date": (
            item.get("Ending_Date_Time")
            or item.get("Ending_Date")
            or item.get("ending_date")
        ),
    }


_cache_lock = threading.Lock()
_cache = {"at": 0.0, "key": None, "records": None}


def clear_board_cache() -> None:
    with _cache_lock:
        _cache["at"] = 0.0
        _cache["key"] = None
        _cache["records"] = None


def _scheduled_dates(db: Optional[Session]) -> dict:
    if db is None:
        return {}
    nested = None
    try:
        from app.db.models import SalesOrder
        nested = db.begin_nested()
        rows = (
            db.query(SalesOrder.bc_order_number, SalesOrder.scheduled_date)
            .filter(SalesOrder.scheduled_date.isnot(None))
            .all()
        )
        nested.commit()
    except Exception:
        logger.warning("Shop TV could not read portal scheduled dates", exc_info=True)
        if nested is not None:
            try:
                nested.rollback()
            except Exception:
                pass
        return {}
    found = {}
    for number, scheduled in rows:
        if number:
            found[str(number)] = scheduled
    return found


def load_board_records(db: Optional[Session], config: Optional[dict] = None, *, use_cache: bool = True) -> dict:
    """Read Business Central. Failures become an empty lane, not a guessed row."""
    config = config or lane_config(db)
    cache_key = (
        bool(config.get("outlook_calendar_enabled")),
        tuple(config.get("production_statuses") or []),
    )
    now_mono = time.monotonic()
    if use_cache:
        with _cache_lock:
            cached = _cache["records"]
            if cached is not None and _cache["key"] == cache_key and now_mono - _cache["at"] < CACHE_SECONDS:
                return cached

    sales = []
    sales_ok = True
    sales_note = None
    try:
        from app.integrations.bc.client import bc_client
        sales = bc_client.get_open_sales_orders_with_lines() or []
    except Exception:
        logger.warning("Shop TV could not read sales orders", exc_info=True)
        sales_ok = False
        sales_note = "Business Central sales orders could not be read."

    production_orders = []
    production_note = None
    master = []
    try:
        from app.services.bc_production_service import ODATA_ENDPOINTS, bc_production_service
        try:
            prod_so = bc_production_service.get_prod_so_map() or {}
        except Exception:
            logger.warning("Shop TV production-to-sales map unavailable", exc_info=True)
            prod_so = {}
        try:
            raw_orders = bc_production_service._make_odata_request_all(
                ODATA_ENDPOINTS["production_orders"]
            ) or []
            production_orders = [normalize_production_row(row, prod_so) for row in raw_orders]
        except Exception:
            logger.warning("Shop TV could not read production orders", exc_info=True)
            production_note = "Production orders could not be read."
        try:
            master = bc_production_service.get_sales_order_master() or []
        except Exception:
            logger.warning("Shop TV could not read SalesOrderMaster", exc_info=True)
            master = []
    except Exception:
        logger.warning("Shop TV production service unavailable", exc_info=True)
        production_note = "Production orders could not be read."

    outlook = OutlookShippingCalendarSource()
    outlook_state = outlook.status()
    if config.get("outlook_calendar_enabled"):
        fetched = outlook.fetch()
        outlook_state = {key: fetched.get(key) for key in ("id", "mailbox", "available", "configured", "note")}
        if fetched.get("available"):
            sales = list(sales) + list(fetched.get("orders") or [])
            production_orders = list(production_orders) + [
                normalize_production_row(row) for row in fetched.get("production_orders") or []
            ]

    records = {
        "sales_orders": sales,
        "production_orders": production_orders,
        "sales_order_master": master,
        "scheduled_dates": _scheduled_dates(db),
        "sources": [
            {"id": "business_central", "available": sales_ok, "note": sales_note},
            {
                "id": "business_central_production",
                "available": production_note is None,
                "note": production_note,
            },
            outlook_state,
        ],
    }
    if use_cache and sales_ok:
        with _cache_lock:
            _cache["at"] = now_mono
            _cache["key"] = cache_key
            _cache["records"] = records
    return records


def assemble_board(db: Optional[Session], now: Optional[datetime] = None) -> dict:
    config = lane_config(db)
    current = now or datetime.now(SHOP_TZ)
    records = load_board_records(db, config)
    return build_board(records, today=shop_today(current), now=current, config=config)
