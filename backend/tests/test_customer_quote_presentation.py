"""Customers see door-package totals. Component prices stay off the payload."""

import json
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.services.customer_quote_presentation import (
    annotate_customer_groups,
    build_customer_quote_pdf,
    collapse_customer_line_pricing,
    customer_visible_keys_only,
    present_customer_pricing,
)


DOOR = '(20) 9\'0" x 8\'0" KANATA, BLACK, SHXL, 2" BRACKET MOUNT, STD LIFT'


def _row(line_type, description, **extra):
    row = {
        "line_type": line_type,
        "description": description,
        "part_number": extra.pop("part_number", ""),
        "quantity": extra.pop("quantity", 1),
        "unit_price": extra.pop("unit_price", 10),
        "line_total": extra.pop("line_total", 10),
    }
    row.update(extra)
    return row


def _full_quote_lines():
    return [
        _row("Item", "Replacement section, ordered separately", part_number="PN65-21005-1600", quantity=1, unit_price=454.34, line_total=454.34),
        _row("Comment", DOOR, quantity=0, unit_price=0, line_total=0),
        _row("Item", "Section, Kanata, black, SHXL", part_number="PN65-21021-0900", quantity=80, unit_price=142.5, line_total=11400),
        _row("Item", "Bottom retainer", part_number="PL10-00141-00", quantity=20, unit_price=12.4, line_total=248),
        _row("Note", "PRICE NOTE: GK15-11205-00 flat long residential window $165.00 each", quantity=0, unit_price=0, line_total=0),
        _row("Note", "Door weight 168 lb, drum 400-12, 7.25 turns. Springs: 2 x .250", quantity=0, unit_price=0, line_total=0),
        _row("Item", "Springs", part_number="SP10-25025-01", quantity=40, unit_price=36, line_total=1440),
        _row("Item", "Door wrapping", part_number="WRAP", quantity=20, unit_price=15, line_total=300),
        _row("Item", "LiftMaster jackshaft operator", part_number="OP19-01106-00", quantity=2, unit_price=890, line_total=1780, category="operator"),
        _row("Item", "Freight (7.0% - AB)", part_number="FREIGHT", quantity=1, unit_price=420, line_total=420),
        _row("Comment", "Freight is an estimate. If the actual shipping cost comes in higher, the difference will be added to the invoice.", quantity=0, unit_price=0, line_total=0, is_freight_note=True),
    ]


def _sources(lines):
    sources = []
    for line in lines:
        sources.append({
            "description": line["description"],
            "part_number": line["part_number"],
            "lineType": "Comment" if line["line_type"] in {"Comment", "Note"} else "Item",
            "is_door_desc": line["description"] == DOOR,
            "is_note": line["line_type"] == "Note",
            "is_freight_note": line.get("is_freight_note"),
            "is_door_freight": line["part_number"] == "FREIGHT",
            "category": line.get("category") or "",
        })
    return sources


def test_customer_payload_hides_component_prices_and_notes():
    lines = _full_quote_lines()
    annotate_customer_groups(lines, _sources(lines))
    # The staff snapshot is the same list, still itemized.
    assert any(row["part_number"] == "PN65-21021-0900" and row["unit_price"] == 142.5 for row in lines)

    visible = collapse_customer_line_pricing(lines)
    rendered = json.dumps(visible)
    assert customer_visible_keys_only(visible)
    assert "PN65-21021-0900" not in rendered
    assert "PL10-00141-00" not in rendered
    assert "PRICE NOTE" not in rendered
    assert "GK15-11205-00" not in rendered
    assert "Door weight" not in rendered
    assert "unit_price" not in rendered
    assert "7.0%" not in rendered
    assert "15 items" not in rendered

    standalone, package, operator, freight = visible
    assert standalone == {
        "line_type": "Item",
        "description": "Replacement section, ordered separately",
        "quantity": 1,
        "line_total": 454.34,
    }
    assert package["line_type"] == "Package"
    assert package["description"] == DOOR
    assert package["quantity"] == 20
    # Section + retainer + springs + wrap. The operator is not in the package.
    assert package["line_total"] == 11400 + 248 + 1440 + 300
    assert operator["description"] == "LiftMaster jackshaft operator"
    assert operator["quantity"] == 2
    assert operator["line_total"] == 1780
    assert freight == {
        "line_type": "Freight",
        "description": "Freight (estimate)",
        "quantity": 1,
        "line_total": 420,
    }


def test_bc_lines_without_portal_tags_collapse_the_same_way():
    lines = [
        {"lineType": "Item", "lineObjectNumber": "PN65-21005-1600", "description": "Replacement section", "quantity": 1, "unitPrice": 454.34, "lineAmount": 454.34, "sequence": 1000},
        {"lineType": "Comment", "description": DOOR, "sequence": 10000},
        {"lineType": "Item", "lineObjectNumber": "PN65-21021-0900", "description": "Section", "quantity": 80, "unitPrice": 100, "lineAmount": 8000, "sequence": 11000},
        {"lineType": "Comment", "description": "PRICE NOTE: GK15-11205-00 flat long residential window $165.00 each", "sequence": 12000},
        {"lineType": "Item", "lineObjectNumber": "OP19-01106-00", "description": "LiftMaster jackshaft", "quantity": 2, "unitPrice": 890, "lineAmount": 1780, "sequence": 20000},
        {"lineType": "Item", "lineObjectNumber": "FREIGHT", "description": "Freight (7.0% - AB)", "quantity": 1, "unitPrice": 70, "lineAmount": 70, "sequence": 30000},
    ]
    visible = collapse_customer_line_pricing(lines, output_by_sequence={20000: True, 30000: True})
    rendered = json.dumps(visible)
    assert "PN65-21021-0900" not in rendered
    assert "PRICE NOTE" not in rendered
    assert "165.00" not in rendered
    assert [row["line_type"] for row in visible] == ["Item", "Package", "Item", "Freight"]
    assert visible[1]["quantity"] == 20
    assert visible[1]["line_total"] == 8000
    assert visible[2]["line_total"] == 1780
    assert visible[3]["description"] == "Freight (estimate)"
    assert visible[3]["line_total"] == 70


