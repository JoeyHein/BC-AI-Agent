"""Incoming lane: packing-slip match, PO to SO, review, and the off flags."""
from __future__ import annotations

import sys
from datetime import date, datetime
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.api.shop_tv import router
from app.db.database import get_db as database_get_db
from app.db.models import (
    AppSettings,
    IncomingEmailReview,
    IncomingMailSeen,
    IncomingShipmentNotice,
    ShopTvKioskToken,
    SupplierOrderMap,
    User,
    UserRole,
)
from app.services.auth_service import AuthService
from app.services.shop_tv_incoming import (
    EMAIL_FLAG,
    accept_review,
    attach_incoming,
    build_incoming_days,
    build_upwardor_days,
    decide_match,
    email_matching_enabled,
    extract_shipping_notice,
    incoming_enabled,
    is_shipping_message,
    load_purchase_orders,
    lookup_sales_order_customers,
    poll_shipping_mail,
    reject_review,
    route_notice,
    set_flag,
    so_completion_text,
    summarize_po_lines,
)

TODAY = date(2026, 11, 12)
NOW = datetime(2026, 11, 12, 15, 0)

PACKING_SLIP = """
From: Justin <justin@upwardor.com>
Subject: Shipped — on the truck Order#116307 / PO#000962

Packing slip
S-ORD 116307
P.O. No. PO-000962
Carrier: TEAMS Transport
Waybill: TW-88421
ETA: 2026-11-14
PN10  16x7 insulated  Qty 1
TAG:SO-001842
"""

PO = {
    "number": "PO-000962",
    "vendorName": "Upwardor",
    "vendorNumber": "UPW",
    "status": "Open",
    "requestedReceiptDate": "2026-11-18",
    "vendorOrderNumber": "",
    "externalDocumentNumber": "",
    "purchaseOrderLines": [
        {"lineType": "Comment", "description": "Built from SO-001842"},
        {
            "lineType": "Item",
            "description": "16x7 insulated",
            "lineObjectNumber": "PN10",
            "quantity": 1,
            "receivedQuantity": 0,
        },
    ],
}
SALES = [{"number": "SO-001842", "customerName": "Prairie Door Co", "status": "Open"}]


def test_upwardor_packing_slip_extracts_po_supplier_order_carrier_and_eta():
    assert is_shipping_message("Shipped — on the truck", PACKING_SLIP, "justin@upwardor.com")
    extracted = extract_shipping_notice(
        "Shipped — on the truck Order#116307 / PO#000962",
        PACKING_SLIP,
        "justin@upwardor.com",
    )
    assert extracted["supplier_key"] == "upwardor"
    assert extracted["supplier_order_no"] == "S-ORD116307"
    assert extracted["our_po_number"] == "PO-000962"
    assert extracted["carrier"] == "TEAMS Transport"
    assert extracted["tracking"] == "TW-88421"
    assert extracted["eta"] == "2026-11-14"
    assert extracted["sales_orders"] == ["SO-001842"]
    assert extracted["lines"][0]["item"] == "PN10"
    assert extracted["lines"][0]["quantity"] == "1"


def test_po_resolves_to_sales_order_and_customer():
    extracted = extract_shipping_notice(
        "Shipped — on the truck Order#116307 / PO#000962",
        PACKING_SLIP,
        "justin@upwardor.com",
    )
    decision = decide_match(extracted, [PO], maps=[], sales_orders=SALES)
    assert decision["action"] == "apply"
    assert decision["confidence"] == "high"
    assert decision["po_number"] == "PO-000962"
    assert decision["sales_orders"] == [{"number": "SO-001842", "customer": "Prairie Door Co"}]
    days = build_incoming_days(
        [PO],
        SALES,
        notices=[{
            "our_po_number": "PO-000962",
            "supplier_order_no": "S-ORD116307",
            "carrier": "TEAMS Transport",
            "tracking": "TW-88421",
            "eta": "2026-11-14",
            "status": "shipped",
        }],
        today=TODAY,
        now=NOW,
    )
    item = days["days"][1]["items"][0]
    assert item["order_number"] == "PO-000962"
    assert item["customer"] == "Upwardor"
    assert "SO-001842 Prairie Door Co" in item["detail"]
    assert item["when_label"] == "Shipped"
    assert item["date"] == "2026-11-14"


