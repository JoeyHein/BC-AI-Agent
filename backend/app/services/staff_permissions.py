"""Staff permission presets and the one check every staff route uses.

Customer portal routes and the external Service.AI API are not staff routes.
A staff service key (osk_) is not checked here: its allow-list is the gate,
and that list is unchanged.

Stored JSON on the user overrides the preset. NULL means "use the preset".
"""
from __future__ import annotations

import json
from typing import Optional

from fastapi import HTTPException, status

from app.db.models import UserRole

# Kept in sync with staff_service_keys_service.SERVICE_USER_EMAIL.
SERVICE_USER_EMAIL = "automation@keys.opendc.internal"
OWNER_EMAIL = "joey@opendc.ca"

# key, group, short label. Order is the order shown on the Users page.
PERMISSION_SPEC = (
    ("quotes.view", "Quotes", "View"),
    ("quotes.edit", "Quotes", "Create and update"),
    ("sales_orders.view", "Sales orders", "View"),
    ("sales_orders.edit", "Sales orders", "Update and ship"),
    ("purchase_orders.view", "Purchase orders", "View"),
    ("purchase_orders.edit", "Purchase orders", "Edit drafts, vendor acknowledgements, and invoices"),
    ("purchase_orders.send", "Purchase orders", "Create and send"),
    ("configurator.use", "Configurator", "Use the door configurator"),
    ("pricing.view", "Pricing", "See selling prices"),
    ("pricing.edit", "Pricing", "See cost and margin, and edit pricing rules"),
    ("receiving.view", "Receiving", "View incoming draft purchase orders"),
    ("receiving.edit", "Receiving", "Set the warehouse date on a draft purchase order"),
    ("inventory.view", "Inventory", "View"),
    ("inventory.edit", "Inventory", "Edit the catalog and inventory records"),
    ("production.view", "Production", "View production and cut work orders"),
    ("production.edit", "Production", "Schedule production and complete cut work"),
    ("customers.view", "Customers", "View"),
    ("customers.edit", "Customers", "Edit"),
    ("users.view", "Users", "View staff and the access log"),
    ("users.manage", "Users", "Invite, change access, and manage service keys"),
    ("settings.view", "Settings", "View"),
    ("settings.edit", "Settings", "Edit"),
)

ALL_KEYS = tuple(item[0] for item in PERMISSION_SPEC)

_PRESET_COPY = (
    ("owner", "Owner", "Everything, including users, settings, pricing, and service keys."),
    ("admin", "Admin", "Same access as Owner. Only an Owner can change another Owner."),
    ("manager", "Manager", "Quotes, sales orders, purchase orders (create and send), receiving, customers, and the door configurator. Sees selling prices. Cost, margin, and pricing rules need the pricing edit grant."),
    ("sales", "Sales", "Quotes, sales orders, customers, and the door configurator. Sees selling prices. Can view inventory."),
    ("purchasing", "Purchasing", "Purchase orders, vendor acknowledgements, invoice matching, and receiving. Can view sales orders and inventory."),
    ("warehouse", "Warehouse / Production", "Receiving, production, and cut work orders. Can view inventory."),
    ("viewer", "Viewer", "Read-only quotes, sales orders, customers, inventory, and production."),
    ("configurator", "Configurator only", "Door configurator and selling prices. Quotes list, orders, purchasing, the customers page, inventory, cost, and admin stay off."),
)


def _blank() -> dict:
    return {key: False for key in ALL_KEYS}


def imply(perms: dict) -> dict:
    """Edit, send, and manage include view. Send does not include edit.

    configurator.use is its own switch. It is not a view bit, so turning on
    another area does not grant the configurator, and the configurator does
    not grant that area.
    """
    out = {key: bool(perms.get(key)) for key in ALL_KEYS}
    for key in ALL_KEYS:
        area, _, level = key.partition(".")
        if level != "view":
            continue
        if out.get(f"{area}.edit") or out.get(f"{area}.manage") or out.get(f"{area}.send"):
            out[key] = True
    return out


def _grant(keys: tuple) -> dict:
    base = _blank()
    for key in keys:
        base[key] = True
    return imply(base)


_FULL = imply({key: True for key in ALL_KEYS})

