"""Customer purchase-order emails trigger the existing quote-to-order conversion.

The switch defaults to off. These tests turn it on or to shadow. Business
Central is a recorder: the only writes allowed in on mode are the quote
external-document PATCH and makeOrder.
"""
from __future__ import annotations

import base64
import os
import sys
from datetime import datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.db.models import (
    AppSettings,
    AuditTrail,
    EmailLog,
    OpsActionItem,
    OpsActivity,
    QuotePoIntake,
    QuoteRequest,
    SalesOrder,
)
from app.services.email_monitor import EmailMonitorService
from app.services.inbox_settings import set_inbox_mode
from app.services.quote_po_auto_convert import (
    accept_quote_po,
    business_hours_between,
    dismiss_quote_po,
    handle_quote_po_email,
    list_quote_po_intakes,
    missed_purchase_orders,
)


def _engine():
    engine = create_engine(
        "sqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    for model in (
        EmailLog, AppSettings, QuoteRequest, QuotePoIntake, SalesOrder,
        AuditTrail, OpsActivity, OpsActionItem,
    ):
        model.__table__.create(engine, checkfirst=True)
    return engine


@pytest.fixture
def session():
    db = sessionmaker(bind=_engine(), autoflush=False, autocommit=False)()
    try:
        yield db
    finally:
        db.close()


class Bc:
    def __init__(self):
        self.writes = []
        self.reads = []

    def get_sales_quote_by_number(self, number, company_id=None):
        self.reads.append(("GET", "salesQuotes", number))
        return {
            "id": "guid-quote",
            "number": number,
            "status": "Open",
            "@odata.etag": 'W/"1"',
        }

    def get_sales_quotes(self, **kwargs):
        self.reads.append(("GET", "salesQuotes-page", kwargs))
        return []

    def update_sales_quote(self, quote_id, data, etag="*", company_id=None):
        self.writes.append(("PATCH", "salesQuotes", quote_id, dict(data)))
        return data

    def convert_quote_to_order(self, quote_id, company_id=None, *, allow_manual_fallback=True):
        self.writes.append(("POST", "makeOrder", quote_id, allow_manual_fallback))
        return {
            "id": "guid-so",
            "number": "SO-100",
            "customerId": "cust",
            "customerName": "Acme",
            "totalAmountIncludingTax": 1500,
            "externalDocumentNumber": "44521",
        }


@pytest.fixture
def bc(monkeypatch):
    client = Bc()
    monkeypatch.setattr("app.integrations.bc.client.bc_client", client)
    monkeypatch.setattr("app.services.order_lifecycle_service.bc_client", client)
    return client


def _log(session, message_id="mail-1", sender="buyer@acme.test", subject="PO", body="See attached"):
    row = EmailLog(
        message_id=message_id,
        received_at=datetime(2026, 11, 13, 15, 0),
        from_address=sender,
        subject=subject,
        body=body,
        status="parsed",
        referenced_quote_number="SQ-9999",
    )
    session.add(row)
    session.flush()
    return row


def _quote(session, number, sender="buyer@acme.test", total="1500.00", status="bc_created", customer="Acme", lines=None):
    log = _log(session, message_id=f"quote-{number}-{sender}", sender=sender)
    data = {"total": total}
    if lines:
        data["lines"] = lines
    row = QuoteRequest(
        email_id=log.id,
        customer_name=customer,
        contact_email=sender,
        status=status,
        bc_quote_id=number,
        parsed_data=data,
        created_at=datetime(2026, 11, 1, 12, 0),
    )
    session.add(row)
    session.commit()
    return row


def _po(subject="Purchase order", body="Purchase order 44521 for quote SQ-1001. Total $1,500.00."):
    return subject, body


