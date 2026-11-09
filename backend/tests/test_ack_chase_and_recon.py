"""Acknowledgement chase, Upwardor reconciliation, and customer-update triggers.

No live Business Central or Graph calls. Mail leaves the process only when a
test calls approve_message with a fake sender.
"""
from __future__ import annotations

import io
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from openpyxl import Workbook
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.models import (
    OpsActionItem,
    OpsActivity,
    OpsFieldAudit,
    OpsOutboundMessage,
    OpsTrackedLine,
    OpsTrackedOrder,
    OpsTrackedPo,
    OpsTrackerMeta,
    UpwardorReconRun,
)
from app.services.alberta_business_days import add_business_days, is_alberta_business_day
from app.services.ops_tracker_service import (
    Actor,
    apply_snapshot,
    approve_message,
    reject_message,
    snooze_ack,
)
from app.services.upwardor_open_order_recon import (
    compare_runs,
    import_upwardor_recon,
    parse_open_order_payload,
    reconcile_open_orders,
)

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
        UpwardorReconRun.__table__,
    ):
        table.create(engine)
    return sessionmaker(bind=engine)()


def _order(number="SO-10421", **extra):
    body = {
        "number": number,
        "id": "guid-" + number,
        "customer_number": "C100",
        "customer_name": "Prairie Door Co",
        "customer_email": "pat@prairiedoor.ca",
        "external_document_number": "LOT-18",
        "order_date": "2026-10-01",
        "status": "Open",
        "fully_shipped": False,
        "lines": [{
            "line_no": 10000,
            "item_no": "PN10",
            "description": "Insulated panel",
            "quantity": 2,
            "shipped_quantity": 0,
            "line_type": "Item",
        }],
    }
    body.update(extra)
    return body


def _po(number="PO-001066", so="SO-10421", order_date="2026-10-27", expected="2026-11-30", status="Open", **extra):
    body = {
        "number": number,
        "vendor_number": "UPW",
        "vendor_name": "Upwardor",
        "vendor_email": "orders@upwardor.com",
        "status": status,
        "order_date": order_date,
        "expected_date": expected,
        "external_document_number": so,
        "lines": [{
            "item_no": "PN10",
            "description": f"Built from {so}",
            "quantity": 2,
            "received_quantity": 0,
            "line_type": "Item",
        }],
    }
    body.update(extra)
    return body


def _apply(db, orders, purchase_orders, today=TODAY, acks=None):
    return apply_snapshot(
        db,
        {"orders": orders, "purchase_orders": purchase_orders, "vendors": [], "acks": acks or [], "receipts": []},
        actor=SYNC,
        today=today,
    )


def _pending(db, kind):
    return (
        db.query(OpsOutboundMessage)
        .filter(OpsOutboundMessage.kind == kind, OpsOutboundMessage.status == "pending")
        .all()
    )


def test_two_business_days_skips_the_weekend_and_remembrance_day():
    assert add_business_days(date(2026, 10, 30), 2) == date(2026, 11, 3)
    assert is_alberta_business_day(date(2026, 11, 11)) is False

    db = _db()
    # Sent Friday. Monday is one business day, not two.
    _apply(db, [_order()], [_po(order_date="2026-10-30", expected="2026-11-30")], today=date(2026, 11, 2))
    assert db.query(OpsActionItem).filter_by(kind="missing_ack", status="open").count() == 0
    assert _pending(db, "supplier_reminder") == []

    _apply(db, [_order()], [_po(order_date="2026-10-30", expected="2026-11-30")], today=date(2026, 11, 3))
    assert db.query(OpsActionItem).filter_by(kind="missing_ack", status="open").count() == 1
    chase = _pending(db, "supplier_reminder")
    assert len(chase) == 1
    assert "PO-001066" in chase[0].body_text
    assert "October 30, 2026" in chase[0].body_text
    assert "November 30, 2026" in chase[0].body_text
    assert "acknowledgement" in chase[0].body_text.lower()
    assert "ship date" in chase[0].body_text.lower()
    drafted = db.query(OpsActivity).filter_by(event_type="reminder_drafted", po_number="PO-001066").one()
    assert "has not been sent" in drafted.body

    # Outlook send date wins over an older BC order date.
    po = db.query(OpsTrackedPo).one()
    po.sent_at = datetime(2026, 10, 30, 15, 0)
    po.order_date = date(2026, 10, 1)
    db.commit()
    _apply(db, [_order()], [_po(order_date="2026-10-01", expected="2026-11-30")], today=date(2026, 11, 2))
    assert db.query(OpsActionItem).filter_by(kind="missing_ack", status="open").count() == 0

    # Sent Monday Nov 9. Wednesday is Remembrance Day, so the second business day is Thursday.
    db2 = _db()
    _apply(db2, [_order()], [_po(order_date="2026-11-09")], today=date(2026, 11, 11))
    assert db2.query(OpsActionItem).filter_by(kind="missing_ack", status="open").count() == 0
    _apply(db2, [_order()], [_po(order_date="2026-11-09")], today=date(2026, 11, 12))
    assert db2.query(OpsActionItem).filter_by(kind="missing_ack", status="open").count() == 1