PRESETS = {
    "owner": dict(_FULL),
    "admin": dict(_FULL),
    "manager": _grant((
        "quotes.view", "quotes.edit",
        "sales_orders.view", "sales_orders.edit",
        "purchase_orders.view", "purchase_orders.edit", "purchase_orders.send",
        "configurator.use",
        "pricing.view",
        "receiving.view", "receiving.edit",
        "inventory.view",
        "production.view",
        "customers.view", "customers.edit",
    )),
    "sales": _grant((
        "quotes.view", "quotes.edit",
        "sales_orders.view", "sales_orders.edit",
        "customers.view", "customers.edit",
        "inventory.view",
        "configurator.use",
        "pricing.view",
    )),
    "purchasing": _grant((
        "purchase_orders.view", "purchase_orders.edit", "purchase_orders.send",
        "receiving.view", "receiving.edit",
        "inventory.view",
        "sales_orders.view",
    )),
    "warehouse": _grant((
        "receiving.view", "receiving.edit",
        "production.view", "production.edit",
        "inventory.view",
    )),
    "viewer": _grant((
        "quotes.view",
        "sales_orders.view",
        "customers.view",
        "inventory.view",
        "production.view",
    )),
    "configurator": _grant((
        "configurator.use",
        "pricing.view",
    )),
}
# Old reviewer rows, until the migration moves them to manager.
PRESETS["reviewer"] = dict(PRESETS["manager"])

ASSIGNABLE_ROLES = (
    "owner", "admin", "manager", "sales", "purchasing", "warehouse", "viewer", "configurator",
)


def legacy_reviewer_permissions() -> dict:
    """What a reviewer could already open, including screens that only checked 'is staff'."""
    perms = dict(PRESETS["manager"])
    perms["inventory.edit"] = True
    perms["production.edit"] = True
    perms["settings.view"] = True
    perms["settings.edit"] = True
    perms["pricing.edit"] = True
    perms["configurator.use"] = True
    return imply(perms)


def legacy_viewer_permissions() -> dict:
    """Screens a viewer could already open. Purchasing stays off.

    The purchasing page was already hidden from viewers. The API used to let
    them through; that hole is closed for existing viewers as well as new ones.
    Settings and pricing stay on because those pages were open to every login.
    """
    perms = dict(PRESETS["viewer"])
    for key in (
        "quotes.edit",
        "sales_orders.edit",
        "inventory.edit",
        "production.edit",
        "settings.view",
        "settings.edit",
        "pricing.view",
        "pricing.edit",
        "configurator.use",
    ):
        perms[key] = True
    return imply(perms)


def role_name(user) -> str:
    role = getattr(user, "role", None)
    if role is None:
        return "viewer"
    if isinstance(role, UserRole):
        return role.value
    text = str(role).strip()
    if "." in text:
        text = text.split(".")[-1]
    text = text.lower()
    if text in PRESETS or text in ASSIGNABLE_ROLES:
        return text
    return "viewer"


def _is_service(user) -> bool:
    if (getattr(user, "user_type", None) or "").upper() == "SERVICE":
        return True
    return (getattr(user, "email", None) or "").lower() == SERVICE_USER_EMAIL


def _is_customer(user) -> bool:
    return (getattr(user, "user_type", None) or "").upper() == "CUSTOMER"


def stored_permissions(user) -> Optional[dict]:
    raw = getattr(user, "permissions", None)
    if raw is None or raw == "":
        return None
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return None
    if not isinstance(raw, dict) or not raw:
        return None
    return raw


def effective_permissions(user) -> dict:
    if _is_service(user):
        return dict(_FULL)
    base = dict(PRESETS.get(role_name(user), PRESETS["viewer"]))
    raw = stored_permissions(user)
    if raw:
        for key in ALL_KEYS:
            if key in raw:
                base[key] = bool(raw[key])
    return imply(base)


def permissions_are_custom(user) -> bool:
    raw = stored_permissions(user)
    if not raw or _is_service(user):
        return False
    preset = PRESETS.get(role_name(user), PRESETS["viewer"])
    return effective_permissions(user) != preset


def has_permission(user, key: str) -> bool:
    if _is_service(user):
        return True
    return bool(effective_permissions(user).get(key))


_COST_KEYS = {
    "unit_cost",
    "cost",
    "margin",
    "gm",
    "target_gm",
    "discount_pct",
    "posting_group",
    "price_multiplier",
    "bc_price_group",
    "pricing_tier",
}
_SELLING_KEYS = {"unit_price", "line_total", "unitPrice", "netAmount"}


def _strip_keys(value, keys: set):
    if not isinstance(value, list):
        return value
    cleaned = []
    for item in value:
        if isinstance(item, dict):
            cleaned.append({k: v for k, v in item.items() if k not in keys})
        else:
            cleaned.append(item)
    return cleaned


