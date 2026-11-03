"""Order tracker, to-do list, and approval-gated mail.

No live Business Central or Graph calls. Sending happens only when a test
calls approve_message with a fake sender.
"""
from __future__ import annotations

import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.api.ops_tracker import get_current_admin, get_db, router as ops_router
from app.db.models import (
    OpsActionItem,
    OpsActivity,
    OpsFieldAudit,
    OpsOutboundMessage,
    OpsTrackedLine,
    OpsTrackedOrder,
    OpsTrackedPo,
    OpsTrackerMeta,
    VendorOrderAck,
)
from app.services.ops_po_mail import apply_mailbox, extract_acknowledgement, note_po_review_draft
from app.services.ops_tracker_service import (
    Actor,
    OpsTrackerError,
    add_note,
    apply_snapshot,
    approve_message,
    complete_action,
    create_follow_up,
    feed_mail,
    list_actions,
    list_activity,
    patch_line,
    patch_order,
    purchasing_work,
    reject_message,
    snapshot_from_bc,
    weekly_summary,
)
from app.services.staff_permissions import permission_for

TODAY = date(2026, 11, 3)
ACTOR = Actor(user_id=7, email="joey@opendc.ca", source="portal")
SYNC = Actor(email="Business Central", source="sync")


def _db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY)"))
    for table in (
        OpsTrackerMeta.__table__,
        OpsTrackedOrder.__table__,
        OpsTrackedLine.__table__,
        OpsTrackedPo.__table__,
        OpsFieldAudit.__table__,
        OpsActionItem.__table__,
        OpsOutboundMessage.__table__,
        OpsActivity.__table__,
    ):
        table.create(engine)
    return sessionmaker(bind=engine)()


def _order(number="SO-10421", item="PN10", email="pat@prairiedoor.ca", **extra):
    body = {
        "number": number,
        "id": "guid-" + number,
        "customer_number": "C100",
        "customer_name": "Prairie Door Co",
        "customer_email": email,
        "external_document_number": "LOT-18",
        "order_date": "2026-10-01",
        "status": "Open",
        "fully_shipped": False,
        "lines": [
            {
                "line_no": 10000,
                "item_no": item,
                "description": "Insulated panel",
                "quantity": 2,
                "shipped_quantity": 0,
                "line_type": "Item",
            }
        ],
    }
    body.update(extra)
    return body


def _po(number="PO-000956", so="SO-10421", vendor_number="UPW", vendor_name="Upwardor", status="Open", order_date="2026-10-02", expected="2026-11-05", item="PN10", **extra):
    body = {
        "number": number,
        "vendor_number": vendor_number,
        "vendor_name": vendor_name,
        "vendor_email": "orders@upwardor.com",
        "status": status,
        "order_date": order_date,
        "expected_date": expected,
        "external_document_number": so,
        "lines": [
            {
                "item_no": item,
                "description": f"Built from {so}",
                "quantity": 2,
                "received_quantity": 0,
                "line_type": "Item",
            }
        ],
    }
    body.update(extra)
    return body


def _apply(db, orders, purchase_orders=None, acks=None, emails=None, today=TODAY, allow_empty=False):
    snapshot = {"orders": orders, "vendors": [], "acks": acks or [], "receipts": []}
    if purchase_orders is not None:
        snapshot["purchase_orders"] = purchase_orders
    if emails is not None:
        snapshot["emails"] = emails
    return apply_snapshot(db, snapshot, actor=SYNC, today=today, allow_empty=allow_empty)


def _pending(db, kind):
    return (
        db.query(OpsOutboundMessage)
        .filter(OpsOutboundMessage.kind == kind, OpsOutboundMessage.status == "pending")
        .all()
    )


def test_sync_defaults_source_to_upwardor_and_links_po():
    db = _db()
    _apply(db, [_order()], [_po()])
    line = db.query(OpsTrackedLine).one()
    order = db.query(OpsTrackedOrder).one()
    assert line.source_code == "UPW"
    assert line.source_label == "Upwardor"
    assert line.linked_po_number == "PO-000956"
    assert order.upwardor_po_number == "PO-000956"
    assert order.external_document_number == "LOT-18"
    assert order.order_status == "Ordered"
    assert order.expected_receipt == date(2026, 11, 5)
    assert order.fulfillment == "Buy Complete"
    assert _pending(db, "customer_update") == []


