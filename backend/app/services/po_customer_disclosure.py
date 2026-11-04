"""Which vendors may see the sales-order customer on a purchase order.

Open Distribution, Joey: a purchase order and the email that carries it
must not show the customer to the vendor, except Elton Manufacturing,
Upwardor, and Nice/Micanan. Customer info is the customer name, the
customer's own PO (the sales order's external document number), the job
or site name, and the customer's ship-to address or phone.

Every other vendor's SO link is only "Built from SO-xxxxxx". Our sales
order number is fine to show.

Match is the vendor number (exact, ignoring case) or the vendor name,
using the same whole-word / phrase rules as the lead-time table: ``NICE``
matches "Nice Canada", not "Bernice".

Write paths reject the text before Business Central or Outlook is touched.
A warning that still saved the line would print on the BC PDF. Draft-PO
validate is read-only, so it flags a leak that is already on the PO.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Callable, Iterable, List, Optional, Sequence

logger = logging.getLogger(__name__)

_SO_RE = re.compile(r"\bSO-\d+\b", re.IGNORECASE)
_YEAR_RE = re.compile(r"(?:19|20)\d{2}")
# "cust PO", "customer PO", "customer's P.O.", "customer purchase order".
_CUST_PO_RE = re.compile(
    r"\b(?:customer(?:'s)?|cust\.?)\s+(?:purchase\s+order|p\.?\s*o\.?)\b",
    re.IGNORECASE,
)

# Single-word names that also appear on door lines. A customer named
# "Black" still matches a comment that is only that word. It does not
# match the color inside "(1) 10'0\" x 8'0\" TX450, BLACK".
_SINGLE_WORD_STOPLIST = frozenset({
    "ALMOND",
    "ANODIZED",
    "BLACK",
    "BOX",
    "BRONZE",
    "BROWN",
    "CHOCOLATE",
    "CLEAR",
    "COMMERCIAL",
    "DOOR",
    "DOORS",
    "FREIGHT",
    "GLASS",
    "GREEN",
    "HARDWARE",
    "LIFT",
    "PANEL",
    "POLYCARBONATE",
    "RESIDENTIAL",
    "SANDSTONE",
    "SECTION",
    "STANDARD",
    "STD",
    "TRACK",
    "WHITE",
})


@dataclass(frozen=True)
class _AllowlistVendor:
    key: str
    vendor_numbers: tuple
    name_contains: tuple


# First match wins. Nice's BC vendor number is not on the lead-time row
# yet; "NICE" is accepted as a number so a card numbered that way is
# covered, and the name needles cover Nice Canada and Micanan.
_ALLOWLIST = (
    _AllowlistVendor("upwardor", ("UPW",), ("UPWARDOR", "UPW")),
    _AllowlistVendor("elton", ("ELT",), ("ELTON", "ELT")),
    _AllowlistVendor(
        "nice_micanan",
        ("NICE",),
        ("NICE CANADA", "MICANAN", "NICE"),
    ),
)

_KIND_LABELS = (
    ("customer_name", "the customer name"),
    ("external_document", "the customer PO / external document number"),
    ("ship_to", "the job, site, or ship-to"),
    ("customer_po_phrase", 'a "customer PO" phrase'),
)


class CustomerDisclosureError(ValueError):
    """The text would show customer info to a vendor who must not see it."""

    def __init__(self, kinds: Sequence[str]):
        self.kinds = tuple(dict.fromkeys(kinds))
        labels = [label for key, label in _KIND_LABELS if key in self.kinds]
        listed = ", ".join(labels) if labels else "customer information"
        super().__init__(
            "This vendor cannot see the customer's name, PO, job, or ship-to. "
            "Only Elton, Upwardor, and Nice/Micanan may. "
            f"The text includes {listed}."
        )


@dataclass(frozen=True)
class CustomerIdentity:
    """Customer fields from one sales order. Empty strings are ignored."""

    customer_name: str = ""
    external_document: str = ""
    ship_to_names: tuple = ()
    ship_to_addresses: tuple = ()
    phones: tuple = ()

    @classmethod
    def from_sales_order(cls, so: Optional[dict]) -> "CustomerIdentity":
        if not isinstance(so, dict):
            return cls()
        names = _unique(
            so.get("shipToName"),
            so.get("shipToContact"),
        )
        addresses = _unique(
            so.get("shipToAddressLine1"),
            so.get("shipToAddressLine2"),
            so.get("shipToPostCode"),
        )
        phones = _unique(so.get("phoneNumber"), so.get("mobilePhoneNumber"))
        return cls(
            customer_name=str(so.get("customerName") or "").strip(),
            external_document=str(so.get("externalDocumentNumber") or "").strip(),
            ship_to_names=tuple(names),
            ship_to_addresses=tuple(addresses),
            phones=tuple(phones),
        )


def vendor_may_see_customer_info(vendor_no: str = "", vendor_name: str = "") -> bool:
    """True for Elton, Upwardor, and Nice/Micanan. Everyone else may not."""
    number = (vendor_no or "").strip().upper()
    if number:
        for vendor in _ALLOWLIST:
            if number in {item.upper() for item in vendor.vendor_numbers}:
                return True
    name = _norm(vendor_name)
    if name:
        for vendor in _ALLOWLIST:
            if any(_name_matches(name, needle) for needle in vendor.name_contains):
                return True
    return False


def sales_order_numbers_from_texts(texts: Iterable[str]) -> List[str]:
    """SO-###### mentions, in first-seen order."""
    found: List[str] = []
    seen = set()
    for text in texts:
        for match in _SO_RE.finditer(text or ""):
            number = match.group(0).upper()
            if number not in seen:
                seen.add(number)
                found.append(number)
    return found