def redact_configurator_quote(user, payload: dict) -> dict:
    """Selling prices need pricing.view. Cost and margin need pricing.edit."""
    if not isinstance(payload, dict):
        return payload
    see_prices = has_permission(user, "pricing.view")
    see_cost = has_permission(user, "pricing.edit")
    out = dict(payload)
    message = out.get("message")
    if isinstance(message, str) and not see_cost:
        out["message"] = " | ".join(
            part for part in message.split(" | ") if not part.startswith("Volume pricing:")
        )
    data = out.get("data")
    if not isinstance(data, dict):
        return out
    data = dict(data)
    if not see_cost:
        data.pop("escalating_margin", None)
        freight = data.get("freight")
        if isinstance(freight, dict):
            cleaned = {k: v for k, v in freight.items() if k != "rate"}
            cleaned["description"] = "Pickup - No Freight" if freight.get("skip") else "Freight"
            data["freight"] = cleaned
        data["line_pricing"] = _strip_keys(data.get("line_pricing"), _COST_KEYS)
        data["parts_summary"] = _strip_keys(data.get("parts_summary"), _COST_KEYS)
    if not see_prices:
        data.pop("pricing", None)
        data.pop("line_pricing", None)
        data.pop("freight", None)
        data.pop("escalating_margin", None)
        data["parts_summary"] = _strip_keys(data.get("parts_summary"), _SELLING_KEYS)
    out["data"] = data
    return out


def redact_customer_search(user, row: dict) -> dict:
    """Company name for the configurator picker. Directory and price group stay gated."""
    directory = has_permission(user, "customers.view")
    cost = has_permission(user, "pricing.edit")
    return {
        "bc_customer_id": row.get("bc_customer_id"),
        "company_name": row.get("company_name"),
        "already_linked": bool(row.get("already_linked")),
        "is_home_builder": bool(row.get("is_home_builder")),
        "contact_name": row.get("contact_name") if directory else None,
        "email": row.get("email") if directory else None,
        "phone": row.get("phone") if directory else None,
        "customer_number": row.get("customer_number") if directory else None,
        "bc_price_group": row.get("bc_price_group") if cost else None,
        "pricing_tier": row.get("pricing_tier") if cost else None,
    }


def normalize_permissions(raw: Optional[dict]) -> dict:
    if not isinstance(raw, dict):
        raise ValueError("permissions must be an object of true/false flags")
    unknown = [key for key in raw if key not in ALL_KEYS]
    if unknown:
        raise ValueError("Unknown permission: " + ", ".join(sorted(unknown)))
    return imply({key: bool(raw.get(key)) for key in ALL_KEYS})


def permissions_for_storage(role: str, raw: Optional[dict]) -> Optional[dict]:
    """NULL when the flags match the preset, so the preset stays the source."""
    if raw is None:
        return None
    normalized = normalize_permissions(raw)
    preset = PRESETS.get(role, PRESETS["viewer"])
    if normalized == preset:
        return None
    return normalized


def catalog() -> dict:
    presets = []
    for preset_id, label, description in _PRESET_COPY:
        presets.append({
            "id": preset_id,
            "label": label,
            "description": description,
            "owner_only": preset_id == "owner",
            "permissions": dict(PRESETS[preset_id]),
        })
    return {
        "presets": presets,
        "permissions": [
            {"key": key, "group": group, "label": label}
            for key, group, label in PERMISSION_SPEC
        ],
    }


def serialize_user(user) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "role": role_name(user),
        "is_active": bool(user.is_active),
        "created_at": user.created_at,
        "last_login_at": user.last_login_at,
        "permissions": effective_permissions(user),
        "permissions_custom": permissions_are_custom(user),
        "invite_pending": bool(getattr(user, "invite_pending", False)),
        "user_type": getattr(user, "user_type", None),
    }


def plan_backfill(email: Optional[str], role: Optional[str], user_type: Optional[str], permissions) -> Optional[tuple]:
    """Return (db enum name, permissions or None) when this row should change.

    Customers, the automation identity, and rows that already have a
    permission override are left alone. Joey's admin login becomes Owner.
    Other admins stay Admin (full access). Reviewers become Managers and
    keep the extra screens they could already open. Viewers keep those
    screens too, except purchasing.
    """
    if permissions:
        return None
    kind = (user_type or "INTERNAL").upper()
    if kind in ("CUSTOMER", "SERVICE"):
        return None
    if (email or "").lower() == SERVICE_USER_EMAIL:
        return None
    role_name_db = (role or "").upper()
    if role_name_db == "ADMIN" and (email or "").lower() == OWNER_EMAIL:
        return ("OWNER", None)
    if role_name_db == "REVIEWER":
        return ("MANAGER", legacy_reviewer_permissions())
    if role_name_db == "VIEWER":
        return ("VIEWER", legacy_viewer_permissions())
    return None