def test_date_change_queues_customer_update_without_sending():
    db = _db()
    sent = []
    _apply(db, [_order()], [_po(expected="2026-11-05")])
    _apply(db, [_order()], [_po(expected="2026-11-20")])
    queued = _pending(db, "customer_update")
    assert len(queued) == 1
    assert queued[0].to_email == "pat@prairiedoor.ca"
    assert "2026-11-20" in queued[0].body_text
    assert "2026-11-05" in queued[0].body_text
    assert sent == []
    approve_message(db, queued[0].id, ACTOR, lambda message: sent.append(message))
    db.commit()
    assert len(sent) == 1
    assert sent[0]["to_email"] == "pat@prairiedoor.ca"
    assert db.query(OpsOutboundMessage).filter_by(kind="customer_update").one().status == "sent"
    order = db.query(OpsTrackedOrder).one()
    assert order.customer_update_baseline == date(2026, 11, 20)


def test_reject_does_not_send_and_same_date_is_not_redrafted():
    db = _db()
    sent = []
    _apply(db, [_order()], [_po(expected="2026-11-05")])
    _apply(db, [_order()], [_po(expected="2026-11-20")])
    message = _pending(db, "customer_update")[0]
    reject_message(db, message.id, ACTOR)
    db.commit()
    assert sent == []
    assert db.query(OpsOutboundMessage).filter_by(kind="customer_update").one().status == "rejected"
    _apply(db, [_order()], [_po(expected="2026-11-20")])
    assert _pending(db, "customer_update") == []


def test_supplier_reminder_is_queued_on_a_cadence_and_not_sent():
    db = _db()
    sent = []
    _apply(db, [_order()], [_po(order_date="2026-10-01", expected="2026-11-05")])
    queued = _pending(db, "supplier_reminder")
    assert len(queued) == 1
    assert "PO-000956" in queued[0].subject
    assert queued[0].to_email == "orders@upwardor.com"
    assert sent == []
    approve_message(db, queued[0].id, ACTOR, lambda message: sent.append(message), now=datetime(2026, 11, 3, 15, 0))
    db.commit()
    assert len(sent) == 1
    _apply(db, [_order()], [_po(order_date="2026-10-01")], today=TODAY)
    assert _pending(db, "supplier_reminder") == []
    _apply(db, [_order()], [_po(order_date="2026-10-01")], today=TODAY + timedelta(days=3))
    assert len(_pending(db, "supplier_reminder")) == 1


def test_ack_closes_missing_ack_and_withdraws_reminder():
    db = _db()
    _apply(db, [_order()], [_po(order_date="2026-10-01")])
    assert db.query(OpsActionItem).filter_by(kind="missing_ack", status="open").count() == 1
    _apply(
        db,
        [_order()],
        [_po(order_date="2026-10-01")],
        acks=[{
            "po_number": "PO-000956",
            "status": "confirmed",
            "completion_date": "2026-11-18",
            "received_at": "2026-10-04T12:00:00",
            "vendor_order_no": "S-ORD116307",
        }],
    )
    assert db.query(OpsActionItem).filter_by(kind="missing_ack", status="open").count() == 0
    reminder = db.query(OpsOutboundMessage).filter_by(kind="supplier_reminder").one()
    assert reminder.status == "withdrawn"
    assert db.query(OpsTrackedPo).one().vendor_order_no == "S-ORD116307"
    assert db.query(OpsTrackedOrder).one().expected_receipt == date(2026, 11, 18)


def test_missing_po_closes_when_linked_and_stock_does_not_need_one():
    db = _db()
    _apply(db, [_order()], [])
    assert db.query(OpsActionItem).filter_by(kind="missing_po", status="open").count() == 1
    line = db.query(OpsTrackedLine).one()
    patch_line(db, line.id, {"source_code": "STOCK", "source_label": "Stock / on hand"}, ACTOR, today=TODAY)
    assert db.query(OpsActionItem).filter_by(kind="missing_po", status="open").count() == 0
    audit = db.query(OpsFieldAudit).filter_by(field_name="source_code").one()
    assert audit.old_value == "UPW"
    assert audit.new_value == "STOCK"
    assert audit.actor_email == "joey@opendc.ca"
    assert audit.source == "portal"