def test_exact_quote_match_converts_with_only_two_bc_writes(session, bc):
    set_inbox_mode(session, "quote_po_auto_convert", "on")
    quote = _quote(session, "SQ-1001")
    log = _log(session, message_id="po-1", body="ignored by the matcher")
    subject, body = _po()
    row = handle_quote_po_email(
        session,
        email_log=log,
        subject=subject,
        body=body,
        from_address="buyer@acme.test",
        graph_message_id="graph-exact",
        mailbox="joey@opendc.ca",
    )
    assert row.status == "converted"
    assert row.bc_quote_number == "SQ-1001"
    assert row.bc_order_number == "SO-100"
    assert row.customer_po == "44521"
    assert log.referenced_quote_number == "SQ-9999"
    assert bc.writes == [
        ("PATCH", "salesQuotes", "guid-quote", {"externalDocumentNumber": "44521"}),
        ("POST", "makeOrder", "guid-quote", False),
    ]
    session.refresh(quote)
    assert quote.status == "converted_to_order"
    activity = session.query(OpsActivity).one()
    assert activity.so_number == "SO-100"
    assert "44521" in activity.body
    notice = session.query(OpsActionItem).one()
    assert notice.so_number == "SO-100"
    assert notice.kind == "quote_po_converted"


def test_customer_and_amount_matches_one_open_quote(session, bc):
    set_inbox_mode(session, "quote_po_auto_convert", "on")
    _quote(session, "SQ-1001", total="1500.00")
    _quote(session, "SQ-1002", total="900.00")
    log = _log(session, message_id="po-amount")
    row = handle_quote_po_email(
        session,
        email_log=log,
        subject="PO",
        body="Please enter purchase order 77881. Total $1,500.00.",
        from_address="buyer@acme.test",
        graph_message_id="graph-amount",
    )
    assert row.status == "converted"
    assert row.match_method == "customer_amount"
    assert row.bc_quote_number == "SQ-1001"
    assert [item[0] for item in bc.writes] == ["PATCH", "POST"]


def test_cross_customer_collision_goes_to_review(session, bc):
    set_inbox_mode(session, "quote_po_auto_convert", "on")
    _quote(session, "SQ-1001", sender="other@shop.test", customer="Other Shop")
    log = _log(session, message_id="po-cross")
    subject, body = _po()
    row = handle_quote_po_email(
        session,
        email_log=log,
        subject=subject,
        body=body,
        from_address="buyer@acme.test",
        graph_message_id="graph-cross",
    )
    assert row.status == "review"
    assert row.review_reason == "cross_customer"
    assert row.bc_order_number is None
    assert bc.writes == []
    listed = list_quote_po_intakes(session)
    assert listed[0]["review_reason"] == "cross_customer"
    assert "different customer" in listed[0]["review_reason_text"]


def test_ambiguous_amount_goes_to_review(session, bc):
    set_inbox_mode(session, "quote_po_auto_convert", "on")
    _quote(session, "SQ-1001", total="1500.00")
    _quote(session, "SQ-1002", total="1500.00")
    log = _log(session, message_id="po-amb")
    row = handle_quote_po_email(
        session,
        email_log=log,
        subject="PO",
        body="Purchase order 9001. Total $1,500.00.",
        from_address="buyer@acme.test",
        graph_message_id="graph-amb",
    )
    assert row.status == "review"
    assert row.review_reason == "ambiguous"
    assert row.bc_quote_number is None
    assert bc.writes == []
    assert {item["bc_quote_number"] for item in row.candidates} == {"SQ-1001", "SQ-1002"}


def test_mismatched_total_stays_in_review(session, bc):
    set_inbox_mode(session, "quote_po_auto_convert", "on")
    _quote(session, "SQ-1001", total="1500.00")
    log = _log(session, message_id="po-mismatch")
    row = handle_quote_po_email(
        session,
        email_log=log,
        subject="PO",
        body="Purchase order 44521 for quote SQ-1001. Total $900.00.",
        from_address="buyer@acme.test",
        graph_message_id="graph-mismatch",
    )
    assert row.status == "review"
    assert row.review_reason == "mismatched_total"
    assert bc.writes == []


def test_duplicate_email_converts_once(session, bc):
    set_inbox_mode(session, "quote_po_auto_convert", "on")
    _quote(session, "SQ-1001")
    log = _log(session, message_id="po-dup")
    subject, body = _po()
    kwargs = dict(
        email_log=log,
        subject=subject,
        body=body,
        from_address="buyer@acme.test",
        graph_message_id="graph-dup",
    )
    first = handle_quote_po_email(session, **kwargs)
    second = handle_quote_po_email(session, **kwargs)
    assert first.id == second.id
    assert first.bc_order_number == "SO-100"
    assert len(bc.writes) == 2
    again = _log(session, message_id="po-dup-2")
    third = handle_quote_po_email(
        session,
        email_log=again,
        subject=subject,
        body=body,
        from_address="buyer@acme.test",
        graph_message_id="graph-dup-2",
    )
    assert third.status == "review"
    assert third.review_reason == "already_converted"
    assert len(bc.writes) == 2


