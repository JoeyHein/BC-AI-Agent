"""bc_production_service._make_odata_request_all: a transient failure on one
page must retry, not silently look like "this was the last page."

Confirmed live 2026-09-09: a 30s read-timeout on one ProductionBomLines page
dropped 7 of 13 exploded panels' BOM lines, and so_po_generation_service
wrote an incomplete/wrong component list to a real BC purchase order
(PO-000962) before anyone caught it and reverted it.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.bc_production_service import BCProductionService


def _rows(n, start=0):
    return [{"No": f"item-{i}"} for i in range(start, start + n)]


class TestPaginationRetry:
    def test_normal_pagination_stops_on_short_page(self):
        svc = BCProductionService()
        calls = []

        def fake(endpoint, query_params=None):
            calls.append(dict(query_params))
            skip = int(query_params["$skip"])
            page_size = int(query_params["$top"])
            if skip == 0:
                return {"value": _rows(page_size)}
            return {"value": _rows(3, start=skip)}  # short final page

        svc._make_odata_request = fake
        rows = svc._make_odata_request_all("Items", page_size=5, max_pages=10)
        assert len(rows) == 5 + 3
        assert len(calls) == 2

    def test_transient_failure_retries_same_page_and_succeeds(self):
        svc = BCProductionService()
        attempts_at_skip5 = []

        def fake(endpoint, query_params=None):
            skip = int(query_params["$skip"])
            page_size = int(query_params["$top"])
            if skip == 0:
                return {"value": _rows(page_size)}
            attempts_at_skip5.append(1)
            if len(attempts_at_skip5) < 2:
                return None  # simulates the page erroring (timeout etc.)
            return {"value": _rows(3, start=skip)}

        svc._make_odata_request = fake
        rows = svc._make_odata_request_all("ProductionBomLines", page_size=5, max_pages=10)
        # must have recovered the full 8 rows, not silently truncated at 5
        assert len(rows) == 5 + 3
        assert len(attempts_at_skip5) == 2

    def test_failure_on_all_three_attempts_stops_with_partial_rows_not_a_crash(self):
        svc = BCProductionService()

        def fake(endpoint, query_params=None):
            skip = int(query_params["$skip"])
            page_size = int(query_params["$top"])
            if skip == 0:
                return {"value": _rows(page_size)}
            return None  # every retry of the second page fails

        svc._make_odata_request = fake
        rows = svc._make_odata_request_all("ProductionBomLines", page_size=5, max_pages=10)
        # first page's 5 rows are kept; the failed second page contributes nothing
        # (not a phantom empty-page "we're done" that silently drops real data
        # elsewhere in the table — callers must treat this as a possibly-partial
        # result, not a verified-complete one)
        assert len(rows) == 5

    def test_404_style_unavailable_endpoint_still_degrades_to_empty(self):
        """A genuinely unpublished web service (_make_odata_request already
        logs+returns None on 404) must still degrade to [] on the very first
        page, not retry forever or raise — existing callers rely on this."""
        svc = BCProductionService()
        svc._make_odata_request = lambda endpoint, query_params=None: None
        rows = svc._make_odata_request_all("NotPublished", page_size=5, max_pages=10)
        assert rows == []