def test_other_supplier_without_a_po_stays_on_the_list():
    db = _db()
    _apply(db, [_order()], [_po()])
    line = db.query(OpsTrackedLine).one()
    patch_line(db, line.id, {"source_code": "NWD", "source_label": "Northwest Door", "linked_po_number": ""}, ACTOR, today=TODAY)
    kinds = {row.kind for row in db.query(OpsActionItem).filter_by(status="open")}
    assert "missing_po_line" in kinds


def test_follow_up_stays_open_until_marked_done():
    db = _db()
    _apply(db, [_order()], [])
    follow = create_follow_up(db, {"title": "Call Prairie Door about the site", "so_number": "SO-10421", "due_on": "2026-11-01"}, ACTOR)
    structural = db.query(OpsActionItem).filter_by(kind="missing_po", status="open").one()
    with pytest.raises(OpsTrackerError):
        complete_action(db, structural.id, ACTOR)
    _apply(db, [_order()], [_po()])
    row = db.query(OpsActionItem).filter_by(id=follow["id"]).one()
    assert row.status == "open"
    assert row.auto_managed is False
    complete_action(db, row.id, ACTOR)
    assert db.query(OpsActionItem).filter_by(id=row.id).one().status == "done"
    assert db.query(OpsActionItem).filter_by(kind="missing_po").one().status == "done"


def test_reply_closes_when_answered_and_stays_when_mail_is_down():
    db = _db()
    _apply(db, [_order()], [])
    inbox = [{
        "id": "m1",
        "conversation_id": "c1",
        "received_at": "2026-11-02T09:00:00",
        "from_email": "andrew@upwardor.com",
        "from_name": "Andrew",
        "subject": "Ship date?",
        "preview": "Can you confirm?",
    }]
    feed_mail(db, {"available": True, "mailbox": "joey@opendc.ca", "inbox": inbox, "sent": []}, today=TODAY)
    assert db.query(OpsActionItem).filter_by(kind="needs_reply", status="open").count() == 1
    feed_mail(db, {
        "available": True,
        "mailbox": "joey@opendc.ca",
        "inbox": inbox,
        "sent": [{
            "id": "s1",
            "conversation_id": "c1",
            "sent_at": "2026-11-02T11:00:00",
            "from_email": "joey@opendc.ca",
            "subject": "Re: Ship date?",
        }],
    }, today=TODAY)
    assert db.query(OpsActionItem).filter_by(kind="needs_reply", status="open").count() == 0

    feed_mail(db, {"available": True, "mailbox": "joey@opendc.ca", "inbox": inbox, "sent": []}, today=TODAY)
    assert db.query(OpsActionItem).filter_by(kind="needs_reply", status="open").count() == 1
    feed_mail(db, {"available": False, "reason": "Graph is not configured", "inbox": [], "sent": []}, today=TODAY)
    assert db.query(OpsActionItem).filter_by(kind="needs_reply", status="open").count() == 1


