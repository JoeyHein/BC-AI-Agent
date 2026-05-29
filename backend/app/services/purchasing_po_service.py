"""
Purchase-order generation for the purchasing tool.

Takes a purchaser's per-vendor selection, creates the PO in Business Central,
renders an OpenDC PO PDF, and emails it to the vendor (BC native send isn't
available via the API, so we deliver our own PDF via Microsoft Graph). The
result is recorded on POAgentLog for audit.
"""

import logging
from datetime import datetime
from typing import List, Optional

# fpdf2 is imported lazily inside _build_pdf so this module (and the app/test
# import chain that loads it via the purchasing router) doesn't hard-require it.
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import POAgentLog
from app.integrations.bc.client import bc_client
from app.integrations.email.client import graph_client

logger = logging.getLogger(__name__)

COMPANY_NAME = "Open Distribution Company Inc."


class PurchasingPOService:
    def create_and_send(
        self,
        db: Session,
        vendor_no: Optional[str],
        vendor_name: str,
        lines: List[dict],
        user_id: int,
        notes: Optional[str] = None,
        send_email: bool = True,
        cc: Optional[List[str]] = None,
    ) -> dict:
        """Create the PO in BC, render+email the PDF, and log it.

        `lines`: [{item_no, description, quantity, unit_cost}]. Quantity must be
        > 0. Returns bc_po_number + email status; raises on BC creation failure.
        """
        clean = [ln for ln in lines if float(ln.get("quantity") or 0) > 0]
        if not clean:
            raise ValueError("No lines with positive quantity to order")

        # 1. Create PO header in BC.
        bc_po = bc_client.create_purchase_order({
            "vendorNumber": vendor_no or "",
            "vendorName": vendor_name,
        })
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

        # 3. Render PDF.
        pdf_bytes = self._build_pdf(bc_po_number, vendor_no, vendor_name, clean, notes)

        # 4. Email to vendor.
        emailed_to = None
        emailed_at = None
        email_error = None
        vendor_email = self._vendor_email(vendor_no) if vendor_no else None
        if send_email:
            if not vendor_email:
                email_error = "No email on the BC vendor record"
            else:
                try:
                    graph_client.send_mail(
                        from_email=settings.NOTIFICATION_SENDER_EMAIL,
                        to=vendor_email,
                        subject=f"Purchase Order {bc_po_number} — {COMPANY_NAME}",
                        html_body=self._email_body(bc_po_number, vendor_name),
                        attachments=[{
                            "name": f"PO_{bc_po_number}.pdf",
                            "content_bytes": pdf_bytes,
                            "content_type": "application/pdf",
                        }],
                        cc=cc,
                    )
                    emailed_to = vendor_email
                    emailed_at = datetime.utcnow()
                except Exception as e:
                    email_error = str(e)
                    logger.error(f"[PurchasingPO] PO {bc_po_number} email failed: {e}")

        # 5. Record for audit.
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
            emailed_to=emailed_to,
            emailed_at=emailed_at,
        )
        db.add(log)
        db.flush()

        return {
            "success": True,
            "po_id": log.id,
            "bc_po_id": bc_po_id,
            "bc_po_number": bc_po_number,
            "total_amount": total,
            "emailed_to": emailed_to,
            "email_error": email_error,
        }

    # ─── helpers ───────────────────────────────────────────────

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
    def _email_body(po_number: str, vendor_name: str) -> str:
        return f"""<div style="font-family:-apple-system,Segoe UI,Arial,sans-serif;color:#111827">
        <p>Hello {vendor_name},</p>
        <p>Please find attached our Purchase Order <strong>{po_number}</strong>.</p>
        <p>Kindly confirm receipt and expected ship date. Reply to this email with any questions.</p>
        <p>Thank you,<br>{COMPANY_NAME}</p></div>"""

    def _build_pdf(self, po_number: str, vendor_no: Optional[str], vendor_name: str,
                   lines: List[dict], notes: Optional[str]) -> bytes:
        from fpdf import FPDF  # lazy: only the PO-PDF path needs fpdf2

        pdf = FPDF(orientation="P", unit="mm", format="A4")
        pdf.set_auto_page_break(auto=True, margin=15)
        pdf.add_page()

        # Header
        pdf.set_font("Helvetica", "B", 18)
        pdf.cell(0, 10, COMPANY_NAME, ln=1)
        pdf.set_font("Helvetica", "B", 14)
        pdf.set_text_color(80, 80, 80)
        pdf.cell(0, 8, "PURCHASE ORDER", ln=1)
        pdf.set_text_color(0, 0, 0)
        pdf.set_font("Helvetica", "", 10)
        pdf.cell(0, 6, f"PO Number: {po_number or '(pending)'}", ln=1)
        pdf.cell(0, 6, f"Date: {datetime.utcnow().strftime('%Y-%m-%d')}", ln=1)
        pdf.ln(2)

        # Vendor block
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(0, 6, "Vendor", ln=1)
        pdf.set_font("Helvetica", "", 10)
        pdf.cell(0, 6, f"{vendor_name}" + (f"  ({vendor_no})" if vendor_no else ""), ln=1)
        pdf.ln(3)

        # Line table header
        col = {"item": 36, "desc": 88, "qty": 18, "cost": 24, "amt": 24}
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_fill_color(243, 244, 246)
        pdf.cell(col["item"], 7, "Item", border=1, fill=True)
        pdf.cell(col["desc"], 7, "Description", border=1, fill=True)
        pdf.cell(col["qty"], 7, "Qty", border=1, align="R", fill=True)
        pdf.cell(col["cost"], 7, "Unit Cost", border=1, align="R", fill=True)
        pdf.cell(col["amt"], 7, "Amount", border=1, align="R", ln=1, fill=True)

        pdf.set_font("Helvetica", "", 9)
        total = 0.0
        for ln in lines:
            qty = float(ln["quantity"])
            cost = float(ln.get("unit_cost") or 0)
            amt = qty * cost
            total += amt
            desc = (ln.get("description") or "")[:60]
            pdf.cell(col["item"], 6, str(ln["item_no"])[:22], border=1)
            pdf.cell(col["desc"], 6, desc, border=1)
            pdf.cell(col["qty"], 6, f"{qty:g}", border=1, align="R")
            pdf.cell(col["cost"], 6, f"${cost:,.2f}", border=1, align="R")
            pdf.cell(col["amt"], 6, f"${amt:,.2f}", border=1, align="R", ln=1)

        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(col["item"] + col["desc"] + col["qty"], 7, "", border=0)
        pdf.cell(col["cost"], 7, "Total", border=1, align="R")
        pdf.cell(col["amt"], 7, f"${total:,.2f}", border=1, align="R", ln=1)

        if notes:
            pdf.ln(4)
            pdf.set_font("Helvetica", "B", 9)
            pdf.cell(0, 6, "Notes", ln=1)
            pdf.set_font("Helvetica", "", 9)
            pdf.multi_cell(0, 5, str(notes))

        out = pdf.output()  # fpdf2 returns bytearray
        return bytes(out)


purchasing_po_service = PurchasingPOService()