def test_tracker_link_supplies_the_sales_order_when_the_po_text_does_not():
    po = {
        "number": "PO-000100",
        "vendorName": "Elton",
        "status": "Open",
        "requestedReceiptDate": "2026-11-11",
        "purchaseOrderLines": [{"lineType": "Item", "description": "Track", "quantity": 2, "receivedQuantity": 0}],
    }
    links = [{"po_number": "PO-000100", "so_number": "SO-000555", "source_label": "Elton", "customer_name": "North Hill Homes"}]
    days = build_incoming_days([po], [], tracker_links=links, today=TODAY, now=NOW)
    item = next(row for day in days["days"] for row in day["items"])
    assert item["overdue"] is True
    assert item["sales_orders"] == [{"number": "SO-000555", "customer": "North Hill Homes"}]


def test_saved_map_matches_the_next_email_without_a_po_number():
    extracted = {
        "supplier_key": "upwardor",
        "supplier_order_no": "S-ORD116307",
        "our_po_number": "",
        "sales_orders": [],
        "carrier": "TEAMS Transport",
        "tracking": "",
        "eta": "2026-11-14",
    }
    decision = decide_match(
        extracted,
        [PO],
        maps=[{
            "supplier_key": "upwardor",
            "supplier_order_no": "S-ORD116307",
            "our_po_number": "PO-000962",
            "sales_orders": [{"number": "SO-001842", "customer": "Prairie Door Co"}],
        }],
        sales_orders=SALES,
    )
    assert decision["action"] == "apply"
    assert decision["reason"] == "saved supplier map"
    assert decision["po_number"] == "PO-000962"


def test_low_confidence_email_is_review_and_does_not_pick_a_po():
    extracted = extract_shipping_notice(
        "Shipped — on the truck",
        "Elton says the order is on the truck. No PO number in this note.",
        "shipping@elton.example",
    )
    decision = decide_match(extracted, [PO], maps=[], sales_orders=SALES)
    assert decision["action"] == "review"
    assert decision["confidence"] == "low"
    assert decision["po_number"] == ""


def test_purchase_order_read_is_get_only():
    calls = []

    class BC:
        def get_open_purchase_orders_with_lines(self):
            calls.append("get")
            return [PO]

        def update_purchase_order(self, *args, **kwargs):
            raise AssertionError("wrote to Business Central")

    assert load_purchase_orders(BC()) == [PO]
    assert calls == ["get"]


def test_flags_off_return_nothing(monkeypatch):
    class Graph:
        def get_inbox_emails(self, *args, **kwargs):
            raise AssertionError("mail was read while matching is off")

    class DB:
        pass

    monkeypatch.setattr(
        "app.services.shop_tv_incoming.email_matching_enabled",
        lambda db: False,
    )
    monkeypatch.setattr(
        "app.services.shop_tv_incoming.incoming_enabled",
        lambda db: False,
    )
    monkeypatch.setattr(
        "app.services.shop_tv_incoming.load_purchase_orders",
        lambda bc=None: (_ for _ in ()).throw(AssertionError("purchase orders were read")),
    )
    assert poll_shipping_mail(DB(), graph=Graph(), purchase_orders=[PO])["processed"] == 0
    board = attach_incoming(DB(), {"lanes": {"production": {"days": []}}, "horizon_days": 7})
    assert board["incoming_enabled"] is False
    assert board["lanes"]["incoming"]["days"] == []
    assert board["lanes"]["upwardor"]["days"] == []


