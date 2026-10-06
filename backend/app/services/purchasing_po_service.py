"""
Purchase-order generation for the purchasing tool.

Creates the PO in Business Central, downloads BC's purchase-order report
(`purchaseOrders({id})/pdfDocument`, the same bytes as the staff PDF
download), and saves an Outlook draft in the portal mailbox
(`NOTIFICATION_SENDER_EMAIL`) with that PDF attached. The draft is
pre-addressed to the BC vendor so a person can review it and hit Send.

The same Outlook draft can be saved later for a purchase order that
already exists in BC (`create_review_draft_for_existing`). Each call
creates a new Drafts message. Nothing is deduped.

This service does not email the vendor. Graph sendMail is not used.
BC has no native send on purchaseOrder. The portal fpdf2 table is not
attached.
"""

import html
import logging
from datetime import datetime
from typing import List, Optional

import requests
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import POAgentLog
from app.integrations.bc.client import bc_client
from app.integrations.email.client import graph_client

logger = logging.getLogger(__name__)

COMPANY_NAME = "Open Distribution Company Inc."


class PurchasingPOService:
    def create_with_review_draft(
        self,
        db: Session,
        vendor_no: Optional[str],
        vendor_name: str,
        lines: List[dict],
        user_id: int,
        notes: Optional[str] = None,
        create_review_draft: bool = True,
        cc: Optional[List[str]] = None,
    ) -> dict:
        """Create the PO in BC and, by default, an unsent Outlook review draft.

        `lines`: [{item_no, description, quantity, unit_cost}]. Quantity must be
        > 0. Raises on BC creation failure.

        `create_review_draft` true (the purchasing-dashboard default) downloads
        `get_purchase_order_pdf` and saves a Graph draft in
        `settings.NOTIFICATION_SENDER_EMAIL`. It never sends. A failed PDF
        download or a failed Graph save is logged and returned on the response
        (`pdf_error` / `draft_error`); the BC PO is kept either way, because
        Business Central has already accepted it. `create_review_draft` false
        skips both the PDF fetch and Graph so a Draft can be created without
        touching a mailbox.
        """
        clean = [ln for ln in lines if float(ln.get("quantity") or 0) > 0]
        if not clean:
            raise ValueError("No lines with positive quantity to order")

        # 1. Create PO header in BC. vendorName is read-only in api/v2.0 (BC
        # 400s if it's in the body) — set vendorNumber only.
        bc_po = bc_client.create_purchase_order({"vendorNumber": vendor_no or ""})
        bc_po_id = bc_po.get("id")
        bc_po_number = bc_po.get("number")
        if not bc_po_id:
            raise RuntimeError(f"BC did not return a PO id: {bc_po}")

        # 2. Add lines.
        for ln in clean:
            line_data = {
                "lineType": "Item",
                "lineObjectNumber": ln["item_no"],
                "quantity": float(ln["quantity"]),
                "directUnitCost": float(ln.get("unit_cost") or 0),
            }
            if ln.get("description"):
                line_data["description"] = str(ln["description"])[:100]
            bc_client.add_purchase_order_line(bc_po_id, line_data)

        # 3. BC PDF + Outlook draft. Never sendMail.
        mailbox = settings.NOTIFICATION_SENDER_EMAIL
        draft_id = None
        draft_web_link = None
        draft_to = None
        draft_warning = None
        draft_error = None
        pdf_error = None
        pdf_source = None
        if create_review_draft:
            draft_to, draft_id, draft_web_link, draft_warning, draft_error, pdf_error, pdf_source = (
                self._save_review_draft(
                    bc_po_id, bc_po_number, vendor_no, vendor_name, notes, cc, mailbox,
                )
            )

        # 4. Record for audit. emailed_* stay empty: the vendor was not emailed.
        total = round(sum(float(l["quantity"]) * float(l.get("unit_cost") or 0) for l in clean), 2)
        log = POAgentLog(
            vendor_id=vendor_no,
            vendor_name=vendor_name,
            status="submitted",
            total_amount=total,
            currency="CAD",
            line_items=[{
                "bc_item_number": l["item_no"],
                "description": l.get("description", ""),
                "quantity": float(l["quantity"]),
                "unit_cost": float(l.get("unit_cost") or 0),
                "line_total": round(float(l["quantity"]) * float(l.get("unit_cost") or 0), 2),
            } for l in clean],
            bc_po_id=bc_po_id,
            bc_po_number=bc_po_number,
            approved_by=user_id,
            approved_at=datetime.utcnow(),
            submitted_at=datetime.utcnow(),
            emailed_to=None,
            emailed_at=None,
        )
        db.add(log)
        db.flush()

        return {
            "success": True,
            "po_id": log.id,
            "bc_po_id": bc_po_id,
            "bc_po_number": bc_po_number,
            "total_amount": total,
            "email_sent": False,
            "emailed_to": None,
            "review_draft_created": bool(draft_id),
            "review_mailbox": mailbox if create_review_draft else None,
            "draft_id": draft_id,
            "draft_web_link": draft_web_link,
            "draft_to": draft_to if draft_id else None,
            "draft_warning": draft_warning,
            "draft_error": draft_error,
            "pdf_error": pdf_error,
            "pdf_source": pdf_source,
        }

    def create_review_draft_for_existing(
        self,
        *,
        kind: str,
        value: str,
        notes: Optional[str] = None,
        cc: Optional[List[str]] = None,
    ) -> dict:
        """Save an unsent Outlook review draft for a purchase order already in BC.

        `kind` is ``guid`` or ``number`` (see ``normalize_staff_po_ref``).
        The PO must be status Draft. Downloads ``get_purchase_order_pdf`` and
        saves a Graph draft in ``settings.NOTIFICATION_SENDER_EMAIL``, To the
        BC vendor email, with the same subject and body as generate-po.

        Does not call sendMail, and does not release or rewrite the PO.
        A failed PDF download or Graph save is returned on the dict
        (``pdf_error`` / ``draft_error``) and does not raise.

        Not idempotent. Each call creates another Drafts message so a fresh
        copy can be saved for the same PO. There is no stored draft id.

        Raises KeyError when BC has no such purchase order, ValueError when
        it is not Draft, and requests.HTTPError when the lookup itself fails
        for a reason other than 404.
        """
        po = self._load_existing_purchase_order(kind, value)
        status = po.get("status") or ""
        number = po.get("number") or value
        if status != "Draft":
            raise ValueError(f"{number} is status {status!r}, not Draft")

        bc_po_id = po.get("id")
        if not bc_po_id:
            raise RuntimeError(
                f"Business Central returned purchase order {number} without an id"
            )

        vendor_no = (po.get("vendorNumber") or "").strip() or None
        vendor_name = (
            (po.get("vendorName") or "").strip()
            or (po.get("payToVendorName") or "").strip()
            or vendor_no
            or "Vendor"
        )
        mailbox = settings.NOTIFICATION_SENDER_EMAIL
        (
            draft_to,
            draft_id,
            draft_web_link,
            draft_warning,
            draft_error,
            pdf_error,
            pdf_source,
        ) = self._save_review_draft(
            bc_po_id, number, vendor_no, vendor_name, notes, cc, mailbox,
        )
        return {
            "success": True,
            "bc_po_id": bc_po_id,
            "bc_po_number": number,
            "email_sent": False,
            "emailed_to": None,
            "review_draft_created": bool(draft_id),
            "review_mailbox": mailbox,
            "draft_id": draft_id,
            "draft_web_link": draft_web_link,
            "draft_to": draft_to if draft_id else None,
            "draft_warning": draft_warning,
            "draft_error": draft_error,
            "pdf_error": pdf_error,
            "pdf_source": pdf_source,
        }

    def _load_existing_purchase_order(self, kind: str, value: str) -> dict:
        try:
            if kind == "guid":
                po = bc_client.get_purchase_order(value)
            else:
                po = bc_client.get_purchase_order_by_number(value)
        except requests.HTTPError as exc:
            bc_status = getattr(getattr(exc, "response", None), "status_code", None)
            if bc_status == 404:
                raise KeyError(value) from exc
            raise
        if not po:
            raise KeyError(value)
        return po

    # ─── helpers ───────────────────────────────────────────────

    def _save_review_draft(
        self,
        bc_po_id: str,
        bc_po_number: Optional[str],
        vendor_no: Optional[str],
        vendor_name: str,
        notes: Optional[str],
        cc: Optional[List[str]],
        mailbox: str,
    ):
        """Download the BC report and save an unsent Outlook draft.

        Returns (draft_to, draft_id, web_link, warning, draft_error, pdf_error, pdf_source).
        """
        vendor_email = self._vendor_email(vendor_no) if vendor_no else None
        try:
            pdf_bytes = bc_client.get_purchase_order_pdf(bc_po_id)
            if not pdf_bytes:
                raise ValueError(f"Empty PDF content for purchase order {bc_po_id}")
        except Exception as exc:
            logger.error(
                "[PurchasingPO] BC purchase-order PDF fetch failed for %s (id=%s); "
                "Outlook review draft not created. Error: %s",
                bc_po_number, bc_po_id, exc,
                exc_info=True,
            )
            pdf_error = f"BC PDF unavailable: {exc}"
            draft_error = (
                "Outlook review draft not created because the Business Central PDF "
                "could not be downloaded"
            )
            return None, None, None, None, draft_error, pdf_error, None

        logger.info(
            "[PurchasingPO] Fetched BC purchase-order PDF for %s (id=%s, %s bytes)",
            bc_po_number, bc_po_id, len(pdf_bytes),
        )
        warning = None
        if not vendor_email:
            warning = "No email on the BC vendor record; review draft has no To address"
            logger.warning(
                "[PurchasingPO] %s for PO %s (vendor %s)",
                warning, bc_po_number, vendor_no,
            )

        try:
            draft = graph_client.create_draft_with_attachment(
                mailbox=mailbox,
                to=vendor_email,
                subject=f"Purchase Order {bc_po_number} — {COMPANY_NAME}",
                html_body=self._email_body(bc_po_number, vendor_name, notes),
                attachments=[{
                    "name": f"PO_{bc_po_number}.pdf",
                    "content_bytes": pdf_bytes,
                    "content_type": "application/pdf",
                }],
                cc=cc,
            )
        except Exception as exc:
            logger.error(
                "[PurchasingPO] Outlook review draft failed for PO %s (mailbox %s): %s",
                bc_po_number, mailbox, exc,
                exc_info=True,
            )
            return vendor_email, None, None, warning, str(exc), None, "bc"

        draft_id = draft.get("id")
        if not draft_id:
            logger.error(
                "[PurchasingPO] Graph did not return a draft id for PO %s (mailbox %s)",
                bc_po_number, mailbox,
            )
            return vendor_email, None, None, warning, "Graph did not return a draft id", None, "bc"

        logger.info(
            "[PurchasingPO] Saved Outlook review draft %s in %s for PO %s "
            "(not sent; to=%s)",
            draft_id, mailbox, bc_po_number, vendor_email or "(none)",
        )
        return vendor_email, draft_id, draft.get("webLink"), warning, None, None, "bc"

    @staticmethod
    def _vendor_email(vendor_no: str) -> Optional[str]:
        try:
            res = bc_client._make_request(
                "GET",
                f"companies({bc_client.company_id})/vendors?$filter=number eq '{vendor_no}'&$select=number,email",
            )
            vals = res.get("value", [])
            return (vals[0].get("email") or None) if vals else None
        except Exception as e:
            logger.warning(f"[PurchasingPO] vendor email lookup failed for {vendor_no}: {e}")
            return None

    @staticmethod
    def _email_body(po_number: str, vendor_name: str, notes: Optional[str] = None) -> str:
        notes_html = ""
        if notes:
            notes_html = f"<p><strong>Notes:</strong> {html.escape(str(notes))}</p>"
        return f"""<div style="font-family:-apple-system,Segoe UI,Arial,sans-serif;color:#111827">
        <p>Hello {html.escape(vendor_name)},</p>
        <p>Please find attached our Purchase Order <strong>{html.escape(str(po_number or ''))}</strong>.</p>
        {notes_html}
        <p>Kindly confirm receipt and expected ship date. Reply to this email with any questions.</p>
        <p>Thank you,<br>{COMPANY_NAME}</p></div>"""


purchasing_po_service = PurchasingPOService()
