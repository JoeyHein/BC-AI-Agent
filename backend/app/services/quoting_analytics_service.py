"""
Quoting Analytics Service
Computes quote pipeline metrics from Business Central sales quotes and orders.
"""
import logging
from datetime import datetime, date, timedelta
from typing import Dict, List, Any, Optional
from collections import defaultdict

from app.integrations.bc.client import bc_client
from app.config import settings

logger = logging.getLogger(__name__)


class QuotingAnalyticsService:

    def __init__(self):
        self.client = bc_client
        self.company_id = settings.BC_COMPANY_ID

    def _get_all_pages(self, endpoint: str, params: Optional[Dict] = None) -> List[Dict]:
        results = []
        query_parts = [f"{k}={v}" for k, v in (params or {}).items()]
        qs = "&".join(query_parts)
        url = f"{self.client.base_url}/companies({self.company_id})/{endpoint}" + (f"?{qs}" if qs else "")
        while url:
            token = self.client._get_access_token()
            import requests as req
            resp = req.get(url, headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
            if resp.status_code >= 400:
                logger.error(f"BC API error {resp.status_code}: {resp.text[:300]}")
                break
            data = resp.json()
            results.extend(data.get("value", []))
            url = data.get("@odata.nextLink")
        return results

    # ─── helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _parse_date(val: str) -> Optional[date]:
        if not val:
            return None
        try:
            return datetime.fromisoformat(val.replace("Z", "+00:00")).date()
        except Exception:
            try:
                return datetime.strptime(val[:10], "%Y-%m-%d").date()
            except Exception:
                return None

    # ─── main entry ─────────────────────────────────────────────────────

    def get_quoting_analytics(self, days: int = 30) -> Dict[str, Any]:
        cutoff = date.today() - timedelta(days=days)
        cutoff_str = cutoff.isoformat()

        # Fetch data — BC uses documentDate for quotes, orderDate for orders
        quotes = self._get_all_pages("salesQuotes", {
            "$select": "id,number,customerNumber,customerName,totalAmountIncludingTax,documentDate,status,validUntilDate,externalDocumentNumber",
        })
        orders = self._get_all_pages("salesOrders", {
            "$select": "id,number,customerNumber,customerName,totalAmountIncludingTax,orderDate,status,externalDocumentNumber",
        })

        # Parse dates
        for q in quotes:
            q["_date"] = self._parse_date(q.get("documentDate", ""))
        for o in orders:
            o["_date"] = self._parse_date(o.get("orderDate", ""))

        # Filter to period
        period_quotes = [q for q in quotes if q["_date"] and q["_date"] >= cutoff]
        period_orders = [o for o in orders if o["_date"] and o["_date"] >= cutoff]

        # Open quotes (no status filter — all quotes in BC are "open" until converted/deleted)
        open_quotes = quotes  # BC only returns open quotes via salesQuotes endpoint

        today = date.today()

        # ── 1. Summary cards ───────────────────────────────────────────
        total_open_value = sum(q.get("totalAmountIncludingTax", 0) or 0 for q in open_quotes)

        # Conversion: orders that originated from quotes (match by externalDocumentNumber or customer+date proximity)
        quote_numbers = {q.get("number") for q in period_quotes}
        order_ext_docs = {o.get("externalDocumentNumber", "") for o in period_orders}
        converted_count = sum(1 for q in period_quotes if q.get("number") in order_ext_docs or q.get("externalDocumentNumber") in order_ext_docs)
        conversion_rate = round((converted_count / len(period_quotes) * 100)) if period_quotes else 0

        # Expiring within 7 days
        expiring_soon = 0
        for q in open_quotes:
            due = self._parse_date(q.get("validUntilDate", ""))
            if due and today <= due <= today + timedelta(days=7):
                expiring_soon += 1

        # Average quote age
        ages = []
        for q in open_quotes:
            qd = q["_date"]
            if qd:
                ages.append((today - qd).days)
        avg_age = round(sum(ages) / len(ages)) if ages else 0

        summary = {
            "total_open_value": round(total_open_value),
            "conversion_rate": conversion_rate,
            "expiring_soon": expiring_soon,
            "avg_age_days": avg_age,
            "total_quotes_in_period": len(period_quotes),
            "total_orders_in_period": len(period_orders),
        }

        # ── 2. Quote frequency by customer (top 10) ───────────────────
        cust_counts = defaultdict(int)
        for q in period_quotes:
            name = q.get("customerName") or q.get("customerNumber") or "Unknown"
            cust_counts[name] += 1
        quote_by_customer = sorted(
            [{"customer": k, "count": v} for k, v in cust_counts.items()],
            key=lambda x: x["count"], reverse=True
        )[:10]

        # ── 3. Conversion rate by customer ─────────────────────────────
        cust_quotes = defaultdict(int)
        cust_orders = defaultdict(int)
        for q in period_quotes:
            name = q.get("customerName") or q.get("customerNumber") or "Unknown"
            cust_quotes[name] += 1
        for o in period_orders:
            name = o.get("customerName") or o.get("customerNumber") or "Unknown"
            cust_orders[name] += 1

        conversion_by_customer = []
        for name in sorted(cust_quotes, key=cust_quotes.get, reverse=True):
            q_count = cust_quotes[name]
            o_count = cust_orders.get(name, 0)
            rate = round(o_count / q_count * 100) if q_count else 0
            conversion_by_customer.append({
                "customer": name,
                "quotes": q_count,
                "orders": o_count,
                "rate": rate,
            })

        # ── 4. Most-quoted items not converting ────────────────────────
        # Fetch quote lines for period quotes
        item_quoted = defaultdict(int)
        item_ordered = defaultdict(int)
        item_desc_map = {}

        for q in period_quotes[:50]:  # Cap to avoid too many API calls
            try:
                lines = self.client.get_quote_lines(q["id"])
                if isinstance(lines, list):
                    for ln in lines:
                        if ln.get("lineType") == "Item" and ln.get("lineObjectNumber"):
                            pn = ln["lineObjectNumber"]
                            item_quoted[pn] += 1
                            if pn not in item_desc_map:
                                item_desc_map[pn] = ln.get("description", pn)
            except Exception:
                pass

        for o in period_orders[:50]:
            try:
                lines = self.client.get_order_lines(o["id"])
                if isinstance(lines, list):
                    for ln in lines:
                        if ln.get("lineType") == "Item" and ln.get("lineObjectNumber"):
                            item_ordered[ln["lineObjectNumber"]] += 1
            except Exception:
                pass

        items_not_converting = []
        for pn, q_count in sorted(item_quoted.items(), key=lambda x: x[1], reverse=True):
            if q_count < 5:
                continue
            o_count = item_ordered.get(pn, 0)
            rate = round(o_count / q_count * 100) if q_count else 0
            items_not_converting.append({
                "item": item_desc_map.get(pn, pn),
                "item_number": pn,
                "times_quoted": q_count,
                "times_ordered": o_count,
                "rate": rate,
            })

        # ── 5. Quote aging buckets ─────────────────────────────────────
        buckets = {"0-7": {"count": 0, "value": 0}, "8-14": {"count": 0, "value": 0},
                   "15-30": {"count": 0, "value": 0}, "30+": {"count": 0, "value": 0}}
        for q in open_quotes:
            qd = q["_date"]
            if not qd:
                continue
            age = (today - qd).days
            val = q.get("totalAmountIncludingTax", 0) or 0
            if age <= 7:
                buckets["0-7"]["count"] += 1; buckets["0-7"]["value"] += val
            elif age <= 14:
                buckets["8-14"]["count"] += 1; buckets["8-14"]["value"] += val
            elif age <= 30:
                buckets["15-30"]["count"] += 1; buckets["15-30"]["value"] += val
            else:
                buckets["30+"]["count"] += 1; buckets["30+"]["value"] += val

        aging = [
            {"bucket": "0-7 days", "label": "Fresh", "status": "green", **buckets["0-7"]},
            {"bucket": "8-14 days", "label": "Active", "status": "green", **buckets["8-14"]},
            {"bucket": "15-30 days", "label": "Follow up", "status": "amber", **buckets["15-30"]},
            {"bucket": "30+ days", "label": "At risk", "status": "red", **buckets["30+"]},
        ]
        for a in aging:
            a["value"] = round(a["value"])

        # ── 6. Pipeline by account type ────────────────────────────────
        # Use customerNumber prefix or BC customer data to classify
        dealer_value = 0
        builder_value = 0
        other_value = 0
        for q in open_quotes:
            val = q.get("totalAmountIncludingTax", 0) or 0
            name = (q.get("customerName") or "").upper()
            # Heuristic: classify by name patterns common in the business
            if any(kw in name for kw in ["DOOR", "OVERHEAD", "GARAGE", "OHD"]):
                dealer_value += val
            elif any(kw in name for kw in ["HOME", "BUILD", "CONSTRUCT", "DEVELOP"]):
                builder_value += val
            else:
                other_value += val

        pipeline_by_type = [
            {"type": "Dealer", "value": round(dealer_value)},
            {"type": "Home Builder", "value": round(builder_value)},
            {"type": "Other", "value": round(other_value)},
        ]

        # ── 7. Quote volume over time (12 months) ─────────────────────
        twelve_months_ago = date.today() - timedelta(days=365)
        monthly = defaultdict(int)
        for q in quotes:
            qd = q["_date"]
            if qd and qd >= twelve_months_ago:
                key = qd.strftime("%Y-%m")
                monthly[key] += 1

        volume_over_time = []
        for i in range(12):
            d = date.today() - timedelta(days=30 * (11 - i))
            key = d.strftime("%Y-%m")
            volume_over_time.append({"month": key, "count": monthly.get(key, 0)})

        # ── 8. Quote revision frequency ────────────────────────────────
        # Use line count as a proxy — quotes with more lines have likely been revised
        revision_1 = 0
        revision_2_3 = 0
        revision_4_plus = 0
        for q in period_quotes[:100]:
            try:
                lines = self.client.get_quote_lines(q["id"])
                line_count = len([l for l in (lines if isinstance(lines, list) else []) if l.get("lineType") == "Item"])
                # Heuristic: single item = 1 revision, 2-10 items = normal, 10+ = heavily revised
                if line_count <= 3:
                    revision_1 += 1
                elif line_count <= 10:
                    revision_2_3 += 1
                else:
                    revision_4_plus += 1
            except Exception:
                revision_1 += 1

        revision_frequency = {
            "simple": revision_1,
            "moderate": revision_2_3,
            "complex": revision_4_plus,
        }

        return {
            "summary": summary,
            "quote_by_customer": quote_by_customer,
            "conversion_by_customer": conversion_by_customer,
            "items_not_converting": items_not_converting[:20],
            "aging": aging,
            "pipeline_by_type": pipeline_by_type,
            "volume_over_time": volume_over_time,
            "revision_frequency": revision_frequency,
            "period_days": days,
        }


quoting_analytics_service = QuotingAnalyticsService()