def test_present_customer_pricing_drops_part_counts_and_override_warnings():
    presented = present_customer_pricing({
        "line_pricing": _full_quote_lines(),
        "door_results": [{
            "door_index": 1,
            "door_description": DOOR,
            "parts_count": 15,
            "success": True,
        }],
        "lines_failed": [{"part_number": "PN65-21021-0900", "error": "missing"}],
        "price_override_warnings": [{
            "part_number": "PN65-21021-0900",
            "message": "PN65-21021-0900 was $142.50 on the previous quote",
        }],
        "pricing": {"subtotal": 1, "tax": 0, "total": 1},
    })
    # These rows were not annotated, so collapse infers groups from the rows.
    rendered = json.dumps(presented)
    assert "parts_count" not in rendered
    assert "lines_failed" not in presented
    assert "price_override_warnings" not in presented
    assert "PN65-21021-0900" not in rendered
    assert presented["pricing"]["total"] == 1
    assert presented["door_results"][0]["door_description"] == DOOR


def test_customer_pdf_lists_the_package_and_not_the_components():
    quote = {
        "number": "SQ-003487",
        "customerName": "Prairie Door Co.",
        "documentDate": "2026-11-27",
        "totalAmountExcludingTax": 15622.34,
        "totalAmountIncludingTax": 16403.46,
    }
    pdf = build_customer_quote_pdf(quote, _full_quote_lines())
    assert pdf.startswith(b"%PDF")
    text = _pdf_text(pdf)
    assert "SQ-003487" in text
    assert "KANATA" in text
    assert "Freight is an estimate" in text
    assert "Subtotal" in text
    assert "PN65-21021-0900" not in text
    assert "PRICE NOTE" not in text
    assert "Door weight" not in text
    assert "Bottom retainer" not in text
    assert "142.50" not in text


def _pdf_text(pdf: bytes) -> str:
    import shutil
    import subprocess
    import tempfile
    if not shutil.which("pdftotext"):
        return pdf.decode("latin-1", "ignore")
    with tempfile.NamedTemporaryFile(suffix=".pdf") as handle:
        handle.write(pdf)
        handle.flush()
        result = subprocess.run(
            ["pdftotext", "-layout", handle.name, "-"],
            check=True,
            capture_output=True,
        )
    return result.stdout.decode()


def test_customer_quote_detail_and_pdf_do_not_return_component_prices(monkeypatch):
    from app.api import customer_portal as portal
    from app.api.customer_auth import get_current_customer

    user = SimpleNamespace(
        id=7,
        email="dealer@example.com",
        bc_customer_id="C-100",
        is_active=True,
        user_type="CUSTOMER",
    )
    quote = {
        "id": "guid-3487",
        "number": "SQ-003487",
        "customerId": "C-100",
        "customerName": "Prairie Door Co.",
        "documentDate": "2026-11-27",
        "status": "Open",
        "totalAmountExcludingTax": 1000,
        "totalAmountIncludingTax": 1050,
        "currencyCode": "CAD",
    }
    lines = [
        {"lineType": "Comment", "description": DOOR, "sequence": 10000},
        {
            "lineType": "Item",
            "lineObjectNumber": "PN65-21021-0900",
            "description": "Section",
            "quantity": 80,
            "unitPrice": 100,
            "lineAmount": 8000,
            "sequence": 11000,
        },
        {
            "lineType": "Comment",
            "description": "PRICE NOTE: GK15-11205-00 flat $165.00 each",
            "sequence": 12000,
        },
    ]
    monkeypatch.setattr(portal.bc_client, "get_sales_quote", lambda quote_id: quote)
    monkeypatch.setattr(portal.bc_client, "get_document_lines", lambda path: lines)
    monkeypatch.setattr(portal.bc_client, "get_quote_output_map", lambda number: {})
    monkeypatch.setattr(
        portal.bc_client,
        "get_quote_pdf",
        lambda quote_id: (_ for _ in ()).throw(AssertionError("itemized BC PDF")),
    )

    app = FastAPI()
    app.include_router(portal.router)

    def _db():
        yield None

    app.dependency_overrides[portal.get_db] = _db
    app.dependency_overrides[get_current_customer] = lambda: user
    client = TestClient(app)

    detail = client.get("/api/customer/portal/bc-quotes/guid-3487")
    assert detail.status_code == 200, detail.text
    body = detail.json()
    rendered = json.dumps(body["lines"])
    assert "PN65-21021-0900" not in rendered
    assert "unit_price" not in rendered
    assert "PRICE NOTE" not in rendered
    assert body["lines"][0]["line_type"] == "Package"
    assert body["lines"][0]["quantity"] == 20
    assert body["lines"][0]["line_total"] == 8000
    assert body["quote"]["total_amount"] == 1050

    downloaded = client.get("/api/customer/portal/bc-quotes/guid-3487/pdf")
    assert downloaded.status_code == 200
    assert downloaded.content.startswith(b"%PDF")
    text = _pdf_text(downloaded.content)
    assert "SQ-003487" in text
    assert "KANATA" in text
    assert "PN65-21021-0900" not in text
    assert "PRICE NOTE" not in text

    quote["customerId"] = "C-OTHER"
    denied = client.get("/api/customer/portal/bc-quotes/guid-3487")
    assert denied.status_code == 403
