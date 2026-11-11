"""The new part of an email, without the quoted thread underneath it.

Graph usually hands back HTML. Outlook, Gmail, and Apple Mail each wrap the
older message differently. Approval detection, PO numbers, and the
explicit-value scanner all start here so a quoted "grey" or a quoted PO
cannot decide the new request.
"""
from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Optional

_QUOTE_LINE = re.compile(r"^\s*>")
_WROTE = re.compile(r"^On .+ wrote:\s*$", re.I)
_ORIGINAL = re.compile(r"^-{2,}\s*Original Message\s*-{2,}\s*$", re.I)
_FORWARDED = re.compile(r"^-{2,}\s*Forwarded message\s*-{2,}\s*$", re.I)
_BEGIN_FORWARD = re.compile(r"^Begin forwarded message:\s*$", re.I)
_OUTLOOK_FROM = re.compile(r"^From:\s+\S", re.I)
_OUTLOOK_NEXT = re.compile(r"^(Sent|Date|To|Cc|Subject):\s+", re.I)
_FROM_EMAIL = re.compile(
    r"From:\s*(?:.*<)?([A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,})",
    re.I,
)
_SUBJECT_FORWARD = re.compile(r"^\s*(fw|fwd)\s*:", re.I)
_EXPLICIT_FORWARD = re.compile(
    r"begin forwarded message|-{2,}\s*forwarded message\s*-{2,}",
    re.I,
)
# A normal reply quotes us. That is not a forward, and it is not the customer.
_OWN_DOMAINS = ("opendc.ca", "elevated-doors.com")
_QUOTE_IDS = {"divrplyfwdmsg"}


class _MailToText(HTMLParser):
    """HTML to text, dropping the quoted history and everything after it."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list = []
        self.drop_rest = False
        self._hidden = 0

    def handle_starttag(self, tag, attrs):
        if self.drop_rest:
            return
        tag = (tag or "").lower()
        ad = {str(key).lower(): (value or "") for key, value in attrs}
        if tag in {"script", "style", "head"}:
            self._hidden += 1
            return
        if self._hidden:
            return
        element_id = ad.get("id", "").lower()
        css = ad.get("class", "").lower()
        if element_id in _QUOTE_IDS or "gmail_quote" in css or tag == "blockquote":
            self.drop_rest = True
            return
        if tag in {"br", "p", "div", "tr", "li", "h1", "h2", "h3", "blockquote"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if self.drop_rest:
            return
        if (tag or "").lower() in {"script", "style", "head"} and self._hidden:
            self._hidden -= 1

    def handle_data(self, data):
        if self.drop_rest or self._hidden:
            return
        self.parts.append(data)


def _looks_like_html(text: str) -> bool:
    sample = text.lstrip()[:500].lower()
    return sample.startswith("<") or "<div" in sample or "<html" in sample or "<br" in sample


def html_to_text(value: str) -> str:
    """Plain text. A message that is already plain text is unchanged."""
    if not value or not _looks_like_html(value):
        return value or ""
    parser = _MailToText()
    try:
        parser.feed(value)
        parser.close()
    except Exception:
        return re.sub(r"<[^>]+>", " ", value)
    text = "".join(parser.parts)
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def fresh_message_text(text: str) -> str:
    """The new writing only. HTML is converted first."""
    if not text:
        return ""
    plain = html_to_text(text)
    lines = plain.splitlines()
    kept = []
    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if _QUOTE_LINE.match(line):
            index += 1
            continue
        if (
            _WROTE.match(stripped)
            or _ORIGINAL.match(stripped)
            or _FORWARDED.match(stripped)
            or _BEGIN_FORWARD.match(stripped)
        ):
            break
        if _OUTLOOK_FROM.match(stripped) and _outlook_header_follows(lines, index + 1):
            break
        kept.append(line)
        index += 1
    return "\n".join(kept).strip()


def _outlook_header_follows(lines, start: int) -> bool:
    """True when the next few lines are Sent/Date/To/Subject, an Outlook quote."""
    window = [line.strip() for line in lines[start:start + 6] if line.strip()]
    return any(_OUTLOOK_NEXT.match(line) for line in window)


def _domain(address: str) -> str:
    if "@" not in (address or ""):
        return ""
    return address.rsplit("@", 1)[-1].strip().lower()


def _is_ours(address: str) -> bool:
    domain = _domain(address)
    return bool(domain) and (domain in _OWN_DOMAINS or domain.endswith(".opendc.ca"))


def is_forward(subject: str, body: str) -> bool:
    """A real forward, not a reply that quotes an older OpenDC message.

    Outlook starts every reply with 'Original message' and our own From line.
    That is the thread, not a forward.
    """
    if _SUBJECT_FORWARD.match(subject or ""):
        return True
    plain = html_to_text(body or "")
    return _EXPLICIT_FORWARD.search(plain) is not None


def original_sender(body: str) -> Optional[str]:
    """The customer address inside a forward, never an opendc.ca address."""
    plain = html_to_text(body or "")
    marker = _EXPLICIT_FORWARD.search(plain)
    tail = plain[marker.end():] if marker else plain
    match = _FROM_EMAIL.search(tail)
    if not match:
        return None
    address = match.group(1).strip().lower()
    if _is_ours(address):
        return None
    return address


def reply_recipient(subject: str, body: str, fallback: Optional[str]) -> tuple:
    """Who a draft should be addressed to. Returns (address, forwarded).

    Unsure means the sender of this message, and the reply stays on the thread.
    """
    if not is_forward(subject or "", body or ""):
        return fallback, False
    customer = original_sender(body or "")
    if customer:
        return customer, True
    return fallback, False
