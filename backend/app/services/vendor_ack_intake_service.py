"""Upwardor order-acknowledgement intake.

Polls joey@opendc.ca and Finance@opendc.ca (configurable) the same way
invoice intake polls its mailbox: a scheduled lookback, not a Graph
subscription. Each confirmation PDF becomes one vendor_order_acks row,
upserted on (vendor_no, vendor_order_no) so a revision replaces the prior
row. The email+attachment pair is recorded in vendor_order_ack_sources so
the same PDF is never parsed twice.

BC write-back sets Vendor Order No. on the purchase order (the field on
the PO card). Failures are stored on the row and retried next run; they
never roll back the acknowledgement. Split POs (PO-000960(2)) are stored
and shown on the schedule but are not written onto the primary PO.

Nothing in this module sends mail.
"""

from __future__ import annotations

import base64
import logging
import subprocess
import tempfile
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import VendorOrderAck, VendorOrderAckSource
from app.integrations.bc.client import bc_client
from app.integrations.email.client import graph_client
from app.services.vendor_ack_parser import (
    email_body_text,
    is_candidate_email,
    parse_acknowledgement,
    po_base,
    po_suffix,
)

logger = logging.getLogger(__name__)

PDF_MIME_TYPES = {"application/pdf", "application/octet-stream", "application/x-pdf"}
_ACTIVE = ("confirmed", "revised", "cancelled")


