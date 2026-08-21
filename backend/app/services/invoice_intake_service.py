"""
AI invoice intake — orchestrates the whole pipeline: monitored mailbox ->
Claude PDF extraction -> vendor/PO/GL matching -> duplicate check -> BC
Draft purchase invoice. Every invoice this creates lands in BC status
'Draft' — nothing is ever posted here; that's a deliberate human step in BC
itself. Anything the matcher isn't confident about (most often an unmatched
vendor, since the invoice header can't be created without a vendorId) is
recorded with status='pending' for manual resolution instead of guessed at.

See IncomingInvoice (app/db/models.py) for the tracking row shape and
invoice_matching_service for the matching logic itself.
"""

import base64
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import IncomingInvoice
from app.integrations.ai.client import ai_client
from app.integrations.bc.client import bc_client
from app.integrations.email.client import graph_client
from app.services.invoice_matching_service import invoice_matching_service

logger = logging.getLogger(__name__)

PDF_MIME_TYPES = {"application/pdf"}
IMAGE_MIME_TYPES = {"image/jpeg", "image/png", "image/tiff"}


def _parse_date(value: Optional[str]):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value[:10]).date()
    except ValueError:
        return None


def _parse_datetime(value: Optional[str]):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


class InvoiceIntakeService:

    def process_new_invoices(self, db: Session) -> Dict[str, Any]:
        """Poll the monitored mailbox for new invoice attachments and run
        each one through extraction, matching, and BC draft creation.
        Returns a summary dict for logging/the digest email."""
        mailbox = settings.INVOICE_INTAKE_MAILBOX or settings.EMAIL_INBOX_1
        if not mailbox:
            logger.warning("[InvoiceIntake] No mailbox configured (INVOICE_INTAKE_MAILBOX / EMAIL_INBOX_1)")
            return {"processed": 0, "error": "no mailbox configured"}

        summary = {"processed": 0, "created": 0, "pending": 0, "duplicate": 0, "error": 0}

        try:
            emails = graph_client.get_recent_emails(
                mailbox, hours=settings.INVOICE_INTAKE_LOOKBACK_HOURS, max_count=100
            )
        except Exception as e:
            logger.error(f"[InvoiceIntake] Failed to fetch emails from {mailbox}: {e}")
            return {"processed": 0, "error": str(e)}

        candidate_emails = [e for e in emails if e.get("hasAttachments")]
        if not candidate_emails:
            return summary

        # Pulled once per run, reused across every attachment in this batch.
        vendors = bc_client.get_vendors(top=1000)
        open_pos = bc_client.get_open_purchase_orders_with_lines()

        for email in candidate_emails:
            message_id = email.get("id")
            sender_email = ((email.get("from") or {}).get("emailAddress") or {}).get("address", "")
            received_at = email.get("receivedDateTime")

            try:
                attachments = graph_client.get_message_attachments(mailbox, message_id)
            except Exception as e:
                logger.error(f"[InvoiceIntake] Failed to fetch attachments for message {message_id}: {e}")
                continue

            for att in attachments:
                content_type = (att.get("contentType") or "").split(";")[0].strip().lower()
                filename = att.get("name") or "attachment"
                content_b64 = att.get("contentBytes")

                if content_type not in PDF_MIME_TYPES | IMAGE_MIME_TYPES or not content_b64:
                    continue  # not an invoice-shaped attachment, or a linked/reference attachment with no bytes

                existing = db.query(IncomingInvoice).filter_by(
                    source_email_id=message_id, attachment_filename=filename
                ).first()
                if existing:
                    continue  # already processed this exact attachment on a prior run

                result = self._process_attachment(
                    db, message_id, received_at, sender_email, filename, content_b64,
                    vendors, open_pos,
                )
                summary["processed"] += 1
                summary[result] = summary.get(result, 0) + 1

            try:
                graph_client.mark_as_read(mailbox, message_id)
            except Exception as e:
                logger.warning(f"[InvoiceIntake] Could not mark message {message_id} read: {e}")

        logger.info(f"[InvoiceIntake] Run complete: {summary}")
        return summary

    def _process_attachment(
        self, db: Session, message_id: str, received_at: Optional[str], sender_email: str,
        filename: str, content_b64: str, vendors: List[Dict[str, Any]], open_pos: List[Dict[str, Any]],
    ) -> str:
        """Process one attachment end to end. Returns the summary bucket key
        this attachment landed in ('created', 'pending', 'duplicate', 'error')."""
        row = IncomingInvoice(
            source_email_id=message_id,
            source_email_received_at=_parse_datetime(received_at),
            sender_email=sender_email,
            attachment_filename=filename,
            status="pending",
        )

        try:
            pdf_bytes = base64.b64decode(content_b64)
        except Exception as e:
            row.status, row.error_message = "error", f"Attachment decode failed: {e}"
            db.add(row); db.commit()
            return "error"

        extraction = ai_client.extract_invoice_from_pdf(pdf_bytes, filename)
        if not extraction.get("success"):
            row.status, row.error_message = "error", extraction.get("error", "extraction failed")
            db.add(row); db.commit()
            return "error"

        data = extraction["data"]
        row.extracted_json = data
        row.vendor_name_extracted = (data.get("vendor") or {}).get("name")
        row.vendor_invoice_number = data.get("invoice_number")
        row.invoice_date = _parse_date(data.get("invoice_date"))
        row.due_date = _parse_date(data.get("due_date"))
        row.total_amount = data.get("total_amount")
        row.currency_code = data.get("currency")

        vendor, vendor_conf = invoice_matching_service.match_vendor(
            sender_email, row.vendor_name_extracted, vendors
        )
        review_flags: List[str] = []
        if not vendor:
            review_flags.append("vendor_unmatched")
            row.review_flags = review_flags
            db.add(row); db.commit()
            return "pending"

        row.vendor_id = vendor.get("id")
        row.vendor_number = vendor.get("number")
        if vendor_conf != "high":
            review_flags.append(f"vendor_match_confidence_{vendor_conf}")

        # Duplicate check — local DB first (cheap), then BC as a safety net
        # for invoices entered by a human outside this pipeline.
        if row.vendor_invoice_number:
            dup = db.query(IncomingInvoice).filter_by(
                vendor_number=row.vendor_number,
                vendor_invoice_number=row.vendor_invoice_number,
                status="created",
            ).first()
            if not dup:
                try:
                    dup_bc = bc_client.find_purchase_invoice_by_vendor_invoice_number(
                        row.vendor_id, row.vendor_invoice_number
                    )
                except Exception as e:
                    logger.warning(f"[InvoiceIntake] BC duplicate check failed: {e}")
                    dup_bc = None
                if dup_bc:
                    dup = True
            if dup:
                row.status = "duplicate_skipped"
                db.add(row); db.commit()
                return "duplicate"

        return self._match_and_create(db, row, data, open_pos, review_flags)

    def resolve_pending(self, db: Session, row_id: int, vendor_number: str) -> Dict[str, Any]:
        """Manually resolve a 'pending' row (almost always vendor_unmatched)
        by supplying the correct BC vendor number, then re-run PO/GL matching
        and BC draft creation from the row's already-extracted data. Used by
        the admin review endpoint — no re-extraction, no re-download."""
        row = db.query(IncomingInvoice).get(row_id)
        if not row:
            return {"success": False, "error": "not found"}
        if row.status not in ("pending", "error"):
            return {"success": False, "error": f"row status is '{row.status}', not resolvable"}

        vendors = bc_client.get_vendors(top=1000)
        vendor = next((v for v in vendors if (v.get("number") or "").upper() == vendor_number.upper()), None)
        if not vendor:
            return {"success": False, "error": f"no BC vendor with number '{vendor_number}'"}

        row.vendor_id = vendor.get("id")
        row.vendor_number = vendor.get("number")
        row.error_message = None
        review_flags = ["vendor_resolved_manually"]

        data = row.extracted_json or {}
        open_pos = bc_client.get_open_purchase_orders_with_lines()
        outcome = self._match_and_create(db, row, data, open_pos, review_flags)
        return {"success": outcome == "created", "outcome": outcome, "bc_invoice_number": row.bc_invoice_number}

    def _match_and_create(
        self, db: Session, row: IncomingInvoice, data: Dict[str, Any],
        open_pos: List[Dict[str, Any]], review_flags: List[str],
    ) -> str:
        """Shared tail of the pipeline: PO/GL match -> build lines -> create
        the BC Draft invoice. Assumes row.vendor_id/vendor_number are already
        set. Returns the same outcome-bucket strings as _process_attachment."""
        po_match, po_conf = invoice_matching_service.match_purchase_order(
            row.vendor_number, data.get("po_number_referenced"), row.total_amount, open_pos
        )
        gl_account, gl_conf = invoice_matching_service.suggest_gl_account(row.vendor_number)

        if po_match and po_conf in ("high", "medium"):
            row.match_type = "po"
            row.matched_po_number = po_match.get("number")
            if po_conf != "high":
                review_flags.append("po_match_by_amount_only")
            lines = self._build_po_lines(po_match)
            review_flags.append("po_lines_not_line_reconciled")  # v1: copies PO lines as-is, doesn't reconcile against extracted line items
        elif gl_account and gl_conf == "high":
            row.match_type = "gl"
            row.gl_account_suggested = gl_account
            row.gl_confidence = gl_conf
            lines = self._build_gl_line(row, data)
        else:
            row.match_type = "unmatched"
            if po_match:
                review_flags.append("po_match_ambiguous")
            if gl_account:
                review_flags.append(f"gl_suggestion_low_confidence_{gl_account}")
            else:
                review_flags.append("no_po_or_gl_signal")
            row.status = "pending"
            row.review_flags = review_flags
            db.add(row); db.commit()
            return "pending"

        try:
            created = bc_client.create_purchase_invoice({
                "vendorId": row.vendor_id,
                "vendorInvoiceNumber": row.vendor_invoice_number or "",
                "invoiceDate": data.get("invoice_date") or datetime.utcnow().date().isoformat(),
                "dueDate": data.get("due_date") or None,
            })
            invoice_id = created["id"]
            for line in lines:
                bc_client.add_purchase_invoice_line(invoice_id, line)

            row.bc_invoice_id = invoice_id
            row.bc_invoice_number = created.get("number")
            row.status = "created"
            row.review_flags = review_flags
            db.add(row); db.commit()
            return "created"
        except Exception as e:
            logger.error(f"[InvoiceIntake] BC invoice creation failed for row {row.id}: {e}")
            row.status, row.error_message = "error", str(e)
            db.add(row); db.commit()
            return "error"

    @staticmethod
    def _build_po_lines(po: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Copy the matched PO's outstanding lines onto the invoice as Item
        lines. v1 does not reconcile these against the extracted invoice line
        items — flagged via 'po_lines_not_line_reconciled' so a human
        confirms quantities/prices against the actual invoice before posting."""
        lines = []
        for ln in po.get("purchaseOrderLines", []):
            if ln.get("lineType") != "Item":
                continue
            outstanding = float(ln.get("quantity") or 0) - float(ln.get("receivedQuantity") or 0)
            if outstanding <= 0:
                continue
            lines.append({
                "lineType": "Item",
                "lineObjectNumber": ln.get("lineObjectNumber"),
                "description": ln.get("description") or "",
                "quantity": outstanding,
                "unitCost": ln.get("unitCost") or ln.get("directUnitCost") or 0,
            })
        return lines

    @staticmethod
    def _build_gl_line(row: IncomingInvoice, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """One aggregate Account line for the whole invoice — GL-coded
        invoices (utilities, subscriptions, fees) are typically not
        itemized in the books the way stock purchases are."""
        amount = data.get("subtotal") or data.get("total_amount") or 0
        return [{
            "lineType": "Account",
            "lineObjectNumber": row.gl_account_suggested,
            "description": f"AI-coded from vendor history: {row.vendor_name_extracted or row.vendor_number} "
                            f"invoice {row.vendor_invoice_number or '(no invoice #)'}",
            "quantity": 1,
            "unitCost": amount,
        }]


invoice_intake_service = InvoiceIntakeService()