def test_snooze_hides_the_flag_until_the_follow_up_date():
    db = _db()
    _apply(db, [_order()], [_po(order_date="2026-10-27")])
    assert db.query(OpsActionItem).filter_by(kind="missing_ack", status="open").count() == 1
    snooze_ack(db, "PO-001066", "2026-11-10", ACTOR, today=TODAY)
    db.commit()
    assert db.query(OpsActionItem).filter_by(kind="missing_ack", status="open").count() == 0
    assert _pending(db, "supplier_reminder") == []
    assert db.query(OpsActivity).filter_by(event_type="ack_snoozed").count() == 1
    follow = db.query(OpsActionItem).filter_by(kind="follow_up", status="open").one()
    assert follow.po_number == "PO-001066"

    _apply(db, [_order()], [_po(order_date="2026-10-27")], today=date(2026, 11, 10))
    assert db.query(OpsActionItem).filter_by(kind="missing_ack", status="open").count() == 1


def test_chase_send_is_logged_and_not_automatic():
    db = _db()
    sent = []
    _apply(db, [_order()], [_po(order_date="2026-10-27", expected="2026-11-30")])
    message = _pending(db, "supplier_reminder")[0]
    assert sent == []
    approve_message(db, message.id, ACTOR, lambda row: sent.append(row), now=datetime(2026, 11, 3, 9))
    db.commit()
    assert len(sent) == 1
    assert db.query(OpsActivity).filter_by(event_type="reminder_sent", po_number="PO-001066").count() == 1


