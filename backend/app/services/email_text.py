"""The new part of an email, without the quoted thread underneath it.

Approval detection and the explicit-value scanner both use this so an
older message ("On Tue, Pat wrote:" or lines starting with ">") cannot
approve a quote or set a colour.
"""
from __future__ import annotations

import re
from typing import Optional

_QUOTE_LINE = re.compile(r"^\s*>")
_WROTE = re.compile(r"^On .+ wrote:\s*$", re.I)
_ORIGINAL = re.compile(r"^-{2,}\s*Original Message\s*-{2,}\s*$", re.I)
_FORWARDED = re.compile(r"^-{2,}\s*Forwarded message\s*-{2,}\s*$", re.I)
_BEGIN_FORWARD = re.compile(r"^Begin forwarded message:\s*$", re.I)
_FORWARD_MARK = re.compile(
    r"forwarded message|original message|begin forwarded message",
    re.I,
)
_FROM_EMAIL = re.compile(
    r"From:\s*(?:.*<)?([A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,})",
    re.I,
)


def fresh_message_text(text: str) -> str:
    """Drop quoted replies and forwarded history. Keep the new writing."""
    if not text:
        return ""
    kept = []
    for line in text.splitlines():
        if _QUOTE_LINE.match(line):
            continue
        stripped = line.strip()
        if _WROTE.match(stripped) or _ORIGINAL.match(stripped) or _FORWARDED.match(stripped) or _BEGIN_FORWARD.match(stripped):
            break
        kept.append(line)
    return "\n".join(kept).strip()


def is_forward(subject: str, body: str) -> bool:
    if re.match(r"^\s*(fw|fwd)\s*:", subject or "", re.I):
        return True
    return _FORWARD_MARK.search(body or "") is not None


def original_sender(body: str) -> Optional[str]:
    """The customer address inside a forwarded header, if one is there."""
    match = _FROM_EMAIL.search(body or "")
    if not match:
        return None
    return match.group(1).strip().lower()


def reply_recipient(subject: str, body: str, fallback: Optional[str]) -> tuple:
    """Who a draft should be addressed to.

    A forwarded request is addressed to the customer in the forward, not
    the person who forwarded it. Returns (address, forwarded).
    """
    forwarded = is_forward(subject or "", body or "")
    if forwarded:
        customer = original_sender(body or "")
        if customer:
            return customer, True
    return fallback, False