def lookup_sales_order(bc, number: str) -> Optional[dict]:
    """Load one sales order. A missing method or a BC error yields None."""
    fn = getattr(bc, "get_sales_order_by_number", None)
    if not callable(fn):
        return None
    try:
        row = fn(number)
    except Exception:
        logger.warning(
            "Sales order %s could not be loaded for the customer-disclosure check",
            number,
            exc_info=True,
        )
        return None
    return row if isinstance(row, dict) else None


def load_customer_identities(so_numbers: Sequence[str], lookup: Callable[[str], Optional[dict]]) -> List[CustomerIdentity]:
    identities: List[CustomerIdentity] = []
    seen = set()
    for number in so_numbers:
        key = (number or "").strip().upper()
        if not key or key in seen:
            continue
        seen.add(key)
        identities.append(CustomerIdentity.from_sales_order(lookup(key)))
    return identities


def find_customer_leaks(text: str, identities: Sequence[CustomerIdentity] = ()) -> List[str]:
    """Kind codes for customer info in ``text``. Empty when the text is safe.

    Our sales-order number is not customer info. A comment that is only
    "Built from SO-001299 …" does not match.
    """
    raw = text or ""
    if not raw.strip():
        return []
    kinds: List[str] = []
    if _CUST_PO_RE.search(raw):
        kinds.append("customer_po_phrase")
    for identity in identities:
        if _name_in_text(raw, identity.customer_name):
            kinds.append("customer_name")
        if _document_in_text(raw, identity.external_document):
            kinds.append("external_document")
        if any(_name_in_text(raw, name) for name in identity.ship_to_names):
            kinds.append("ship_to")
        if any(_address_in_text(raw, line) for line in identity.ship_to_addresses):
            kinds.append("ship_to")
        if any(_phone_in_text(raw, phone) for phone in identity.phones):
            kinds.append("ship_to")
    return list(dict.fromkeys(kinds))