def _parse_datetime(value: Optional[str]) -> Optional[datetime]:
    """Graph receivedDateTime → naive UTC (portal DateTime columns are naive)."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed
    from datetime import timezone
    return parsed.astimezone(timezone.utc).replace(tzinfo=None)


def pdf_bytes_to_text(pdf_bytes: bytes) -> str:
    """Extract text with poppler ``pdftotext``. Empty string if it is missing
    or the file is not a readable PDF — the caller still parses subject,
    body, and filename."""
    if not pdf_bytes:
        return ""
    path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as handle:
            handle.write(pdf_bytes)
            path = handle.name
        proc = subprocess.run(
            ["pdftotext", "-layout", path, "-"],
            capture_output=True,
            timeout=30,
            check=False,
        )
        if proc.returncode != 0:
            logger.warning(
                "[VendorAck] pdftotext failed (%s): %s",
                proc.returncode,
                (proc.stderr or b"")[:300],
            )
            return ""
        return proc.stdout.decode("utf-8", errors="replace")
    except FileNotFoundError:
        logger.warning("[VendorAck] pdftotext is not installed; using subject/filename only")
        return ""
    except Exception as exc:
        logger.warning("[VendorAck] PDF text extraction failed: %s", exc)
        return ""
    finally:
        if path:
            try:
                os.unlink(path)
            except OSError:
                pass


def configured_mailboxes() -> List[str]:
    raw = settings.VENDOR_ACK_INTAKE_MAILBOXES or "joey@opendc.ca,Finance@opendc.ca"
    seen = []
    for part in raw.split(","):
        mailbox = part.strip()
        if mailbox and mailbox.lower() not in {m.lower() for m in seen}:
            seen.append(mailbox)
    return seen


def load_schedule_acks(db: Session) -> List[dict]:
    """Acknowledgements the Purchase Orders sheet can join onto a PO."""
    rows = (
        db.query(VendorOrderAck)
        .filter(VendorOrderAck.our_po_number.isnot(None))
        .filter(VendorOrderAck.status.in_(_ACTIVE))
        .all()
    )
    return [
        {
            "vendor_order_no": row.vendor_order_no,
            "our_po_number": row.our_po_number,
            "status": row.status,
            "completion_date": row.completion_date,
            "received_at": row.received_at,
        }
        for row in rows
    ]


class VendorAckIntakeService:

    def process_new_acks(self, db: Session, dry_run: Optional[bool] = None) -> Dict[str, Any]:
        """Poll every configured mailbox and upsert acknowledgements.

        ``dry_run`` overrides VENDOR_ACK_DRY_RUN for this call. Dry-run still
        stores rows; it does not PATCH Business Central.
        """
        if dry_run is None:
            dry_run = bool(settings.VENDOR_ACK_DRY_RUN)
        mailboxes = configured_mailboxes()
        summary: Dict[str, Any] = {
            "processed": 0,
            "parsed": 0,
            "updated": 0,
            "pending": 0,
            "skipped": 0,
            "duplicate": 0,
            "error": 0,
            "bc_written": 0,
            "bc_failed": 0,
            "bc_skipped": 0,
            "bc_retried": 0,
            "mailboxes": mailboxes,
            "dry_run": dry_run,
            "pending_orders": [],
        }
        if not mailboxes:
            summary["error_message"] = "no mailboxes configured"
            return summary

        batch = self._collect_messages(mailboxes, summary)
        batch.sort(key=lambda item: item[0] or "")

        for _received, mailbox, email in batch:
            self._process_message(db, mailbox, email, dry_run, summary)

        summary["bc_retried"] = self._retry_failed_writes(db, dry_run)
        if summary["pending_orders"]:
            logger.warning(
                "[VendorAck] %s acknowledgement(s) pending with no PO: %s",
                len(summary["pending_orders"]),
                ", ".join(summary["pending_orders"]),
            )
        logger.info("[VendorAck] Run complete: %s", summary)
        return summary

    def _collect_messages(self, mailboxes: List[str], summary: Dict[str, Any]) -> List[tuple]:
        hours = settings.VENDOR_ACK_INTAKE_LOOKBACK_HOURS or 72
        batch = []
        for mailbox in mailboxes:
            try:
                emails = graph_client.get_recent_emails(mailbox, hours=hours, max_count=100)
            except Exception as exc:
                logger.error("[VendorAck] Failed to fetch %s: %s", mailbox, exc)
                summary["error"] += 1
                continue
            for email in emails or []:
                subject = email.get("subject") or ""
                body = email_body_text(email)
                if not email.get("hasAttachments"):
                    continue
                if not is_candidate_email(subject, body):
                    continue
                batch.append((email.get("receivedDateTime") or "", mailbox, email))
        return batch

    def _process_message(
        self, db: Session, mailbox: str, email: dict, dry_run: bool, summary: Dict[str, Any],
    ) -> None:
        message_id = email.get("id")
        if not message_id:
            return
        subject = email.get("subject") or ""
        body = email_body_text(email)
        sender = ((email.get("from") or {}).get("emailAddress") or {}).get("address", "")
        received_at = _parse_datetime(email.get("receivedDateTime"))
        try:
            attachments = graph_client.get_message_attachments(mailbox, message_id)
        except Exception as exc:
            logger.error("[VendorAck] Attachments failed for %s: %s", message_id, exc)
            summary["error"] += 1
            return

        saw_pdf = False
        for att in attachments or []:
            filename = att.get("name") or "attachment"
            if not _is_pdf(att, filename):
                continue
            saw_pdf = True
            content_b64 = att.get("contentBytes")
            if not content_b64:
                continue
            self._process_pdf(
                db, mailbox, message_id, filename, content_b64, subject, body,
                sender, received_at, dry_run, summary,
            )
        if not saw_pdf:
            logger.info("[VendorAck] Candidate %s has no PDF attachment (%s)", message_id, subject)

    def _process_pdf(
        self, db: Session, mailbox: str, message_id: str, filename: str, content_b64: str,
        subject: str, body: str, sender: str, received_at: Optional[datetime],
        dry_run: bool, summary: Dict[str, Any],
    ) -> None:
        existing_source = (
            db.query(VendorOrderAckSource)
            .filter_by(source_email_id=message_id, attachment_filename=filename)
            .first()
        )
        if existing_source:
            summary["duplicate"] += 1
            return

        summary["processed"] += 1
        try:
            pdf_bytes = base64.b64decode(content_b64)
            pdf_text = pdf_bytes_to_text(pdf_bytes)
            parsed = parse_acknowledgement(
                subject=subject, body=body, filename=filename, pdf_text=pdf_text,
            )
        except Exception as exc:
            logger.exception("[VendorAck] Parse failed for %s: %s", filename, exc)
            self._record_source(db, message_id, filename, mailbox, "error", str(exc), None)
            summary["error"] += 1
            return

        if parsed is None:
            self._record_source(
                db, message_id, filename, mailbox, "skipped",
                "no S-ORD number in PDF, filename, or subject", None,
            )
            summary["skipped"] += 1
            return

        try:
            ack, created = self._upsert_ack(
                db, parsed, mailbox, message_id, filename, sender, received_at, subject,
            )
            source = self._record_source(
                db, message_id, filename, mailbox, "parsed", None, ack, commit=False,
            )
            source.ack_id = ack.id
            write_bucket = self._apply_bc_write(db, ack, dry_run)
            db.commit()
        except Exception as exc:
            db.rollback()
            logger.exception("[VendorAck] Save failed for %s: %s", filename, exc)
            summary["error"] += 1
            return

        summary["parsed"] += 1
        if not created:
            summary["updated"] += 1
        if ack.status == "pending":
            summary["pending"] += 1
            summary["pending_orders"].append(ack.vendor_order_no)
        summary[write_bucket] = summary.get(write_bucket, 0) + 1

    def _upsert_ack(
        self, db: Session, parsed, mailbox: str, message_id: str, filename: str,
        sender: str, received_at: Optional[datetime], subject: str,
    ):
        vendor_no = (settings.VENDOR_ACK_VENDOR_NO or "UPW").strip() or "UPW"
        payload = {
            "subject": subject,
            "sender_email": sender,
            "mailbox": mailbox,
            "document_status": parsed.document_status,
            "po_source": parsed.po_source,
            "subject_order_digits": parsed.subject_order_digits,
            "pdf_excerpt": parsed.pdf_excerpt,
            "our_so_numbers": parsed.our_so_numbers,
        }
        existing = (
            db.query(VendorOrderAck)
            .filter_by(vendor_no=vendor_no, vendor_order_no=parsed.vendor_order_no)
            .first()
        )
        if existing:
            payload["previous_status"] = existing.status
            payload["previous_po"] = existing.our_po_number
            payload["previous_completion_date"] = (
                existing.completion_date.isoformat() if existing.completion_date else None
            )
            payload["previous_source_email_id"] = existing.source_email_id
            existing.source_email_id = message_id
            existing.attachment_filename = filename
            existing.mailbox = mailbox
            existing.sender_email = sender or existing.sender_email
            if parsed.our_po_number:
                existing.our_po_number = parsed.our_po_number
                existing.status = parsed.status
            else:
                # A revision that doesn't repeat the PO keeps the link we already have.
                existing.status = parsed.document_status if existing.our_po_number else parsed.status
            existing.our_so_numbers = parsed.our_so_numbers or existing.our_so_numbers
            if parsed.completion_date:
                existing.completion_date = parsed.completion_date
            existing.received_at = received_at or existing.received_at
            existing.parsed_json = payload
            # A new revision should attempt write-back again.
            if existing.bc_write_status in ("written", "failed", "dry_run", "skipped"):
                existing.bc_write_status = None
                existing.bc_write_error = None
            db.flush()
            return existing, False

        ack = VendorOrderAck(
            source_email_id=message_id,
            attachment_filename=filename,
            mailbox=mailbox,
            sender_email=sender,
            vendor_no=vendor_no,
            vendor_order_no=parsed.vendor_order_no,
            our_po_number=parsed.our_po_number,
            our_so_numbers=parsed.our_so_numbers,
            status=parsed.status,
            completion_date=parsed.completion_date,
            received_at=received_at,
            parsed_json=payload,
        )
        db.add(ack)
        db.flush()
        return ack, True

    def _apply_bc_write(self, db: Session, ack: VendorOrderAck, dry_run: bool) -> str:
        """Set bc_write_* on the row. Returns the summary bucket name."""
        if dry_run:
            ack.bc_write_status = "dry_run"
            ack.bc_write_error = None
            return "bc_skipped"
        if ack.status == "pending" or not ack.our_po_number:
            ack.bc_write_status = "skipped"
            ack.bc_write_error = "No PO number on the acknowledgement"
            return "bc_skipped"
        if po_suffix(ack.our_po_number):
            ack.bc_write_status = "skipped"
            ack.bc_write_error = (
                "Split PO suffix is stored for the schedule and is not written "
                "onto the primary PO Vendor Order No."
            )
            return "bc_skipped"
        if not self._is_latest_unsuffixed(db, ack):
            ack.bc_write_status = "skipped"
            ack.bc_write_error = "Superseded by a later acknowledgement on this PO"
            return "bc_skipped"
        if not settings.VENDOR_ACK_BC_WRITEBACK:
            ack.bc_write_status = "skipped"
            ack.bc_write_error = "VENDOR_ACK_BC_WRITEBACK is off"
            return "bc_skipped"
        try:
            self._write_bc(ack)
            return "bc_written"
        except Exception as exc:
            logger.warning(
                "[VendorAck] BC write-back failed for %s -> %s: %s",
                ack.our_po_number, ack.vendor_order_no, exc,
            )
            ack.bc_write_status = "failed"
            ack.bc_write_error = str(exc)[:2000]
            return "bc_failed"

    def _write_bc(self, ack: VendorOrderAck) -> None:
        base = po_base(ack.our_po_number)
        if not base:
            raise LookupError(f"Cannot normalize PO '{ack.our_po_number}'")
        po = bc_client.get_purchase_order_by_number(base)
        if not po:
            raise LookupError(f"BC has no purchase order {base}")
        ack.bc_po_id = po.get("id")
        bc_client.set_purchase_order_vendor_order_no(base, ack.vendor_order_no)
        ack.bc_write_status = "written"
        ack.bc_write_error = None

    def _is_latest_unsuffixed(self, db: Session, ack: VendorOrderAck) -> bool:
        base = po_base(ack.our_po_number)
        if not base or po_suffix(ack.our_po_number):
            return False
        siblings = (
            db.query(VendorOrderAck)
            .filter(VendorOrderAck.vendor_no == ack.vendor_no)
            .filter(VendorOrderAck.status.in_(_ACTIVE))
            .all()
        )
        unsuffixed = [
            row for row in siblings
            if po_base(row.our_po_number) == base and not po_suffix(row.our_po_number)
        ]
        if not unsuffixed:
            return False
        latest = max(unsuffixed, key=lambda row: (row.received_at or row.created_at or datetime.min, row.id or 0))
        return latest.id == ack.id

    def _retry_failed_writes(self, db: Session, dry_run: bool) -> int:
        if dry_run or not settings.VENDOR_ACK_BC_WRITEBACK:
            return 0
        rows = (
            db.query(VendorOrderAck)
            .filter(VendorOrderAck.bc_write_status == "failed")
            .all()
        )
        retried = 0
        for row in rows:
            if po_suffix(row.our_po_number) or row.status not in _ACTIVE:
                row.bc_write_status = "skipped"
                continue
            if not self._is_latest_unsuffixed(db, row):
                row.bc_write_status = "skipped"
                row.bc_write_error = "Superseded by a later acknowledgement on this PO"
                continue
            try:
                self._write_bc(row)
                retried += 1
            except Exception as exc:
                row.bc_write_error = str(exc)[:2000]
                logger.warning(
                    "[VendorAck] BC retry failed for %s -> %s: %s",
                    row.our_po_number, row.vendor_order_no, exc,
                )
        if rows:
            db.commit()
        return retried

    def _record_source(
        self, db: Session, message_id: str, filename: str, mailbox: str,
        outcome: str, detail: Optional[str], ack: Optional[VendorOrderAck],
        commit: bool = True,
    ) -> VendorOrderAckSource:
        source = VendorOrderAckSource(
            source_email_id=message_id,
            attachment_filename=filename,
            mailbox=mailbox,
            outcome=outcome,
            detail=(detail or "")[:2000] or None,
            ack_id=ack.id if ack is not None and ack.id else None,
        )
        db.add(source)
        if commit:
            db.commit()
        else:
            db.flush()
        return source


def _is_pdf(att: dict, filename: str) -> bool:
    content_type = (att.get("contentType") or "").split(";")[0].strip().lower()
    if content_type in PDF_MIME_TYPES and (filename or "").lower().endswith(".pdf"):
        return True
    if content_type == "application/pdf":
        return True
    return (filename or "").lower().endswith(".pdf")


vendor_ack_intake_service = VendorAckIntakeService()
