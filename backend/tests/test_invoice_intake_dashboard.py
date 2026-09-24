"""Bookkeeper dashboard helpers for AI invoice intake."""
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.api.invoice_intake import describe_ai_action, pipeline_status, _row_to_dict
from app.config import Settings


def _row(**kwargs):
    defaults = dict(
        id=1,
        source_email_id="msg-1",
        source_email_received_at=None,
        sender_email="ap@vendor.com",
        attachment_filename="invoice.pdf",
        vendor_number="ACE",
        vendor_name_extracted="ACE Courier",
        vendor_invoice_number="INV-99",
        invoice_date=None,
        due_date=None,
        total_amount=120.50,
        currency_code="CAD",
        match_type="gl",
        matched_po_number=None,
        gl_account_suggested="502000",
        gl_confidence="high",
        review_flags=[],
        status="created",
        bc_invoice_id="guid",
        bc_invoice_number="P-INV000692",
        error_message=None,
        reviewed_by_user_id=None,
        reviewed_at=None,
        created_at=None,
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_describe_created_gl_draft():
    text = describe_ai_action(_row())
    assert "Extracted INV-99 from ACE Courier" in text
    assert "GL 502000" in text
    assert "BC Draft P-INV000692" in text


def test_describe_pending_unmatched_vendor():
    text = describe_ai_action(_row(
        status="pending",
        match_type="unmatched",
        bc_invoice_number=None,
        review_flags=["vendor_unmatched"],
    ))
    assert "waiting on bookkeeper" in text
    assert "vendor_unmatched" in text


def test_describe_duplicate_and_error():
    dup = describe_ai_action(_row(status="duplicate_skipped"))
    assert "Skipped duplicate INV-99" in dup
    err = describe_ai_action(_row(status="error", error_message="PDF unreadable", attachment_filename="scan.pdf"))
    assert "Failed processing scan.pdf" in err
    assert "PDF unreadable" in err


def test_row_to_dict_includes_ai_action_and_reviewer():
    payload = _row_to_dict(_row(), reviewer_name="Pat Bookkeeper")
    assert payload["ai_action"].startswith("Extracted INV-99")
    assert payload["reviewed_by_name"] == "Pat Bookkeeper"
    assert payload["bc_invoice_number"] == "P-INV000692"


def test_pipeline_defaults_to_accounting_mailbox_and_stays_off():
    info = pipeline_status()
    assert "enabled" in info
    assert info["creates_drafts_only"] is True
    assert info["posts_to_bc"] is False
    assert info["poll_interval_minutes"] == 30
    # Class default — production stays off until Graph Mail.Read is granted.
    assert Settings.model_fields["INVOICE_INTAKE_ENABLED"].default is False
    assert Settings.model_fields["INVOICE_INTAKE_MAILBOX"].default == "accounting@opendc.ca"