def test_expired_quote_goes_to_review(session, bc):
    set_inbox_mode(session, "quote_po_auto_convert", "on")
    _quote(session, "SQ-1001", status="expired")
    log = _log(session, message_id="po-expired")
    subject, body = _po()
    row = handle_quote_po_email(
        session,
        email_log=log,
        subject=subject,
        body=body,
        from_address="buyer@acme.test",
        graph_message_id="graph-expired",
    )
    assert row.status == "review"
    assert row.review_reason == "expired"
    assert bc.writes == []


def test_already_converted_quote_is_not_converted_again(session, bc):
    set_inbox_mode(session, "quote_po_auto_convert", "on")
    quote = _quote(session, "SQ-1001", status="converted_to_order")
    session.add(SalesOrder(
        quote_request_id=quote.id,
        bc_order_number="SO-55",
        bc_order_id="guid-55",
        customer_name="Acme",
        status="confirmed",
    ))
    session.commit()
    log = _log(session, message_id="po-done")
    subject, body = _po()
    row = handle_quote_po_email(
        session,
        email_log=log,
        subject=subject,
        body=body,
        from_address="buyer@acme.test",
        graph_message_id="graph-done",
    )
    assert row.status == "review"
    assert row.review_reason == "already_converted"
    assert bc.writes == []


def test_shadow_makes_no_bc_writes(session, bc):
    set_inbox_mode(session, "quote_po_auto_convert", "shadow")
    _quote(session, "SQ-1001")
    log = _log(session, message_id="po-shadow")
    subject, body = _po()
    row = handle_quote_po_email(
        session,
        email_log=log,
        subject=subject,
        body=body,
        from_address="buyer@acme.test",
        graph_message_id="graph-shadow",
    )
    assert row.status == "shadow"
    assert row.confidence == "high"
    assert "SQ-1001" in row.planned_action
    assert "Would write" in row.planned_action
    assert bc.writes == []
    assert bc.reads == []
    listed = list_quote_po_intakes(session)
    assert listed[0]["id"] == row.id
    assert listed[0]["excerpt"]
    accepted = accept_quote_po(session, row.id, bc_quote_number=None, user_email="joey@opendc.ca")
    assert accepted["converted"] is False
    assert bc.writes == []


def test_off_does_nothing(session, bc):
    set_inbox_mode(session, "quote_po_auto_convert", "off")
    _quote(session, "SQ-1001")
    log = _log(session, message_id="po-off")
    subject, body = _po()
    row = handle_quote_po_email(
        session,
        email_log=log,
        subject=subject,
        body=body,
        from_address="buyer@acme.test",
        graph_message_id="graph-off",
    )
    assert row is None
    assert session.query(QuotePoIntake).count() == 0
    assert bc.writes == []
    assert bc.reads == []


def test_go_ahead_without_a_po_is_ignored(session, bc):
    set_inbox_mode(session, "quote_po_auto_convert", "on")
    _quote(session, "SQ-1001")
    log = _log(session, message_id="po-none")
    row = handle_quote_po_email(
        session,
        email_log=log,
        subject="Re: quote",
        body="Approved SQ-1001. Please proceed.",
        from_address="buyer@acme.test",
        graph_message_id="graph-none",
    )
    assert row is None
    assert bc.writes == []