def test_send_failure_stays_pending_and_blank_recipient_is_refused():
    db = _db()
    _apply(db, [_order(email="")], [_po(order_date="2026-10-01")])
    reminder = _pending(db, "supplier_reminder")[0]
    reminder.to_email = None
    db.commit()

    def boom(_message):
        raise RuntimeError("mailbox down")

    reminder.to_email = "orders@upwardor.com"
    db.commit()
    with pytest.raises(OpsTrackerError) as caught:
        approve_message(db, reminder.id, ACTOR, boom)
    assert caught.value.status == 502
    assert db.query(OpsOutboundMessage).filter_by(id=reminder.id).one().status == "pending"
    assert "mailbox down" in (db.query(OpsOutboundMessage).filter_by(id=reminder.id).one().send_error or "")

    customer = OpsOutboundMessage(
        kind="customer_update",
        status="pending",
        dedupe_key="customer:SO-10421:2026-12-01",
        to_email=None,
        subject="Production update for SO-10421",
        body_text="Hello",
        so_number="SO-10421",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(customer)
    db.commit()
    with pytest.raises(OpsTrackerError) as missing:
        approve_message(db, customer.id, ACTOR, lambda message: None)
    assert missing.value.status == 400


def test_order_status_does_not_move_backward():
    db = _db()
    _apply(db, [_order()], [_po()])
    patch_order(db, "SO-10421", {"order_status": "Shipped by Vendor"}, ACTOR, today=TODAY)
    _apply(db, [_order()], [_po()])
    assert db.query(OpsTrackedOrder).one().order_status == "Shipped by Vendor"


def test_empty_bc_pull_does_not_wipe_the_book():
    db = _db()
    _apply(db, [_order()], [_po()])
    with pytest.raises(OpsTrackerError) as caught:
        _apply(db, [], [])
    assert caught.value.status == 409
    assert db.query(OpsTrackedOrder).one().bc_open is True
    assert db.query(OpsTrackedPo).one().bc_open is True


def test_weekly_summary_math():
    db = _db()
    _apply(db, [_order()], [_po(order_date="2026-10-01", expected="2026-10-21")])
    po = db.query(OpsTrackedPo).one()
    po.ack_received_at = datetime(2026, 10, 4, 12, 0)
    po.receipt_date = date(2026, 10, 21)
    db.commit()
    order = db.query(OpsTrackedOrder).one()
    order.expected_receipt = date(2026, 10, 21)
    db.commit()
    report = weekly_summary(db, TODAY)
    assert report["week_start"] == "2026-11-02"
    assert report["week_ending"] == "2026-11-08"
    assert report["lead_time_days_by_supplier"][0]["supplier"] == "Upwardor"
    assert report["lead_time_days_by_supplier"][0]["avg_lead_days"] == 20.0
    assert report["ack_turnaround_days_by_supplier"][0]["avg_days"] == 3.0
    assert report["late_orders"][0]["so_number"] == "SO-10421"
    assert report["late_orders"][0]["days_late"] == 13
    assert "nothing_sends_automatically" in report["definitions"]


def test_snapshot_from_bc_maps_orders_pos_and_acks():
    db = _db()
    VendorOrderAck.__table__.create(db.get_bind())
    db.add(VendorOrderAck(
        source_email_id="e1",
        attachment_filename="ack.pdf",
        vendor_no="UPW",
        vendor_order_no="S-ORD9",
        our_po_number="PO-000956",
        status="confirmed",
        completion_date=date(2026, 11, 12),
        received_at=datetime(2026, 10, 5, 8, 0),
    ))
    db.commit()

    class FakeBC:
        def get_open_sales_orders_with_lines(self):
            return [{
                "number": "SO-10421",
                "id": "g1",
                "customerNumber": "C100",
                "customerName": "Prairie Door Co",
                "email": "pat@prairiedoor.ca",
                "externalDocumentNumber": "LOT-18",
                "orderDate": "2026-10-01",
                "status": "Open",
                "fullyShipped": False,
                "salesOrderLines": [{
                    "sequence": 10000,
                    "lineType": "Item",
                    "lineObjectNumber": "PN10",
                    "description": "Panel",
                    "quantity": 2,
                    "shippedQuantity": 0,
                }],
            }]

        def get_open_purchase_orders_with_lines(self):
            return [{
                "number": "PO-000956",
                "vendorNumber": "UPW",
                "vendorName": "Upward Door",
                "status": "Open",
                "orderDate": "2026-10-02",
                "requestedReceiptDate": "2026-11-01",
                "externalDocumentNumber": "SO-10421",
                "purchaseOrderLines": [{
                    "lineType": "Item",
                    "lineObjectNumber": "PN10",
                    "description": "Built from SO-10421",
                    "quantity": 2,
                    "receivedQuantity": 0,
                }],
            }]

        def get_vendors(self, top=500):
            return [{"number": "NWD", "displayName": "Northwest Door", "email": "sales@northwestdoor.com"}]

        def get_purchase_receipts_with_lines(self):
            return []

    snapshot = snapshot_from_bc(FakeBC(), db)
    assert snapshot["orders"][0]["customer_name"] == "Prairie Door Co"
    assert snapshot["orders"][0]["lines"][0]["item_no"] == "PN10"
    assert snapshot["purchase_orders"][0]["number"] == "PO-000956"
    assert snapshot["acks"][0]["vendor_order_no"] == "S-ORD9"
    assert snapshot["vendors"][0]["name"] == "Northwest Door"


def test_permissions_gate_reads_and_approval():
    assert permission_for("GET", "/api/ops/tracker") == ("perm", "production.view")
    assert permission_for("GET", "/api/ops/weekly-summary") == ("perm", "production.view")
    assert permission_for("POST", "/api/ops/messages/4/approve") == ("any", "production.edit", "purchase_orders.send")
    assert permission_for("GET", "/api/ops/purchasing-work") == ("any", "production.view", "purchase_orders.view")
    assert permission_for("POST", "/api/ops/activity") == ("any", "production.edit", "purchase_orders.edit")
    assert permission_for("POST", "/api/ops/sync") == ("perm", "production.edit")


def test_api_approve_is_the_only_send_and_filters_search():
    db = _db()
    sent = []
    app = FastAPI()
    app.include_router(ops_router)

    def _override_db():
        yield db

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_admin] = lambda: SimpleNamespace(
        id=7, email="joey@opendc.ca", is_active=True, role="owner", user_type="INTERNAL", permissions=None
    )
    client = TestClient(app)
    import app.api.ops_tracker as api_mod
    api_mod.default_sender = lambda message: sent.append(message)

    ingested = client.post("/api/ops/ingest", json={
        "orders": [_order(), _order(number="SO-10422", item="GK17", email="other@example.com", customer_name="Lynx Homes", external_document_number="JOB-2")],
        "purchase_orders": [
            _po(),
            _po(number="PO-000960", so="SO-10422", vendor_number="LYNX", vendor_name="Lynx", vendor_email="sales@lynx.com", item="GK17", order_date="2026-10-20"),
        ],
    })
    assert ingested.status_code == 200, ingested.text
    listed = client.get("/api/ops/tracker", params={"q": "LOT-18"})
    assert listed.status_code == 200
    assert [row["so_number"] for row in listed.json()["orders"]] == ["SO-10421"]
    at_risk = client.get("/api/ops/tracker", params={"supplier": "lynx"})
    assert [row["so_number"] for row in at_risk.json()["orders"]] == ["SO-10422"]

    messages = client.get("/api/ops/messages", params={"status": "pending"})
    assert messages.status_code == 200
    reminder = next(row for row in messages.json()["messages"] if row["kind"] == "supplier_reminder" and row["po_number"] == "PO-000956")
    approved = client.post(f"/api/ops/messages/{reminder['id']}/approve")
    assert approved.status_code == 200, approved.text
    assert sent and sent[0]["po_number"] == "PO-000956"
    rejected_pool = [row for row in client.get("/api/ops/messages", params={"status": "pending"}).json()["messages"]]
    if rejected_pool:
        refused = client.post(f"/api/ops/messages/{rejected_pool[0]['id']}/reject")
        assert refused.status_code == 200
        assert sent == [sent[0]]


