"""
Invoice matching: vendor resolution, PO matching, and GL-account suggestion
for the AI invoice-intake pipeline.

GL-account suggestion is mined from BC's own posted-invoice history rather
than a manually-maintained rule sheet — verified against live data (2026-08):
dozens of vendors have GL-account-coded (non-item) line history, most with
one clearly dominant account (e.g. ACE courier -> 502000 on 93 of 97 lines).
A vendor's suggested account is whichever GL code appears most often in ITS
OWN account-type line history; confidence is 'high' when that majority is
decisive (>= GL_MAJORITY_THRESHOLD share) and 'low' otherwise. A vendor with
no account-line history gets no suggestion at all (None, 'none') rather than
a guess — those get queued for manual coding.
"""

import logging
import time
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Tuple

from app.integrations.bc.client import bc_client

logger = logging.getLogger(__name__)

# A vendor's top GL account needs at least this much of a majority among its
# own history before we call the suggestion "high" confidence.
GL_MAJORITY_THRESHOLD = 0.6
# Need at least this many historical account-lines before trusting a majority
# at all (2-3 lines all agreeing is weak evidence).
GL_MIN_HISTORY_LINES = 3

# How close an open PO's total needs to be to the invoice total to count as
# a match when there's no PO number printed on the invoice to go on directly.
PO_AMOUNT_TOLERANCE_PCT = 0.05  # 5%

_GL_HISTORY_CACHE_TTL_SECONDS = 3600  # 1 hour — history changes slowly


class InvoiceMatchingService:
    def __init__(self):
        self._gl_history_cache: Optional[Tuple[float, Dict[str, Counter]]] = None

    # ── vendor matching ──────────────────────────────────────────────

    def match_vendor(self, sender_email: str, extracted_vendor_name: Optional[str],
                      vendors: List[Dict[str, Any]]) -> Tuple[Optional[Dict[str, Any]], str]:
        """Resolve a BC vendor from the sender's email address first (exact,
        most reliable signal), falling back to fuzzy name matching against
        the extracted vendor name. Returns (vendor_or_None, confidence)."""
        sender_email = (sender_email or "").strip().lower()
        if sender_email:
            for v in vendors:
                v_email = (v.get("email") or "").strip().lower()
                if v_email and v_email == sender_email:
                    return v, "high"
            # Domain-only match — same company, different person/alias.
            sender_domain = sender_email.split("@")[-1] if "@" in sender_email else ""
            if sender_domain:
                for v in vendors:
                    v_email = (v.get("email") or "").strip().lower()
                    if v_email and v_email.split("@")[-1] == sender_domain:
                        return v, "medium"

        if extracted_vendor_name:
            name = extracted_vendor_name.strip().lower()
            best_vendor, best_score = None, 0.0
            for v in vendors:
                display = (v.get("displayName") or "").strip().lower()
                if not display:
                    continue
                score = SequenceMatcher(None, name, display).ratio()
                if score > best_score:
                    best_vendor, best_score = v, score
            if best_vendor and best_score >= 0.85:
                return best_vendor, "high"
            if best_vendor and best_score >= 0.6:
                return best_vendor, "low"

        return None, "none"

    # ── PO matching ──────────────────────────────────────────────────

    def match_purchase_order(
        self,
        vendor_number: str,
        po_number_referenced: Optional[str],
        invoice_total: Optional[float],
        open_purchase_orders: List[Dict[str, Any]],
    ) -> Tuple[Optional[Dict[str, Any]], str]:
        """Match an invoice to one of this vendor's open POs. Prefers the PO
        number printed on the invoice (if it exists among open POs); falls
        back to matching by total amount within tolerance when no PO number
        was found or it doesn't match anything open (common — many vendors
        print their own order confirmation number, not our PO number)."""
        vendor_pos = [
            po for po in open_purchase_orders
            if (po.get("vendorNumber") or "").strip().upper() == (vendor_number or "").strip().upper()
        ]
        if not vendor_pos:
            return None, "none"

        if po_number_referenced:
            ref = po_number_referenced.strip().upper()
            for po in vendor_pos:
                if (po.get("number") or "").strip().upper() == ref:
                    return po, "high"

        if invoice_total:
            candidates = []
            for po in vendor_pos:
                po_total = po.get("totalAmountIncludingTax") or po.get("totalAmountExcludingTax") or 0
                if po_total <= 0:
                    continue
                diff_pct = abs(po_total - invoice_total) / po_total
                if diff_pct <= PO_AMOUNT_TOLERANCE_PCT:
                    candidates.append((diff_pct, po))
            if len(candidates) == 1:
                return candidates[0][1], "medium"
            if len(candidates) > 1:
                # Ambiguous — multiple open POs from this vendor land within
                # tolerance of the invoice total. Don't guess; flag for a human.
                candidates.sort(key=lambda c: c[0])
                return candidates[0][1], "low"

        return None, "none"

    # ── GL-account suggestion ────────────────────────────────────────

    def _gl_history_by_vendor(self) -> Dict[str, Counter]:
        """{vendor_number: Counter({gl_account: line_count})} built from
        recent posted-invoice Account-type lines. Cached — this pulls up to
        1000 invoices with lines expanded, not cheap to recompute per-invoice."""
        now = time.monotonic()
        if self._gl_history_cache and self._gl_history_cache[0] > now:
            return self._gl_history_cache[1]

        history: Dict[str, Counter] = defaultdict(Counter)
        try:
            invoices = bc_client.get_purchase_invoices_with_lines()
            for inv in invoices:
                vn = (inv.get("vendorNumber") or "").strip().upper()
                if not vn:
                    continue
                for ln in inv.get("purchaseInvoiceLines", []):
                    if ln.get("lineType") == "Account":
                        account = ln.get("lineObjectNumber")
                        if account:
                            history[vn][account] += 1
        except Exception as e:
            logger.error(f"[InvoiceMatching] GL history pull failed: {e}")

        self._gl_history_cache = (now + _GL_HISTORY_CACHE_TTL_SECONDS, history)
        return history

    def suggest_gl_account(self, vendor_number: str) -> Tuple[Optional[str], str]:
        """Suggest a GL account for a vendor from its own posted-invoice
        history. Returns (account_no_or_None, confidence: high|low|none)."""
        history = self._gl_history_by_vendor()
        counts = history.get((vendor_number or "").strip().upper())
        if not counts:
            return None, "none"

        total = sum(counts.values())
        if total < GL_MIN_HISTORY_LINES:
            top_account, _ = counts.most_common(1)[0]
            return top_account, "low"

        top_account, top_count = counts.most_common(1)[0]
        share = top_count / total
        return top_account, ("high" if share >= GL_MAJORITY_THRESHOLD else "low")


invoice_matching_service = InvoiceMatchingService()