@pytest.fixture
def session():
    engine = create_engine(
        "sqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    for table in (
        User.__table__,
        AppSettings.__table__,
        ShopTvKioskToken.__table__,
        IncomingShipmentNotice.__table__,
        SupplierOrderMap.__table__,
        IncomingEmailReview.__table__,
        IncomingMailSeen.__table__,
    ):
        table.create(engine, checkfirst=True)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = Session()
    db.add(User(
        email="joey@opendc.ca",
        password_hash=AuthService.get_password_hash("test123"),
        name="Joey",
        role=UserRole.ADMIN,
        is_active=True,
        user_type="INTERNAL",
    ))
    db.commit()
    yield db
    db.close()


def test_low_confidence_is_stored_for_review_and_a_later_map_applies(session):
    vague = extract_shipping_notice(
        "Shipped — on the truck",
        "Justin at Upwardor says it shipped. No numbers.",
        "justin@upwardor.com",
    )
    decision = route_notice(session, vague, [PO], SALES)
    assert decision["action"] == "review"
    assert session.query(IncomingEmailReview).filter_by(status="pending").count() == 1
    assert session.query(IncomingShipmentNotice).count() == 0

    extracted = extract_shipping_notice(
        "Shipped — on the truck Order#116307 / PO#000962",
        PACKING_SLIP,
        "justin@upwardor.com",
    )
    applied = route_notice(session, extracted, [PO], SALES)
    assert applied["action"] == "apply"
    assert session.query(SupplierOrderMap).one().supplier_order_no == "S-ORD116307"
    follow = {
        "supplier_key": "upwardor",
        "supplier_order_no": "S-ORD116307",
        "our_po_number": "",
        "sales_orders": [],
        "carrier": "",
        "tracking": "TW-999",
        "eta": "2026-11-15",
        "sender": "justin@upwardor.com",
        "subject": "tracking",
    }
    again = route_notice(session, follow, [PO], SALES)
    assert again["reason"] == "saved supplier map"
    notice = session.query(IncomingShipmentNotice).one()
    assert notice.status == "shipped"
    assert notice.tracking == "TW-999"