def guard_vendor_texts(
    vendor_no: Optional[str],
    vendor_name: Optional[str],
    texts: Iterable[str],
    so_numbers: Sequence[str] = (),
    *,
    lookup: Optional[Callable[[str], Optional[dict]]] = None,
) -> None:
    """Raise when any text would show customer info to this vendor.

    Allowlisted vendors return immediately. Sales orders are loaded only
    when the vendor is not allowlisted and at least one SO number was found.
    """
    if vendor_may_see_customer_info(vendor_no or "", vendor_name or ""):
        return
    pending = [str(text) for text in texts if text and str(text).strip()]
    if not pending:
        return
    identities: List[CustomerIdentity] = []
    if so_numbers and lookup is not None:
        identities = load_customer_identities(so_numbers, lookup)
    kinds: List[str] = []
    for text in pending:
        kinds.extend(find_customer_leaks(text, identities))
    if kinds:
        logger.info(
            "Blocked customer info on a purchase order for vendor %s (%s)",
            (vendor_no or vendor_name or "unknown"),
            ", ".join(dict.fromkeys(kinds)),
        )
        raise CustomerDisclosureError(kinds)


def _norm(text: Optional[str]) -> str:
    cleaned = re.sub(r"[^A-Z0-9]+", " ", (text or "").upper())
    return " ".join(cleaned.split())


def _name_matches(normalized_name: str, needle: str) -> bool:
    needle = _norm(needle)
    if not needle or not normalized_name:
        return False
    if " " in needle:
        return needle in normalized_name
    return f" {needle} " in f" {normalized_name} "


def _unique(*values) -> List[str]:
    out: List[str] = []
    seen = set()
    for value in values:
        text = " ".join(str(value or "").split())
        key = text.casefold()
        if text and key not in seen:
            seen.add(key)
            out.append(text)
    return out


def _boundary_pattern(marker: str) -> re.Pattern:
    return re.compile(
        rf"(?<![A-Za-z0-9]){re.escape(marker)}(?![A-Za-z0-9])",
        re.IGNORECASE,
    )


def _is_our_sales_order_number(marker: str) -> bool:
    return bool(re.fullmatch(r"SO-\d+", marker.strip(), re.IGNORECASE))


def _name_in_text(text: str, name: str) -> bool:
    """True when ``name`` appears as its own words.

    A one-word door color (``Black``) matches a comment that is only that
    word. It does not match the color on a door header. Any other name of
    at least four characters matches inside a sentence: ``Acme`` in
    "ship to Acme", and ``Prairie Door Co`` in a longer note.
    """
    cleaned = " ".join((name or "").split())
    if len(cleaned) < 4 or _is_our_sales_order_number(cleaned):
        return False
    exact = text.strip().casefold() == cleaned.casefold()
    if " " not in cleaned and cleaned.upper() in _SINGLE_WORD_STOPLIST and not exact:
        return False
    return _boundary_pattern(cleaned).search(text) is not None


def _document_in_text(text: str, document: str) -> bool:
    cleaned = " ".join((document or "").split())
    if len(cleaned) < 3 or _is_our_sales_order_number(cleaned):
        return False
    if _YEAR_RE.fullmatch(cleaned):
        return False
    if cleaned.upper() in _SINGLE_WORD_STOPLIST and not re.search(r"\d", cleaned):
        return False
    return _boundary_pattern(cleaned).search(text) is not None


def _address_in_text(text: str, line: str) -> bool:
    cleaned = " ".join((line or "").split())
    if len(cleaned) < 6 or _is_our_sales_order_number(cleaned):
        return False
    if _YEAR_RE.fullmatch(cleaned):
        return False
    return _boundary_pattern(cleaned).search(text) is not None


def _phone_digits(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def _phone_in_text(text: str, phone: str) -> bool:
    digits = _phone_digits(phone)
    if len(digits) < 10:
        return False
    hay = _phone_digits(text)
    if not hay:
        return False
    if digits in hay:
        return True
    if digits.startswith("1") and len(digits) == 11 and digits[1:] in hay:
        return True
    if len(digits) == 10 and f"1{digits}" in hay:
        return True
    return False