def test_reconciliation_reports_each_exception_and_compares_runs():
    ours = [
        {"po_number": "PO-001100", "vendor_number": "UPW", "vendor_name": "Upwardor", "status": "Open",
         "bc_open": True, "fully_received": False, "ack_status": "none", "vendor_order_no": None, "so_numbers": ["SO-1"]},
        {"po_number": "PO-001101", "vendor_number": "UPW", "vendor_name": "Upwardor", "status": "Open",
         "bc_open": True, "fully_received": True, "receipt_date": "2026-10-20", "ack_status": "acknowledged",
         "vendor_order_no": "S-ORD116101", "so_numbers": ["SO-2"]},
        {"po_number": "PO-001102", "vendor_number": "UPW", "vendor_name": "Upwardor", "status": "Open",
         "bc_open": True, "fully_received": False, "ack_status": "acknowledged", "vendor_order_no": "S-ORD116102",
         "so_numbers": ["SO-3"]},
        {"po_number": "PO-001103", "vendor_number": "UPW", "vendor_name": "Upwardor", "status": "Open",
         "bc_open": True, "fully_received": False, "ack_status": "none", "vendor_order_no": None, "so_numbers": ["SO-4"]},
        {"po_number": "PO-001104", "vendor_number": "UPW", "vendor_name": "Upwardor", "status": "Open",
         "bc_open": True, "fully_received": False, "ack_status": "acknowledged", "vendor_order_no": "S-ORD116104",
         "so_numbers": ["SO-5"]},
        {"po_number": "PO-009999", "vendor_number": "LYNX", "vendor_name": "Lynx", "status": "Open",
         "bc_open": True, "fully_received": False, "ack_status": "none", "vendor_order_no": None, "so_numbers": []},
    ]
    theirs = [
        {"sord": "S-ORD116999", "po_number": None, "po_key": None, "part": "PN10", "description": "Panel", "qty": "2", "date": "2026-11-30", "source_row": 2},
        {"sord": "S-ORD116101", "po_number": "PO-001101", "po_key": "1101", "part": "PN10", "description": "Received", "qty": "1", "date": None, "source_row": 3},
        {"sord": None, "po_number": "PO-001102", "po_key": "1102", "part": "PN12", "description": "No ack on their sheet", "qty": "1", "date": None, "source_row": 4},
        {"sord": "S-ORD116103", "po_number": "PO-001103", "po_key": "1103", "part": "PN14", "description": "They have it", "qty": "4", "date": "2026-12-01", "source_row": 5},
        {"sord": "S-ORD116104", "po_number": "PO-001104", "po_key": "1104", "part": "PN16", "description": "Clean", "qty": "1", "date": None, "source_row": 6},
    ]
    report = reconcile_open_orders(theirs, ours)
    kinds = {}
    for row in report["exceptions"]:
        kinds.setdefault(row["type"], []).append(row["po_number"] or row["sord"])
    assert "S-ORD116999" in kinds["their_sord_no_po"]
    assert "PO-001100" in kinds["our_open_po_missing"]
    assert "PO-001101" in kinds["received_still_open"]
    assert "PO-001102" in kinds["ack_we_have_they_dont"]
    assert "PO-001103" in kinds["ack_they_have_we_dont"]
    assert "PO-001104" not in {value for values in kinds.values() for value in values}
    assert "PO-009999" not in {value for values in kinds.values() for value in values}
    assert all(row["suggested_action"] for row in report["exceptions"])

    later = reconcile_open_orders(theirs[1:], ours)
    delta = compare_runs({"id": 1, "created_at": "2026-11-02T08:00:00", "exceptions": report["exceptions"]}, later)
    assert any(key.startswith("their_sord_no_po|") and "S-ORD116999" in key for key in delta["cleared_keys"])
    assert delta["cleared_count"] >= 1


def test_reconciliation_parses_odd_headers_excel_and_stores_the_run():
    pasted = "Order\tRef\tPart\nS-ORD116500\t1066\tPN10\nS-ORD116501\t\tPN12\n"
    parsed = parse_open_order_payload(pasted.encode("utf-8"), filename="paste.csv")
    assert parsed["rows"][0]["sord"] == "S-ORD116500"
    assert parsed["rows"][0]["po_number"] == "PO-001066"
    assert parsed["rows"][1]["sord"] == "S-ORD116501"

    book = Workbook()
    sheet = book.active
    sheet.append(["Notes"])
    sheet.append(["Sales Order No.", "Customer PO", "Part No.", "Ship Date"])
    sheet.append(["SORD116200", "PO-001200", "PN10", "2026-11-30"])
    buffer = io.BytesIO()
    book.save(buffer)
    excel = parse_open_order_payload(buffer.getvalue(), filename="upwardor.xlsx")
    assert excel["rows"][0]["sord"] == "S-ORD116200"
    assert excel["rows"][0]["po_number"] == "PO-001200"
    assert "Sales Order No." in excel["column_map"]["sord"]

    db = _db()
    _apply(db, [_order()], [_po(number="PO-001200", order_date="2026-10-01")])
    db.commit()
    first = import_upwardor_recon(db, buffer.getvalue(), filename="week1.xlsx", source="upload", actor=ACTOR)
    db.commit()
    assert first["id"] == 1
    assert first["comparison"]["previous_run_id"] is None
    second_csv = "Sales Order No.,Customer PO\nS-ORD116999,\n"
    second = import_upwardor_recon(db, second_csv.encode("utf-8"), filename=None, source="paste", actor=ACTOR)
    db.commit()
    assert second["previous_run_id"] == first["id"]
    assert second["comparison"]["new_count"] >= 1
    assert db.query(UpwardorReconRun).count() == 2


