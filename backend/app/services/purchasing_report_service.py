"""
Daily purchasing report.

Computes the current purchasing requirement and emails a digest (shortfalls
grouped by vendor) to the purchasing team via Microsoft Graph. The same
computation powers the live dashboard, so the email is a push of what the
dashboard shows.
"""

import logging
from datetime import datetime
from typing import List, Optional

from sqlalchemy.orm import Session

from app.config import settings
from app.integrations.email.client import graph_client
from app.services.purchasing_demand_service import purchasing_demand_service, UNASSIGNED

logger = logging.getLogger(__name__)


class PurchasingReportService:
    def send_daily_report(self, db: Session,
                          recipients: Optional[List[str]] = None,
                          sender: Optional[str] = None) -> dict:
        """Compute requirements and email the digest. Returns a result dict."""
        result = purchasing_demand_service.compute_requirements(db)
        summary = result["summary"]

        recipients = recipients or self._default_recipients()
        sender = sender or settings.NOTIFICATION_SENDER_EMAIL

        if summary["shortfall_items"] == 0:
            logger.info("[PurchasingReport] No shortfalls — skipping digest email")
            return {"sent": False, "reason": "no_shortfalls", "summary": summary}

        subject = (
            f"Purchasing — {summary['shortfall_items']} item(s) to buy "
            f"across {summary['vendor_count']} vendor(s) (~${summary['estimated_cost']:,.0f})"
        )
        html = self.build_digest_html(result, db=db)

        try:
            graph_client.send_mail(sender, recipients, subject, html)
            logger.info(f"[PurchasingReport] Digest sent to {recipients}")
            return {"sent": True, "recipients": recipients, "summary": summary}
        except Exception as e:
            logger.error(f"[PurchasingReport] Failed to send digest: {e}")
            return {"sent": False, "error": str(e), "summary": summary}

    def _default_recipients(self) -> List[str]:
        raw = settings.ADMIN_NOTIFICATION_EMAILS or "joey@opendc.ca"
        return [e.strip() for e in raw.split(",") if e.strip()]

    def _auto_po_section_html(self, db: Session) -> str:
        """POs the nightly auto-PO job drafted in BC in the last ~26h — the
        digest goes out at 07:00, the job runs at 05:00. Draft only; a human
        still reviews and releases each one in BC."""
        from datetime import timedelta
        from app.db.models import POAgentLog

        since = datetime.utcnow() - timedelta(hours=26)
        rows = (
            db.query(POAgentLog)
            .filter(POAgentLog.is_auto.is_(True), POAgentLog.created_at >= since)
            .order_by(POAgentLog.created_at.desc())
            .all()
        )
        if not rows:
            return ""
        total = sum(float(r.total_amount or 0) for r in rows)
        body = [
            f"""<div style="background:#eff6ff;border:1px solid #bfdbfe;border-radius:8px;padding:12px 14px;margin:12px 0">
            <div style="font-weight:700;color:#1e40af;margin-bottom:6px">
            Auto-drafted overnight — {len(rows)} PO(s), ~${total:,.0f} · review + release in BC</div>
            <table style="width:100%;border-collapse:collapse;font-size:13px">
            <tr style="text-align:left;color:#6b7280">
              <th style="padding:3px 6px">PO</th><th style="padding:3px 6px">Vendor</th>
              <th style="padding:3px 6px;text-align:right">Amount</th>
              <th style="padding:3px 6px">Sales orders</th></tr>"""
        ]
        for r in rows:
            sos = ", ".join((r.so_allocations or {}).keys())
            body.append(
                f"""<tr style="border-top:1px solid #dbeafe">
                <td style="padding:3px 6px;font-family:monospace">{r.bc_po_number or '(pending)'}</td>
                <td style="padding:3px 6px">{r.vendor_name}</td>
                <td style="padding:3px 6px;text-align:right">${float(r.total_amount or 0):,.2f}</td>
                <td style="padding:3px 6px;color:#6b7280">{sos}</td></tr>"""
            )
        body.append("</table></div>")
        return "".join(body)

    def build_digest_html(self, result: dict, db: Optional[Session] = None) -> str:
        s = result["summary"]
        when = datetime.utcnow().strftime("%A, %B %d, %Y")

        # The narrative brief leads; the tables below are the backup detail.
        # Best-effort — a digest without a brief is still a useful digest.
        brief_html = ""
        if db is not None:
            try:
                from app.services.purchasing_brief_service import purchasing_brief_service
                brief_html = purchasing_brief_service.render_html(
                    purchasing_brief_service.get_or_generate(db, req=result)
                )
            except Exception as e:
                logger.error(f"[PurchasingReport] brief unavailable: {e}")

        auto_html = ""
        if db is not None:
            try:
                auto_html = self._auto_po_section_html(db)
            except Exception as e:
                logger.error(f"[PurchasingReport] auto-PO section unavailable: {e}")

        prod_note = "" if result.get("production_included") else (
            "<p style='color:#92400e;background:#fef3c7;padding:8px 12px;border-radius:6px;"
            "font-size:13px;margin:8px 0'>Production-order demand not included "
            "(BC production web services not yet published) — figures reflect open sales orders only.</p>"
        )

        parts = [
            f"""<div style="font-family:-apple-system,Segoe UI,Arial,sans-serif;max-width:760px;margin:0 auto;color:#111827">
            <h2 style="margin:0 0 4px">OPENDC Daily Purchasing Report</h2>
            <p style="color:#6b7280;margin:0 0 12px;font-size:13px">{when}</p>
            {brief_html}
            {auto_html}
            <div style="display:flex;gap:16px;margin:12px 0">
              <div style="flex:1;background:#f3f4f6;border-radius:8px;padding:12px">
                <div style="font-size:22px;font-weight:700">{s['shortfall_items']}</div>
                <div style="font-size:12px;color:#6b7280">Items to buy</div></div>
              <div style="flex:1;background:#f3f4f6;border-radius:8px;padding:12px">
                <div style="font-size:22px;font-weight:700">{s['vendor_count']}</div>
                <div style="font-size:12px;color:#6b7280">Vendors</div></div>
              <div style="flex:1;background:#f3f4f6;border-radius:8px;padding:12px">
                <div style="font-size:22px;font-weight:700">${s['estimated_cost']:,.0f}</div>
                <div style="font-size:12px;color:#6b7280">Est. spend</div></div>
            </div>
            {prod_note}"""
        ]

        for g in result["vendors"]:
            is_unassigned = g["vendor_name"] == UNASSIGNED
            header_color = "#b91c1c" if is_unassigned else "#1f2937"
            note = " — assign a vendor in the portal to order these" if is_unassigned else ""
            parts.append(
                f"""<h3 style="color:{header_color};margin:20px 0 6px;border-bottom:2px solid #e5e7eb;padding-bottom:4px">
                {g['vendor_name']} <span style="font-weight:400;color:#6b7280;font-size:13px">
                · {g['item_count']} item(s) · ${g['estimated_cost']:,.2f}{note}</span></h3>
                <table style="width:100%;border-collapse:collapse;font-size:13px">
                <tr style="text-align:left;color:#6b7280">
                  <th style="padding:4px 6px">Item</th><th style="padding:4px 6px">Description</th>
                  <th style="padding:4px 6px;text-align:right">Need</th>
                  <th style="padding:4px 6px;text-align:right">Unit&nbsp;Cost</th>
                  <th style="padding:4px 6px;text-align:right">Last&nbsp;paid</th>
                  <th style="padding:4px 6px">Last&nbsp;from</th>
                  <th style="padding:4px 6px;text-align:right">Est.</th>
                  <th style="padding:4px 6px">Jobs</th></tr>"""
            )
            for r in g["items"]:
                est = r["net_need"] * r["unit_cost"]
                jobs = ", ".join(r["jobs"][:4]) + ("…" if len(r["jobs"]) > 4 else "")
                last_paid = f"${r['last_purchase_cost']:,.2f}" if r.get("last_purchase_cost") is not None else "—"
                last_from = r.get("last_purchase_vendor") or "—"
                # flag when last actually bought from someone other than the assigned vendor
                diff = r.get("last_purchase_vendor") and r["last_purchase_vendor"] != r["vendor_name"]
                from_style = "color:#b45309" if diff else "color:#6b7280"
                parts.append(
                    f"""<tr style="border-top:1px solid #f3f4f6">
                    <td style="padding:4px 6px;font-family:monospace">{r['item_no']}</td>
                    <td style="padding:4px 6px">{r['description']}</td>
                    <td style="padding:4px 6px;text-align:right">{r['net_need']:g} {r['unit_of_measure']}</td>
                    <td style="padding:4px 6px;text-align:right">${r['unit_cost']:,.2f}</td>
                    <td style="padding:4px 6px;text-align:right" title="{r.get('last_purchase_date') or ''}">{last_paid}</td>
                    <td style="padding:4px 6px;{from_style}">{last_from}</td>
                    <td style="padding:4px 6px;text-align:right">${est:,.2f}</td>
                    <td style="padding:4px 6px;color:#6b7280">{jobs}</td></tr>"""
                )
            parts.append("</table>")

        parts.append(
            """<p style="margin:20px 0 4px;font-size:13px">
            <a href="https://portal.opendc.ca/purchasing" style="color:#2563eb">Open the Purchasing tool →</a></p>
            </div>"""
        )
        return "".join(parts)


purchasing_report_service = PurchasingReportService()