def test_activity_log_records_events_once_and_notes_can_open_a_follow_up():
    db = _db()
    _apply(db, [_order()], [_po(status="Draft", order_date="2026-11-01")])
    recorded = db.query(OpsActivity).filter_by(event_type="po_recorded").count()
    assert recorded == 1
    assert db.query(OpsActivity).filter_by(event_type="po_sent").count() == 0
    _apply(db, [_order()], [_po(status="Open", order_date="2026-10-01", expected="2026-11-05")])
    assert db.query(OpsActivity).filter_by(event_type="po_recorded").count() == 1
    assert db.query(OpsActivity).filter_by(event_type="po_sent").one().body.startswith("PO-000956 sent")
    _apply(db, [_order()], [_po(status="Open", order_date="2026-10-01", expected="2026-11-05")])
    assert db.query(OpsActivity).filter_by(event_type="po_sent").count() == 1
    drafted = db.query(OpsActivity).filter_by(event_type="reminder_drafted").one()
    assert "has not been sent" in drafted.body
    work = purchasing_work(db, today=TODAY)
    assert work["reminders"][0]["po_number"] == "PO-000956"
    assert "needs_reply" not in {row["kind"] for row in work["actions"]}
    sent = []
    approve_message(db, work["reminders"][0]["id"], ACTOR, lambda message: sent.append(message), now=datetime(2026, 11, 3, 16))
    assert sent[0]["po_number"] == "PO-000956"
    assert db.query(OpsActivity).filter_by(event_type="reminder_sent").count() == 1

    _apply(
        db,
        [_order()],
        [_po(status="Open", order_date="2026-10-01", expected="2026-11-20")],
        acks=[{
            "po_number": "PO-000956",
            "status": "confirmed",
            "completion_date": "2026-11-14",
            "received_at": "2026-11-02T10:00:00",
            "vendor_order_no": "S-ORD1",
        }],
    )
    ack = db.query(OpsActivity).filter_by(event_type="ack_received").one()
    assert "S-ORD1" in ack.body
    assert "2026-11-14" in ack.body
    assert db.query(OpsActivity).filter_by(event_type="expected_date_changed").count() >= 1

    line = db.query(OpsTrackedLine).one()
    patch_line(db, line.id, {"source_code": "LYNX", "source_label": "Lynx"}, ACTOR, today=TODAY)
    sourcing = db.query(OpsActivity).filter_by(event_type="sourcing_changed").one()
    assert "Lynx" in sourcing.body
    assert sourcing.actor_email == "joey@opendc.ca"

    note = add_note(db, {
        "body": "Ian says package waiting for waybill",
        "po_number": "PO-000956",
        "follow_up_on": "2026-11-06",
    }, ACTOR)
    assert note["event_type"] == "note"
    assert note["vendor_name"] == "Upwardor"
    follow = db.query(OpsActionItem).filter_by(kind="follow_up", status="open").one()
    assert follow.po_number == "PO-000956"
    found = list_activity(db, vendor="upward", q="waybill")
    assert [row["id"] for row in found["activity"]] == [note["id"]]
    again = purchasing_work(db, today=TODAY)
    assert any(row["kind"] == "follow_up" for row in again["actions"])