def test_missed_po_safety_net(session):
    set_inbox_mode(session, "quote_po_auto_convert", "on")
    received = datetime(2026, 11, 9, 17, 0)  # Monday 10:00 America/Edmonton
    almost = datetime(2026, 11, 9, 20, 0)  # 3 business hours
    due = datetime(2026, 11, 9, 21, 0)  # 4 business hours
    assert business_hours_between(received, almost) == pytest.approx(3)
    assert business_hours_between(received, due) == pytest.approx(4)
    friday = datetime(2026, 11, 13, 23, 0)  # Friday 16:00 America/Edmonton
    sunday = datetime(2026, 11, 15, 18, 0)
    monday = datetime(2026, 11, 16, 18, 0)  # Monday 11:00, four hours later
    assert business_hours_between(friday, sunday) == pytest.approx(1)
    assert business_hours_between(friday, monday) == pytest.approx(4)

    log = _log(session, message_id="old-po")
    fresh = _log(session, message_id="new-po")
    done = _log(session, message_id="done-po")
    session.add(QuotePoIntake(
        graph_message_id="old",
        email_log_id=log.id,
        from_address="buyer@acme.test",
        subject="Old PO",
        received_at=received,
        customer_po="111",
        status="review",
        review_reason="ambiguous",
        confidence="low",
        excerpt="Purchase order 111",
        overdue=False,
        created_at=received,
    ))
    session.add(QuotePoIntake(
        graph_message_id="new",
        email_log_id=fresh.id,
        from_address="buyer@acme.test",
        subject="New PO",
        received_at=due,
        customer_po="222",
        status="review",
        confidence="low",
        excerpt="Purchase order 222",
        overdue=False,
        created_at=due,
    ))
    session.add(QuotePoIntake(
        graph_message_id="done",
        email_log_id=done.id,
        from_address="buyer@acme.test",
        subject="Done PO",
        received_at=received,
        customer_po="333",
        status="converted",
        bc_order_number="SO-9",
        overdue=False,
        created_at=received,
    ))
    session.commit()
    missed = missed_purchase_orders(session, now=due)
    assert [item["customer_po"] for item in missed] == ["111"]
    listed = list_quote_po_intakes(session, now=due)
    assert [item["customer_po"] for item in listed] == ["111", "222"]
    assert listed[0]["overdue"] is True
    assert listed[1]["overdue"] is False


def test_staff_can_fix_the_match_then_convert_or_dismiss(session, bc):
    set_inbox_mode(session, "quote_po_auto_convert", "on")
    _quote(session, "SQ-1001", total="1500.00")
    _quote(session, "SQ-1002", total="1500.00")
    log = _log(session, message_id="po-fix")
    row = handle_quote_po_email(
        session,
        email_log=log,
        subject="PO",
        body="Purchase order 9001. Total $1,500.00.",
        from_address="buyer@acme.test",
        graph_message_id="graph-fix",
    )
    assert row.review_reason == "ambiguous"
    kept = handle_quote_po_email(
        session,
        email_log=_log(session, message_id="po-dismiss"),
        subject="PO",
        body="Purchase order 4200.",
        from_address="stranger@elsewhere.test",
        graph_message_id="graph-dismiss",
    )
    assert kept.review_reason == "unknown_sender"
    dismiss_quote_po(session, kept.id, user_email="joey@opendc.ca")
    converted = accept_quote_po(
        session, row.id, bc_quote_number="SQ-1002", user_email="joey@opendc.ca",
    )
    assert converted["converted"] is True
    assert converted["bc_quote_number"] == "SQ-1002"
    assert converted["bc_order_number"] == "SO-100"
    assert [item[0] for item in bc.writes] == ["PATCH", "POST"]
    second = accept_quote_po(session, row.id, bc_quote_number="SQ-1002", user_email="joey@opendc.ca")
    assert second["already"] is True
    assert len(bc.writes) == 2
    listed = list_quote_po_intakes(session)
    assert listed == []