def test_overdue_promise_drafts_once_and_a_later_po_date_hooks_the_timeline():
    db = _db()
    sent = []
    order = _order(promised_date="2026-10-15", shipment_date="2026-10-20")
    _apply(db, [order], [_po(number="PO-000956", order_date="2026-10-02", expected="2026-11-20")])
    queued = _pending(db, "customer_update")
    assert len(queued) == 1
    assert queued[0].to_email == "pat@prairiedoor.ca"
    assert "2026-10-15" in queued[0].body_text
    assert "LOT-18" in queued[0].body_text
    assert "PO-000956" not in queued[0].body_text
    assert queued[0].context_json["po_numbers"] == ["PO-000956"]
    assert "PN10" in queued[0].body_text
    assert "Sorry" in queued[0].body_text
    assert db.query(OpsActionItem).filter_by(kind="customer_update", status="open").count() == 1
    assert db.query(OpsActivity).filter_by(event_type="customer_update_drafted").count() == 1

    _apply(db, [order], [_po(number="PO-000956", order_date="2026-10-02", expected="2026-11-20")])
    assert len(_pending(db, "customer_update")) == 1

    reject_message(db, queued[0].id, ACTOR)
    db.commit()
    _apply(db, [order], [_po(number="PO-000956", order_date="2026-10-02", expected="2026-11-20")])
    assert _pending(db, "customer_update") == []
    assert sent == []

    # A new promised date is a new trigger.
    moved = _order(promised_date="2026-10-28", shipment_date=None)
    _apply(db, [moved], [_po(number="PO-000956", order_date="2026-10-02", expected="2026-11-20")])
    again = _pending(db, "customer_update")
    assert len(again) == 1
    assert "2026-10-28" in again[0].body_text

    # Linked PO date moves later. The order already has an earlier date on another PO,
    # so the sales-order expected date does not move. The timeline event still drafts.
    db2 = _db()
    early = _po(number="PO-000956", order_date="2026-10-02", expected="2026-11-05")
    late = _po(number="PO-001066", order_date="2026-10-02", expected="2026-11-20")
    _apply(db2, [_order()], [early, late])
    assert _pending(db2, "customer_update") == []
    _apply(db2, [_order()], [early, _po(number="PO-001066", order_date="2026-10-02", expected="2026-11-28")])
    slip = _pending(db2, "customer_update")
    assert len(slip) == 1
    assert slip[0].context_json["trigger"] == "po_slip"
    assert slip[0].context_json["po_numbers"] == ["PO-001066"]
    assert "LOT-18" in slip[0].body_text
    assert "PO-001066" not in slip[0].body_text
    assert "2026-11-20" in slip[0].body_text
    assert "2026-11-28" in slip[0].body_text
    assert db2.query(OpsActivity).filter_by(event_type="expected_date_changed", po_number="PO-001066").count() == 1

    approve_message(db2, slip[0].id, ACTOR, lambda row: sent.append(row))
    db2.commit()
    assert len(sent) == 1
    logged = db2.query(OpsActivity).filter_by(event_type="customer_update_sent").all()
    assert {row.po_number for row in logged} == {"PO-001066"}
    assert {row.so_number for row in logged} == {"SO-10421"}
    _apply(db2, [_order()], [early, _po(number="PO-001066", order_date="2026-10-02", expected="2026-11-28")])
    assert _pending(db2, "customer_update") == []


def test_shipped_order_does_not_keep_an_overdue_draft():
    db = _db()
    order = _order(promised_date="2026-10-01")
    _apply(db, [order], [_po()])
    assert len(_pending(db, "customer_update")) == 1
    order["fully_shipped"] = True
    _apply(db, [order], [_po()])
    assert _pending(db, "customer_update") == []