def _line(item, description, qty=1, line_no=10000):
    return {
        "line_no": line_no, "item_no": item, "description": description,
        "quantity": qty, "shipped_quantity": 0, "line_type": "Item",
    }


def test_one_sales_order_shows_every_vendor_po_and_mail_moves_lifecycle():
    db = _db()
    order = _order(
        lines=None,
        extra_lines=None,
    )
    order["lines"] = [
        _line("PN10-WHT", "Door section"),
        _line("OP-LM", "Operator", line_no=20000),
        _line("TR02", "Track", line_no=30000),
    ]
    pos = [
        _po(number="PO-001078", vendor_number="ULTRA", vendor_name="Ultra-Lite", vendor_email="parts@ultralitedoors.ca", status="Draft", item="OP-LM", expected=""),
        _po(number="PO-001079", vendor_number="LYNX", vendor_name="Lynx", vendor_email="indervir.singh@lynx-nsw.com", status="Draft", item="PN10-WHT", expected=""),
        _po(number="PO-001080", vendor_number="NWD", vendor_name="Northwest Door", vendor_email="m.luong@hormann.ca", status="Draft", item="TR02", expected=""),
    ]
    for po, item in zip(pos, ("OP-LM", "PN10-WHT", "TR02")):
        po["lines"] = [{"item_no": item, "description": f"Built from SO-10421 {item}", "quantity": 1, "received_quantity": 0, "line_type": "Item"}]
    _apply(db, [order], pos)
    stored = db.query(OpsTrackedOrder).one()
    numbers = {row["po_number"] for row in stored.po_links_json}
    assert numbers == {"PO-001078", "PO-001079", "PO-001080"}
    assert all(row["lifecycle"] == "drafted" for row in stored.po_links_json)
    linked = {line.item_no: line.linked_po_number for line in db.query(OpsTrackedLine).all()}
    assert linked["OP-LM"] == "PO-001078"
    assert linked["TR02"] == "PO-001080"

    sent = [{
        "id": "sent-1078",
        "conversation_id": "thread-1078",
        "sent_at": "2026-11-01T15:04:00",
        "from_email": "joey@opendc.ca",
        "to_emails": ["parts@ultralitedoors.ca"],
        "subject": "PO-001078 Ultra-Lite",
        "body_text": "Please see attached PO-001078.pdf",
        "attachments": [{"name": "PO-001078.pdf"}],
        "web_link": "https://outlook.office.com/mail/sent/1078",
    }]
    apply_mailbox(db, {"available": True, "mailbox": "joey@opendc.ca", "sent": sent, "inbox": []})
    ultra = db.query(OpsTrackedPo).filter_by(po_number="PO-001078").one()
    assert ultra.lifecycle == "waiting_ack"
    assert ultra.sent_at is not None
    assert ultra.sent_source == "graph_sent"
    mailed = db.query(OpsActivity).filter_by(event_type="po_emailed", po_number="PO-001078").one()
    assert mailed.web_link.endswith("/1078")
    assert mailed.attachment_name == "PO-001078.pdf"

    reply = {
        "id": "reply-kaveh",
        "conversation_id": "thread-1078",
        "received_at": "2026-11-02T18:10:00",
        "from_email": "kaveh@ultralitedoors.ca",
        "subject": "Re: PO-001078",
        "body_text": "Order confirmation for PO-001078. Our order number UL-44921. Ship date November 14, 2026. OP-LM is backordered, 2 short. Price is now $410.",
        "attachments": [{"name": "UL-44921.pdf"}],
        "web_link": "https://outlook.office.com/mail/inbox/kaveh",
    }
    def stock(item_no):
        return {"qty": 3, "location": "Redcliff", "source": "item_card", "item_no": item_no}

    apply_mailbox(db, {"available": True, "mailbox": "joey@opendc.ca", "sent": sent, "inbox": [reply]}, stock_lookup=stock)
    ultra = db.query(OpsTrackedPo).filter_by(po_number="PO-001078").one()
    assert ultra.vendor_order_no == "UL-44921"
    assert ultra.expected_date == date(2026, 11, 14)
    assert ultra.ack_needs_review is True
    assert ultra.lifecycle == "issue"
    line = db.query(OpsTrackedLine).filter_by(item_no="OP-LM").one()
    assert line.missing_flag is True
    assert line.stock_qty == 3
    assert line.stock_location == "Redcliff"
    reply_row = db.query(OpsActivity).filter_by(event_type="supplier_reply").one()
    assert reply_row.attachment_name == "UL-44921.pdf"
    assert reply_row.needs_review is True

    # A second scan does not duplicate the sent or reply rows.
    apply_mailbox(db, {"available": True, "mailbox": "joey@opendc.ca", "sent": sent, "inbox": [reply]}, stock_lookup=stock)
    assert db.query(OpsActivity).filter_by(event_type="po_emailed", po_number="PO-001078").count() == 1
    assert db.query(OpsActivity).filter_by(event_type="supplier_reply").count() == 1

    lynx_reply = {
        "id": "lynx-1",
        "from_email": "indervir.singh@lynx-nsw.com",
        "subject": "PO-001079 confirmation",
        "body_text": "Our order number LX-88. Ship date 2026-11-20.",
        "web_link": "https://outlook.office.com/mail/inbox/lynx",
    }
    nwd_reply = {
        "id": "nwd-1",
        "from_email": "m.luong@hormann.ca",
        "subject": "Northwest Door PO-001080",
        "body_text": "Acknowledgement number NWD-17. Ship date 2026-11-18.",
    }
    apply_mailbox(db, {"available": True, "sent": [], "inbox": [lynx_reply, nwd_reply]})
    assert db.query(OpsTrackedPo).filter_by(po_number="PO-001079").one().vendor_order_no == "LX-88"
    assert db.query(OpsTrackedPo).filter_by(po_number="PO-001080").one().lifecycle == "acknowledged"

    # iControls has no PO number in the body; the vendor domain matches the one open iControls PO.
    ic = _po(number="PO-001090", vendor_number="IC", vendor_name="iControls", vendor_email="izinn@icontrols.ca", status="Open", item="PULSE", expected="")
    ic["lines"] = [{"item_no": "PULSE", "description": "iControls Pulse", "quantity": 1, "received_quantity": 0, "line_type": "Item"}]
    ic["external_document_number"] = "SO-10421"
    _apply(db, [order], pos + [ic])
    pulse = {
        "id": "pulse-1",
        "from_email": "izinn@icontrols.ca",
        "subject": "Pulse order",
        "body_text": "Your Pulse order is confirmed. Our order number IC-55. Ship date 2026-11-22.",
    }
    apply_mailbox(db, {"available": True, "sent": [], "inbox": [pulse]})
    assert db.query(OpsTrackedPo).filter_by(po_number="PO-001090").one().vendor_order_no == "IC-55"

    note_po_review_draft(db, "PO-001083", "Ultra-Lite", "https://outlook.office.com/mail/draft/1083")
    draft_row = db.query(OpsActivity).filter_by(event_type="po_draft_saved").one()
    assert "has not been sent" in draft_row.body
    parsed = extract_acknowledgement("Ship date November 2, 2026 only")
    assert parsed["needs_review"] is True
    assert parsed["confidence"] == "medium"

    view = list_tracker = None
    from app.services.ops_tracker_service import list_tracker
    rows = list_tracker(db, today=TODAY, po_status="waiting_ack")
    assert rows["orders"] == [] or all(
        "waiting_ack" in {po["lifecycle"] for po in order_row["purchase_orders"]}
        for order_row in rows["orders"]
    )