_SAFE = {"GET", "HEAD"}


def normalize_path(path: str) -> str:
    path = (path or "").split("?", 1)[0]
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")
    return path


def _level(method: str, view_key: str, write_key: str):
    if method in _SAFE:
        return ("perm", view_key)
    return ("perm", write_key)


def _under(path: str, prefix: str) -> bool:
    return path == prefix or path.startswith(prefix + "/")


def permission_for(method: str, path: str):
    """What this request needs.

    None: not a staff route (customer, public widget math, external API, health).
    ("staff",): any active staff login.
    ("perm", key): that permission. Edit implies view.
    ("any", key, ...): one of those permissions.
    """
    method = (method or "GET").upper()
    if method == "OPTIONS":
        return None
    path = normalize_path(path)

    if (method, path) in {
        ("POST", "/api/auth/login"),
        ("POST", "/api/auth/register"),
        ("POST", "/api/auth/setup"),
        ("POST", "/api/auth/reset-password"),
    }:
        return None
    if path.startswith("/api/email-connections/oauth/callback"):
        return None

    if path.startswith("/api/door-config/load-quote/"):
        return ("any", "quotes.view", "configurator.use")
    if path == "/api/door-config/generate-quote":
        return ("any", "quotes.edit", "configurator.use")
    if path.startswith("/api/door-config"):
        return None

    if (
        path.startswith("/api/customer")
        or path.startswith("/api/public")
        or path.startswith("/api/part-finder")
        or path.startswith("/api/integrations")
        or path.startswith("/api/external/")
        or path == "/api/external"
        or path in ("/", "/health", "/docs", "/redoc", "/openapi.json")
        or path.startswith("/debug")
        or path.startswith("/test-register")
    ):
        return None

    if path in ("/api/auth/me", "/api/auth/logout"):
        return ("staff",)
    if path == "/api/auth/permission-catalog" or _under(path, "/api/auth/access-audit"):
        return ("perm", "users.view") if method in _SAFE else ("perm", "users.manage")
    if _under(path, "/api/auth/users") or path == "/api/auth/users":
        return ("perm", "users.view") if method in _SAFE else ("perm", "users.manage")

    if _under(path, "/api/external-keys") or _under(path, "/api/admin/service-keys"):
        return ("perm", "users.manage")
    if path.startswith("/api/email-agent"):
        return ("perm", "users.manage")

    if path.startswith("/api/admin/purchasing"):
        return _purchasing(method, path)
    if path.startswith("/api/admin/invoices") or path.startswith("/api/admin/vendor-acks") or path.startswith("/api/admin/po-agent"):
        return _level(method, "purchase_orders.view", "purchase_orders.edit")
    if path.startswith("/api/admin/catalog") or path.startswith("/api/admin/inventory-agent"):
        return _level(method, "inventory.view", "inventory.edit")
    if path.startswith("/api/admin/pricing-diagnostic"):
        return ("perm", "pricing.edit")
    if (
        path.startswith("/api/admin/quote-review")
        or path.startswith("/api/admin/quotes")
        or path.startswith("/api/admin/quote-leads")
    ):
        return _level(method, "quotes.view", "quotes.edit")
    if path == "/api/admin/customers/bc-customers" and method in _SAFE:
        return ("any", "customers.view", "configurator.use")
    if path.startswith("/api/admin/customers") or path.startswith("/api/admin/install-referrals"):
        return _level(method, "customers.view", "customers.edit")

    if path.startswith("/api/quotes"):
        return _level(method, "quotes.view", "quotes.edit")
    if path.startswith("/api/orders"):
        if "/mark-viewed" in path:
            return ("perm", "sales_orders.view")
        if "/bc/quotes" in path:
            return _level(method, "quotes.view", "quotes.edit")
        return _level(method, "sales_orders.view", "sales_orders.edit")
    if path.startswith("/api/bc"):
        return _bc(method, path)
    if path.startswith("/api/inventory") or _under(path, "/inventory") or path == "/inventory":
        if "check-availability" in path:
            return ("perm", "inventory.view")
        return _level(method, "inventory.view", "inventory.edit")
    if path.startswith("/production"):
        return _level(method, "production.view", "production.edit")
    if path.startswith("/api/settings"):
        # Selling-price view is not enough. These screens show margins and rates.
        if any(part in path for part in ("pricing", "freight", "bc-group")):
            return ("perm", "pricing.edit")
        return _level(method, "settings.view", "settings.edit")
    if path.startswith("/api/metrics"):
        return _metrics(path)
    if path.startswith("/api/kpi"):
        if method not in _SAFE:
            return ("perm", "users.manage")
        return ("any", "quotes.view", "sales_orders.view", "purchase_orders.view", "inventory.view")
    if path.startswith("/api/analytics"):
        return ("any", "quotes.view", "sales_orders.view")
    if path.startswith("/api/email-connections"):
        if method in _SAFE and "oauth/start" not in path:
            return ("perm", "settings.view")
        return ("perm", "settings.edit")
    if path.startswith("/api/email-feedback"):
        return _level(method, "quotes.view", "quotes.edit")
    if path.startswith("/api/chat"):
        return (
            "any",
            "quotes.view",
            "sales_orders.view",
            "purchase_orders.view",
            "inventory.view",
            "production.view",
            "customers.view",
        )

    staff_prefixes = (
        "/api/admin",
        "/api/auth",
        "/api/email-connections",
        "/api/email-feedback",
        "/api/email-agent",
        "/api/quotes",
        "/api/orders",
        "/api/analytics",
        "/api/bc",
        "/api/settings",
        "/api/metrics",
        "/api/kpi",
        "/api/chat",
        "/api/external-keys",
    )
    if any(_under(path, prefix) or path == prefix for prefix in staff_prefixes):
        return ("perm", "users.manage")
    return None