def test_incoming_route_is_404_when_the_flag_is_off(session):
    def _override():
        try:
            yield session
        finally:
            pass

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[database_get_db] = _override
    client = TestClient(app)
    user = session.query(User).one()
    token = AuthService.create_access_token({"sub": str(user.id)})
    response = client.get("/api/shop-tv/incoming", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 404
    assert "PO-000962" not in response.text
    assert incoming_enabled(session) is False
    set_flag(session, "shop_tv_incoming", "on", user_id=user.id)
    assert incoming_enabled(session) is True
    assert email_matching_enabled(session) is False


def _po(number, vendor, vendor_order="", lines=None):
    return {
        "number": number,
        "vendorName": vendor,
        "status": "Open",
        "vendorOrderNumber": vendor_order,
        "requestedReceiptDate": "2026-11-14",
        "purchaseOrderLines": lines or [
            {"lineType": "Item", "description": "Goods", "quantity": 1, "receivedQuantity": 0},
        ],
    }


def test_cross_vendor_and_substring_supplier_orders_do_not_auto_apply():
    upwardor = _po("PO-000962", "Upwardor", "S-ORD116307")
    elton = extract_shipping_notice(
        "Shipped on the truck S-ORD 116307",
        "Packing slip from Elton. S-ORD 116307 is on the truck.",
        "shipping@elton.example",
    )
    decision = decide_match(elton, [upwardor])
    assert decision["action"] == "review"
    short = extract_shipping_notice(
        "Shipped S-ORD 1163",
        "Upwardor packing slip S-ORD 1163",
        "desk@upwardor.com",
    )
    assert decide_match(short, [upwardor])["action"] == "review"


def test_two_vendor_order_matches_go_to_review():
    first = _po("PO-000962", "Upwardor", "S-ORD116307")
    second = _po("PO-000963", "Upwardor", "S-ORD 116307")
    extracted = extract_shipping_notice(
        "Shipped S-ORD 116307",
        "Upwardor packing slip",
        "desk@upwardor.com",
    )
    decision = decide_match(extracted, [first, second])
    assert decision["action"] == "review"
    assert decision["po_number"] == ""


def test_empty_supplier_key_on_a_map_does_not_match():
    extracted = extract_shipping_notice(
        "Shipped Order#116307",
        "Upwardor packing slip",
        "desk@upwardor.com",
    )
    decision = decide_match(extracted, [PO], maps=[{
        "supplier_key": "",
        "supplier_order_no": "S-ORD116307",
        "our_po_number": "PO-000962",
        "sales_orders": [],
    }])
    assert decision["reason"] != "saved supplier map"


def test_unknown_sender_with_a_po_number_goes_to_review():
    extracted = extract_shipping_notice(
        "Shipped PO-000962",
        "On the truck. P.O. No. PO-000962",
        "someone@gmail.com",
    )
    assert extracted["supplier_key"] == ""
    decision = decide_match(extracted, [PO], sales_orders=SALES)
    assert decision["action"] == "review"
    assert "Justin" not in (extracted["supplier_key"] or "")


def test_customer_name_comes_from_a_sales_order_get_when_the_board_does_not_have_it():
    calls = []

    class BC:
        def get_sales_order_by_number(self, number):
            calls.append(number)
            return {"number": number, "customerName": "Prairie Door Co"}

        def update_sales_order(self, *args, **kwargs):
            raise AssertionError("wrote to Business Central")

    names = lookup_sales_order_customers(["SO-001842"], BC())
    assert names == {"SO-001842": "Prairie Door Co"}
    assert calls == ["SO-001842"]
    days = build_incoming_days(
        [PO],
        sales_orders=[],
        today=TODAY,
        now=NOW,
        customer_lookup=lambda numbers: {"SO-001842": "Prairie Door Co"},
    )
    item = next(row for day in days["days"] for row in day["items"])
    assert item["sales_orders"][0]["customer"] == "Prairie Door Co"


def test_duplicate_mail_and_reject_do_not_apply_twice(session):
    set_flag(session, EMAIL_FLAG, "on")
    message = {
        "id": "graph-1",
        "internetMessageId": "<ship-1@upwardor.com>",
        "subject": "Shipped — on the truck, no numbers",
        "body": {"content": "Justin wrote from Upwardor that it is on the truck."},
        "from": {"emailAddress": {"address": "desk@upwardor.com"}},
    }

    class Graph:
        def get_inbox_emails(self, mailbox, max_count=40):
            return [message]

    first = poll_shipping_mail(session, graph=Graph(), purchase_orders=[PO], mailboxes=["joey@opendc.ca"])
    second = poll_shipping_mail(session, graph=Graph(), purchase_orders=[PO], mailboxes=["joey@opendc.ca"])
    assert first["processed"] == 1
    assert second["processed"] == 0
    assert session.query(IncomingEmailReview).count() == 1
    review = session.query(IncomingEmailReview).one()
    assert reject_review(session, review.id)["status"] == "rejected"
    from app.services.shop_tv_incoming import accept_review
    again = accept_review(session, review.id, purchase_orders=[PO], sales_orders=SALES)
    assert again["ok"] is False
    assert again["reason"] == "already handled"
    assert session.query(IncomingShipmentNotice).count() == 0


def test_kiosk_token_cannot_open_or_reject_reviews(session):
    from app.services.shop_tv_kiosk import create_token

    def _override():
        try:
            yield session
        finally:
            pass

    set_flag(session, "shop_tv_incoming", "on")
    user = session.query(User).one()
    _row, plaintext = create_token(session, name="Floor", created_by_user_id=user.id)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[database_get_db] = _override
    client = TestClient(app)
    headers = {"X-Shop-Tv-Token": plaintext}
    assert client.get("/api/shop-tv/incoming/reviews", headers=headers).status_code == 401
    assert client.post("/api/shop-tv/incoming/reviews/1/reject", headers={"Authorization": f"Bearer {plaintext}"}).status_code == 401


def test_staff_fix_applies_an_unknown_sender_to_the_typed_po(session):
    extracted = extract_shipping_notice(
        "Shipped PO-000111",
        "On the truck. No supplier domain.",
        "someone@gmail.com",
    )
    assert extracted["supplier_key"] == ""
    queued = route_notice(session, extracted, [PO], SALES)
    assert queued["action"] == "review"
    result = accept_review(
        session,
        queued["review_id"],
        po_number="PO-000962",
        purchase_orders=[PO],
        sales_orders=SALES,
    )
    assert result["ok"] is True
    assert result["po_number"] == "PO-000962"
    notice = session.query(IncomingShipmentNotice).one()
    assert notice.our_po_number == "PO-000962"
    assert notice.status == "shipped"
    review = session.query(IncomingEmailReview).one()
    assert review.status == "accepted"


def test_staff_fix_applies_a_teams_notice_to_the_upwardor_po(session):
    extracted = extract_shipping_notice(
        "Shipped — on the truck",
        "Carrier: TEAMS Transport\nP.O. No. PO-000962\nWaybill: TW-88421\nETA: 2026-11-14",
        "dispatch@teamstransport.com",
    )
    assert extracted["supplier_key"] == ""
    assert extracted["carrier_key"] == "teams"
    assert extracted["our_po_number"] == "PO-000962"
    auto = decide_match(extracted, [PO], sales_orders=SALES)
    assert auto["action"] == "apply"
    assert auto["po_number"] == "PO-000962"
    assert auto["supplier_key"] == "upwardor"
    ambiguous = decide_match(extracted, [PO, dict(PO)])
    assert ambiguous["action"] == "review"
    queued = route_notice(session, {**extracted, "our_po_number": "", "message_id": "teams-review"}, [], SALES)
    assert queued["action"] == "review"
    fixed = accept_review(
        session,
        queued["review_id"],
        po_number="PO-000962",
        purchase_orders=[PO],
        sales_orders=SALES,
    )
    assert fixed["ok"] is True
    assert fixed["po_number"] == "PO-000962"
    other = route_notice(session, {**extracted, "our_po_number": "", "message_id": "teams-missing"}, [], SALES)
    missing = accept_review(
        session,
        other["review_id"],
        po_number="PO-999999",
        purchase_orders=[PO],
    )
    assert missing["ok"] is False
    assert "missing or matches more than one" in missing["reason"]
    assert session.query(IncomingEmailReview).filter_by(id=other["review_id"]).one().status == "pending"


def _up_po(number, lines, **extra):
    po = {
        "number": number,
        "vendorName": "Upwardor",
        "vendorNumber": "UPW",
        "status": "Open",
        "vendorOrderNumber": extra.pop("vendorOrderNumber", ""),
        "requestedReceiptDate": extra.pop("requestedReceiptDate", "2026-11-14"),
        "purchaseOrderLines": lines,
    }
    po.update(extra)
    return po


def _section(item, qty=1, received=0, description="section"):
    return {
        "lineType": "Item",
        "lineObjectNumber": item,
        "description": description,
        "quantity": qty,
        "receivedQuantity": received,
    }


def _hardware(qty=1):
    return {
        "lineType": "Item",
        "lineObjectNumber": "HK10-00704-0809",
        "description": "HARDWARE KIT",
        "quantity": qty,
        "receivedQuantity": 0,
    }


def _rows(days):
    return [row for day in days["days"] for row in day["items"]]


def test_summary_uses_the_door_comment_and_collapses_hardware():
    lines = [
        {"lineType": "Comment", "description": "Built from SO-001842"},
        {"lineType": "Comment", "description": "(2) 10'0\" x 7'0\" KANATA, WHITE, FLUSH, 2\" HW"},
        _section("PN65-21000-1000", qty=8),
        _hardware(2),
    ]
    assert summarize_po_lines(lines) == "2× 10x7 Kanata white sections + hardware"
    compact = [
        {"lineType": "Comment", "description": "(1) 16x7 TX450, WHITE, UDC"},
        _section("PN45-24400-1600", qty=4, description="TX450 SECTION"),
    ]
    assert summarize_po_lines(compact) == "1× 16x7 TX450 white sections"


def test_summary_falls_back_to_section_skus_and_skips_received_lines():
    lines = [
        _section("PN65-21000-1000", qty=2, description="KANATA SECTION, WHITE"),
        _section("PN65-21000-1200", qty=4, received=4, description="already here"),
        _hardware(),
    ]
    assert summarize_po_lines(lines) == "2× 10' Kanata white sections + hardware"
    received_sections = [
        {"lineType": "Comment", "description": "(2) 10x7 KANATA, WHITE"},
        _section("PN65-21000-1000", qty=8, received=8),
        _hardware(),
    ]
    assert summarize_po_lines(received_sections) == "Hardware"


def test_completes_so_when_this_is_the_only_open_po():
    po = _up_po("PO-000962", [
        {"lineType": "Comment", "description": "Built from SO-001842"},
        {"lineType": "Comment", "description": "(2) 10'0\" x 7'0\" KANATA, WHITE"},
        _section("PN65-21000-1000", qty=8),
        _hardware(),
    ], vendorOrderNumber="S-ORD116307")
    days = build_upwardor_days([po], SALES, today=TODAY, now=NOW)
    item = _rows(days)[0]
    assert item["completion"] == "Completes SO-001842"
    assert item["sales_label"] == "SO-001842 Prairie Door Co"
    assert item["summary"] == "2× 10x7 Kanata white sections + hardware"
    assert item["supplier_order_label"] == "S-ORD 116307"
    assert so_completion_text("SO-001842", []) == "Completes SO-001842"


def test_waiting_names_the_other_open_po_and_stock():
    upwardor = _up_po("PO-000962", [
        {"lineType": "Comment", "description": "Built from SO-001842"},
        _section("PN65-21000-1000", qty=4),
    ])
    elton = {
        "number": "PO-000881",
        "vendorName": "Elton",
        "status": "Open",
        "requestedReceiptDate": "2026-11-20",
        "purchaseOrderLines": [
            {"lineType": "Comment", "description": "Built from SO-001842"},
            {"lineType": "Item", "description": "Track", "quantity": 1, "receivedQuantity": 0},
        ],
    }
    received = {
        "number": "PO-000100",
        "vendorName": "Elton",
        "status": "Open",
        "purchaseOrderLines": [
            {"lineType": "Comment", "description": "Built from SO-001842"},
            {"lineType": "Item", "description": "Track", "quantity": 1, "receivedQuantity": 1},
        ],
    }
    days = build_upwardor_days([upwardor, elton, received], SALES, today=TODAY, now=NOW)
    item = _rows(days)[0]
    assert item["completion"] == "SO-001842 also waiting on PO-000881"
    assert so_completion_text("SO-001842", ["PO-000881"], needs_stock=True) == (
        "SO-001842 also waiting on PO-000881 and stock"
    )
    stocked = build_upwardor_days(
        [upwardor],
        SALES,
        stock_waiting={"SO-001842"},
        today=TODAY,
        now=NOW,
    )
    assert _rows(stocked)[0]["completion"] == "SO-001842 also waiting on stock"
    both = build_upwardor_days(
        [upwardor, elton],
        SALES,
        stock_waiting={"SO-001842"},
        today=TODAY,
        now=NOW,
    )
    assert _rows(both)[0]["completion"] == "SO-001842 also waiting on PO-000881 and stock"


def test_saved_map_links_the_sales_order_when_the_po_text_does_not():
    po = _up_po("PO-000962", [_section("PN65-21000-1000", qty=2), _hardware()], vendorOrderNumber="S-ORD116307")
    days = build_upwardor_days(
        [po],
        SALES,
        maps=[{
            "supplier_key": "upwardor",
            "supplier_order_no": "S-ORD116307",
            "our_po_number": "PO-000962",
            "sales_orders": [{"number": "SO-001842", "customer": "Prairie Door Co"}],
        }],
        today=TODAY,
        now=NOW,
    )
    item = _rows(days)[0]
    assert item["sales_orders"] == [{"number": "SO-001842", "customer": "Prairie Door Co"}]
    assert item["completion"] == "Completes SO-001842"
    assert item["customer"] == "Prairie Door Co"


def test_tag_on_the_po_links_the_sales_order():
    po = _up_po("PO-000700", [
        {"lineType": "Comment", "description": "TAG:SO-001842"},
        _section("PN65-21000-1000"),
    ])
    days = build_upwardor_days([po], SALES, today=TODAY, now=NOW)
    assert _rows(days)[0]["sales_label"] == "SO-001842 Prairie Door Co"


def test_unlinked_upwardor_po_reads_stock():
    po = _up_po("PO-000990", [_section("PN65-21000-1200", qty=4), _hardware()], vendorOrderNumber="")
    po["requestedReceiptDate"] = "0001-01-01"
    days = build_upwardor_days([po], today=TODAY, now=NOW)
    item = _rows(days)[0]
    assert item["sales_label"] == "STOCK"
    assert item["customer"] == "STOCK"
    assert item["completion"] == ""
    assert item["summary"] == "4× 12' Kanata white sections + hardware"
    assert days["days"][-1]["label"] == "Later"
    assert days["days"][-1]["sublabel"] == "No date"
    assert item["overdue"] is False


def test_later_and_overdue_upwardor_rows_stay_on_the_board():
    overdue = _up_po(
        "PO-000948",
        [{"lineType": "Comment", "description": "Built from SO-001842"}, _section("PN45-24400-1600")],
        requestedReceiptDate="2026-11-10",
        vendorOrderNumber="S-ORD116280",
    )
    later = _up_po(
        "PO-000995",
        [_section("PN65-21000-1000")],
        requestedReceiptDate="2026-11-28",
        vendorOrderNumber="S-ORD116400",
    )
    undated = _up_po("PO-000996", [_hardware()], requestedReceiptDate="", vendorOrderNumber="S-ORD116401")
    days = build_upwardor_days([overdue, later, undated], SALES, today=TODAY, now=NOW)
    by_number = {row["order_number"]: row for row in _rows(days)}
    assert by_number["PO-000948"]["overdue"] is True
    assert by_number["PO-000948"]["date"] == "2026-11-10"
    assert days["days"][0]["label"] == "Overdue"
    assert by_number["PO-000995"]["date"] == "2026-11-28"
    assert by_number["PO-000995"]["overdue"] is False
    assert by_number["PO-000996"]["date"] is None
    later_day = days["days"][-1]
    assert later_day["label"] == "Later"
    assert {row["order_number"] for row in later_day["items"]} == {"PO-000995", "PO-000996"}
    assert "PO-000948" not in {row["order_number"] for row in later_day["items"]}


def test_ship_notice_eta_beats_expected_receipt_and_ack_sets_status():
    po = _up_po("PO-000962", [
        {"lineType": "Comment", "description": "Built from SO-001842"},
        {
            **_section("PN65-21000-1000", qty=2),
            "expectedReceiptDate": "2026-11-18",
        },
    ], requestedReceiptDate="2026-11-20")
    noticed = build_upwardor_days(
        [po],
        SALES,
        notices=[{
            "our_po_number": "PO-000962",
            "supplier_order_no": "S-ORD116307",
            "eta": "2026-11-14",
            "status": "shipped",
        }],
        today=TODAY,
        now=NOW,
    )
    item = _rows(noticed)[0]
    assert item["date"] == "2026-11-14"
    assert item["eta_source"] == "notice"
    assert item["status_label"] == "Shipped"
    assert item["supplier_order_label"] == "S-ORD 116307"
    expected = build_upwardor_days([po], SALES, today=TODAY, now=NOW)
    assert _rows(expected)[0]["date"] == "2026-11-18"
    assert _rows(expected)[0]["eta_source"] == "expected"
    bare = _up_po("PO-000962", [_section("PN65-21000-1000")], requestedReceiptDate="2026-11-15")
    requested = build_upwardor_days(
        [bare],
        SALES,
        acks=[{
            "vendor_order_no": "S-ORD116307",
            "our_po_number": "PO-000962",
            "status": "confirmed",
            "received_at": datetime(2026, 11, 1),
        }],
        today=TODAY,
        now=NOW,
    )
    row = _rows(requested)[0]
    assert row["date"] == "2026-11-15"
    assert row["eta_source"] == "requested"
    assert row["status_label"] == "Acknowledged"
    assert row["supplier_order_label"] == "S-ORD 116307"


def test_other_vendors_stay_on_incoming(monkeypatch):
    upwardor = _up_po("PO-000962", [
        {"lineType": "Comment", "description": "Built from SO-001842"},
        _section("PN65-21000-1000"),
    ], vendorOrderNumber="S-ORD116307", requestedReceiptDate="2026-11-14")
    elton = {
        "number": "PO-000100",
        "vendorName": "Elton",
        "status": "Open",
        "requestedReceiptDate": "2026-11-14",
        "purchaseOrderLines": [
            {"lineType": "Item", "description": "Track", "quantity": 1, "receivedQuantity": 0},
        ],
    }
    far = _up_po("PO-000995", [_section("PN65-21000-1000")], requestedReceiptDate="2026-12-01")

    class Writer:
        def get_open_purchase_orders_with_lines(self):
            raise AssertionError("board build should use the purchase orders it was given")

        def update_purchase_order(self, *args, **kwargs):
            raise AssertionError("wrote to Business Central")

    monkeypatch.setattr("app.services.shop_tv_incoming.incoming_enabled", lambda db: True)
    monkeypatch.setattr("app.services.shop_tv_incoming._notices", lambda db: [])
    monkeypatch.setattr("app.services.shop_tv_incoming._maps", lambda db: [])
    monkeypatch.setattr("app.services.shop_tv_incoming._tracker_links", lambda db: [])
    monkeypatch.setattr("app.services.shop_tv_incoming._acks", lambda db: [])
    monkeypatch.setattr("app.services.shop_tv_incoming._stock_waiting", lambda db: set())
    monkeypatch.setattr(
        "app.services.shop_tv_incoming.lookup_sales_order_customers",
        lambda numbers, bc=None: (_ for _ in ()).throw(AssertionError("extra sales-order read")),
    )
    monkeypatch.setattr("app.services.shop_tv_incoming.load_purchase_orders", lambda bc=None: Writer())
    board = attach_incoming(
        object(),
        {"lanes": {"production": {"days": [{
            "items": [{"order_number": "SO-001842", "customer": "Prairie Door Co"}],
        }]}}, "horizon_days": 7},
        purchase_orders=[upwardor, elton, far],
        now=NOW,
    )
    incoming = [row["order_number"] for day in board["lanes"]["incoming"]["days"] for row in day["items"]]
    upwardor_rows = [row["order_number"] for day in board["lanes"]["upwardor"]["days"] for row in day["items"]]
    assert incoming == ["PO-000100"]
    assert "PO-000962" in upwardor_rows
    assert "PO-000995" in upwardor_rows
    assert "PO-000100" not in upwardor_rows
    assert board["incoming_enabled"] is True
