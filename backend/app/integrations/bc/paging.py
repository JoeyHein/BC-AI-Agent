"""Page through Business Central OData collections.

Two different BC behaviors show up in this tenant:

* api/v2.0 often emits ``@odata.nextLink``. Putting ``$top`` on those
  requests caps the *total* rows, so a full pull omits ``$top`` and
  follows the link.
* Published ODataV4 web services (PostedSalesInvoices, and the items
  entity) do not emit ``@odata.nextLink``. They return exactly ``$top``
  rows and stop. The only way past that cap is ``$skip``.

``collect_odata_pages`` follows a nextLink when BC sends one, and
otherwise continues with ``$skip`` when the page is full or matches a
known silent cap. A repeated first-row id means ``$skip`` was ignored;
the pull stops and is reported incomplete instead of looping.
"""

from typing import Any, Callable, Dict, List, Optional, Set, Tuple
from urllib.parse import urljoin

# Sizes BC has been observed to return with no nextLink when more rows exist.
SILENT_PAGE_CAPS = frozenset({500, 1000, 2000, 5000, 20000})

Fetch = Callable[[str], Dict[str, Any]]
SkipUrl = Callable[[int], str]


def _page_marker(row: Dict[str, Any]) -> Optional[str]:
    for key in ("id", "No", "number", "Number"):
        value = row.get(key)
        if value:
            return f"{key}:{value}"
    return None


def _absolute(base_url: str, link: str) -> str:
    if link.startswith("http://") or link.startswith("https://"):
        return link
    return urljoin(base_url, link)


def collect_odata_pages(
    fetch: Fetch,
    first_url: str,
    skip_url_for: SkipUrl,
    page_size: int,
    max_pages: int = 400,
) -> Tuple[List[Dict[str, Any]], bool]:
    """Return ``(rows, complete)``.

    ``complete`` is False when the pull stopped on an error, a repeated
    page (``$skip`` ignored), or ``max_pages``. An empty collection is
    complete.
    """
    rows: List[Dict[str, Any]] = []
    seen: Set[str] = set()
    url = first_url
    used_next = False

    for _ in range(max_pages):
        data = fetch(url)
        if not isinstance(data, dict) or data.get("_error"):
            return rows, False
        page = data.get("value") or []
        if not page:
            return rows, True

        marker = _page_marker(page[0])
        if marker is not None and marker in seen:
            return rows, False
        if marker is not None:
            seen.add(marker)
        rows.extend(page)

        next_link = data.get("@odata.nextLink")
        if next_link:
            used_next = True
            url = _absolute(url, str(next_link))
            continue

        if used_next:
            # OData: no nextLink means this was the last page.
            return rows, True

        # No server-driven paging on this pull. A short page is the end.
        # A full page, or a known silent cap, has to be continued with $skip.
        short = len(page) < page_size and len(page) not in SILENT_PAGE_CAPS
        oversized = len(page) > page_size and len(page) not in SILENT_PAGE_CAPS
        if short or oversized:
            return rows, True
        url = skip_url_for(len(rows))

    return rows, False