def _purchasing(method: str, path: str):
    if "/cut-work-orders" in path or "/cut-rules" in path:
        return _level(method, "production.view", "production.edit")
    if method in _SAFE:
        if "/draft-pos" in path:
            return ("any", "purchase_orders.view", "receiving.view")
        return ("perm", "purchase_orders.view")
    if path.endswith("/requested-receipt") or path.endswith("/requested-receipt/backfill"):
        return ("any", "purchase_orders.edit", "receiving.edit")
    send_suffixes = (
        "/generate-po",
        "/send-report",
        "/planning-workbook/run",
        "/brief/run",
        "/auto-po/run",
        "/auto-po/seed",
        "/review-draft",
    )
    if any(path.endswith(suffix) for suffix in send_suffixes):
        return ("perm", "purchase_orders.send")
    if path.endswith("/so-complete-po"):
        return ("perm", "purchase_orders.send")
    return ("perm", "purchase_orders.edit")


def _bc(method: str, path: str):
    if method not in _SAFE:
        return ("perm", "users.manage")
    if "/sales-quotes" in path:
        return ("perm", "quotes.view")
    if "/sales-orders" in path:
        return ("perm", "sales_orders.view")
    if "/purchase-orders" in path or "/purchase-invoices" in path or path.startswith("/api/bc/vendors"):
        return ("perm", "purchase_orders.view")
    if "/customers" in path:
        return ("perm", "customers.view")
    if "/items" in path:
        return ("perm", "inventory.view")
    if "/sales-invoices" in path:
        return ("perm", "sales_orders.view")
    if "/purchase-price-lines" in path:
        return ("perm", "pricing.edit")
    if "price" in path:
        return ("perm", "pricing.view")
    return ("perm", "users.manage")


def _metrics(path: str):
    if path == "/api/metrics/executive":
        return ("perm", "users.manage")
    if path == "/api/metrics/operations":
        return ("any", "quotes.edit", "sales_orders.edit", "purchase_orders.view")
    if path == "/api/metrics/quoting":
        return ("perm", "quotes.view")
    if path in ("/api/metrics/sales-analytics", "/api/metrics/order-age", "/api/metrics/shipping"):
        return ("perm", "sales_orders.view")
    if path.startswith("/api/metrics/customer/"):
        return ("perm", "customers.view")
    return ("perm", "users.manage")


def _met(user, requirement) -> bool:
    if requirement is None or requirement[0] == "staff":
        return True
    if requirement[0] == "perm":
        return has_permission(user, requirement[1])
    if requirement[0] == "any":
        return any(has_permission(user, key) for key in requirement[1:])
    return False


def denial_detail(requirement) -> str:
    keys = requirement[1:] if requirement else ()
    if any(str(key).startswith("users.") for key in keys):
        return "Admin access required"
    return "You do not have permission to do that"


def enforce_staff_permission(request, user) -> None:
    """Raise 403 when this staff login cannot call this route.

    Service keys return immediately. Their allow-list already ran.
    """
    if user is None or _is_service(user):
        return
    requirement = permission_for(getattr(request, "method", "GET"), str(request.url.path))
    if requirement is None:
        return
    if _is_customer(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Staff access required",
        )
    if not _met(user, requirement):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=denial_detail(requirement),
        )