def test_second_email_does_not_make_order_while_the_quote_is_converting(session, bc):
    set_inbox_mode(session, "quote_po_auto_convert", "on")
    quote = _quote(session, "SQ-1001")
    holder_log = _log(session, message_id="holder-mail")
    session.add(QuotePoIntake(
        graph_message_id="holder",
        email_log_id=holder_log.id,
        from_address="buyer@acme.test",
        subject="First PO",
        received_at=datetime(2026, 11, 13, 16, 0),
        customer_po="11111",
        status="converting",
        bc_quote_number="SQ-1001",
        quote_request_id=quote.id,
        confidence="high",
        overdue=False,
        created_at=datetime(2026, 11, 13, 16, 0),
    ))
    session.commit()
    subject, body = _po()
    row = handle_quote_po_email(
        session,
        email_log=_log(session, message_id="second-mail"),
        subject=subject,
        body=body,
        from_address="buyer@acme.test",
        graph_message_id="graph-second",
    )
    assert row.status == "review"
    assert row.review_reason == "converting"
    assert bc.writes == []
    assert bc.reads == []
    duplicate = QuotePoIntake(
        graph_message_id="holder-2",
        email_log_id=holder_log.id,
        from_address="buyer@acme.test",
        subject="Also converting",
        received_at=datetime(2026, 11, 13, 16, 1),
        customer_po="22222",
        status="converting",
        bc_quote_number="SQ-1001",
        confidence="high",
        overdue=False,
        created_at=datetime(2026, 11, 13, 16, 1),
    )
    session.add(duplicate)
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_line_match_requires_the_same_sku(session, bc):
    set_inbox_mode(session, "quote_po_auto_convert", "on")
    _quote(session, "SQ-1001", lines=[{"sku": "TX45020"}])
    prefix = handle_quote_po_email(
        session,
        email_log=_log(session, message_id="po-prefix"),
        subject="PO",
        body="Purchase order 44521 for quote SQ-1001. Total $1,500.00. 2 x TX450",
        from_address="buyer@acme.test",
        graph_message_id="graph-prefix",
    )
    assert prefix.status == "review"
    assert prefix.review_reason == "mismatched_lines"
    assert bc.writes == []
    _quote(session, "SQ-1003", lines=[{"sku": "TX450"}])
    exact = handle_quote_po_email(
        session,
        email_log=_log(session, message_id="po-exact-sku"),
        subject="PO",
        body="Purchase order 55661 for quote SQ-1003. Total $1,500.00. 2 x TX450",
        from_address="buyer@acme.test",
        graph_message_id="graph-exact-sku",
    )
    assert exact.status == "converted"
    assert exact.bc_quote_number == "SQ-1003"
    assert [item[0] for item in bc.writes] == ["PATCH", "POST"]


def _pdf(text: str) -> bytes:
    from fpdf import FPDF
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=14)
    pdf.multi_cell(0, 8, text)
    return bytes(pdf.output())


def test_monitor_reads_the_po_pdf_and_ignores_the_ai_quote_number(session, bc, monkeypatch):
    set_inbox_mode(session, "quote_po_auto_convert", "on")
    session.commit()
    _quote(session, "SQ-1001")
    monkeypatch.setattr(
        "app.services.email_categorization_service.get_categorization_service",
        lambda db: SimpleNamespace(
            categorize_email=lambda subject, body, sender: {
                "category": "order_confirmation",
                "confidence": 0.99,
                "reasoning": "model says convert SQ-9999",
                "referenced_quote_number": "SQ-9999",
                "is_modification": False,
            }
        ),
    )
    service = EmailMonitorService()
    calls = {"attachments": 0}

    class Graph:
        def get_message_attachments(self, mailbox, message_id, **kwargs):
            calls["attachments"] += 1
            pdf = _pdf("Purchase order 44521\nQuote SQ-1001\nTotal $1,500.00")
            return [{
                "name": "PO-44521.pdf",
                "contentType": "application/pdf",
                "contentBytes": base64.b64encode(pdf).decode(),
            }]

    service.graph_client = Graph()
    result = service._process_single_email(
        session,
        {
            "id": "graph-pdf",
            "internetMessageId": "mid-pdf",
            "subject": "Order",
            "receivedDateTime": "2026-11-13T15:00:00Z",
            "from": {"emailAddress": {"address": "buyer@acme.test", "name": "Buyer"}},
            "body": {"content": "Please see the attached purchase order."},
        },
        "joey@opendc.ca",
    )
    assert result == "other"
    assert calls["attachments"] == 1
    row = session.query(QuotePoIntake).filter(QuotePoIntake.graph_message_id == "graph-pdf").one()
    assert row.status == "converted"
    assert row.bc_quote_number == "SQ-1001"
    assert row.customer_po == "44521"
    email = session.query(EmailLog).filter(EmailLog.message_id == "mid-pdf").one()
    assert email.referenced_quote_number == "SQ-9999"
    assert [item[0] for item in bc.writes] == ["PATCH", "POST"]
