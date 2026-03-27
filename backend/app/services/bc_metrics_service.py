"""
Business Central Metrics Service
Fetches KPIs and analytics data from BC for the Business Dashboard
"""

import logging
from datetime import datetime, date, timedelta
from typing import Dict, List, Any, Optional
from collections import defaultdict

from app.integrations.bc.client import bc_client
from app.config import settings

logger = logging.getLogger(__name__)


class BCMetricsService:
    """Fetches and computes business metrics from Business Central API"""

    def __init__(self):
        self.client = bc_client
        self.company_id = settings.BC_COMPANY_ID

    def _api(self, endpoint: str, params: Optional[Dict] = None) -> Dict:
        """Make a BC API request with optional OData query params."""
        query_parts = []
        if params:
            for k, v in params.items():
                query_parts.append(f"{k}={v}")
        qs = "&".join(query_parts)
        full = f"companies({self.company_id})/{endpoint}" + (f"?{qs}" if qs else "")
        return self.client._make_request("get", full)

    def _get_all_pages(self, endpoint: str, params: Optional[Dict] = None) -> List[Dict]:
        """Fetch all pages of a paginated BC API response."""
        results = []
        query_parts = []
        if params:
            for k, v in params.items():
                query_parts.append(f"{k}={v}")
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

    # =========================================================================
    # DATE HELPERS
    # =========================================================================

    @staticmethod
    def _start_of_year() -> str:
        return f"{date.today().year}-01-01"

    @staticmethod
    def _prior_year_start() -> str:
        return f"{date.today().year - 1}-01-01"

    @staticmethod
    def _prior_year_end() -> str:
        today = date.today()
        return f"{today.year - 1}-{today.month:02d}-{today.day:02d}"

    @staticmethod
    def _rolling_30d() -> str:
        return (date.today() - timedelta(days=30)).isoformat()

    # =========================================================================
    # EXECUTIVE METRICS
    # =========================================================================

    def get_executive_metrics(self) -> Dict[str, Any]:
        """Fetch all executive dashboard KPIs."""
        soy = self._start_of_year()
        py_start = self._prior_year_start()
        py_end = self._prior_year_end()

        # Fetch invoices for current year and prior year (same period)
        invoices_ytd = self._get_all_pages("salesInvoices", {
            "$filter": f"postingDate ge {soy}",
            "$select": "id,number,totalAmountIncludingTax,totalAmountExcludingTax,postingDate,customerNumber,customerName",
        })
        invoices_py = self._get_all_pages("salesInvoices", {
            "$filter": f"postingDate ge {py_start} and postingDate le {py_end}",
            "$select": "id,totalAmountIncludingTax,totalAmountExcludingTax,postingDate,customerNumber",
        })

        # Revenue YTD
        revenue_ytd = sum(inv.get("totalAmountExcludingTax", 0) or 0 for inv in invoices_ytd)
        revenue_py = sum(inv.get("totalAmountExcludingTax", 0) or 0 for inv in invoices_py)
        revenue_delta_pct = ((revenue_ytd - revenue_py) / revenue_py * 100) if revenue_py else 0

        # Order counts
        orders_ytd = len(invoices_ytd)
        orders_py = len(invoices_py)

        # Average Order Value
        avg_order = revenue_ytd / orders_ytd if orders_ytd else 0
        avg_order_py = revenue_py / orders_py if orders_py else 0

        # Active customer accounts
        customer_numbers_ytd = set(inv.get("customerNumber") for inv in invoices_ytd if inv.get("customerNumber"))
        customer_numbers_py = set(inv.get("customerNumber") for inv in invoices_py if inv.get("customerNumber"))
        new_customers = customer_numbers_ytd - customer_numbers_py

        # Monthly revenue breakdown (for chart)
        monthly_revenue = defaultdict(float)
        monthly_revenue_py = defaultdict(float)
        for inv in invoices_ytd:
            pd = inv.get("postingDate", "")
            if pd:
                month = pd[:7]  # YYYY-MM
                monthly_revenue[month] += inv.get("totalAmountExcludingTax", 0) or 0
        for inv in invoices_py:
            pd = inv.get("postingDate", "")
            if pd:
                month = pd[:7]
                monthly_revenue_py[month] += inv.get("totalAmountExcludingTax", 0) or 0

        # Build monthly chart data (Jan to current month)
        current_year = date.today().year
        prior_year = current_year - 1
        chart_data = []
        for m in range(1, date.today().month + 1):
            key_cy = f"{current_year}-{m:02d}"
            key_py = f"{prior_year}-{m:02d}"
            chart_data.append({
                "month": datetime(current_year, m, 1).strftime("%b"),
                "current": round(monthly_revenue.get(key_cy, 0), 2),
                "prior": round(monthly_revenue_py.get(key_py, 0), 2),
            })

        # Top 10 accounts by revenue
        customer_revenue = defaultdict(lambda: {"revenue": 0, "orders": 0, "name": ""})
        for inv in invoices_ytd:
            cn = inv.get("customerNumber", "")
            customer_revenue[cn]["revenue"] += inv.get("totalAmountExcludingTax", 0) or 0
            customer_revenue[cn]["orders"] += 1
            customer_revenue[cn]["name"] = inv.get("customerName", cn)

        top_accounts = sorted(customer_revenue.values(), key=lambda x: x["revenue"], reverse=True)[:10]

        # Product mix (fetch invoice lines)
        try:
            invoice_lines = self._get_all_pages("salesInvoiceLines", {
                "$filter": f"postingDate ge {soy}",
                "$select": "description,lineAmount,itemId",
                "$top": "5000",
            })
            product_revenue = defaultdict(float)
            for line in invoice_lines:
                desc = line.get("description", "Other") or "Other"
                product_revenue[desc] += line.get("lineAmount", 0) or 0
            product_mix = sorted(
                [{"name": k, "value": round(v, 2)} for k, v in product_revenue.items()],
                key=lambda x: x["value"], reverse=True
            )[:10]
        except Exception as e:
            logger.warning(f"Could not fetch invoice lines for product mix: {e}")
            product_mix = []

        # OTD % (rolling 30d) from shipments
        otd = self._compute_otd(days=30)

        return {
            "revenueYTD": round(revenue_ytd, 2),
            "revenuePriorYTD": round(revenue_py, 2),
            "revenueDeltaPct": round(revenue_delta_pct, 1),
            "ordersShipped": orders_ytd,
            "avgOrderValue": round(avg_order, 2),
            "avgOrderValuePY": round(avg_order_py, 2),
            "activeCustomers": len(customer_numbers_ytd),
            "newCustomers": len(new_customers),
            "otdPct": otd["pct"],
            "otdTotal": otd["total"],
            "otdOnTime": otd["on_time"],
            "monthlyRevenue": chart_data,
            "productMix": product_mix,
            "topAccounts": top_accounts,
        }

    # =========================================================================
    # OPERATIONS METRICS
    # =========================================================================

    def get_operations_metrics(self) -> Dict[str, Any]:
        """Fetch operations dashboard KPIs."""
        # Open sales orders
        open_orders = self._get_all_pages("salesOrders", {
            "$filter": "status eq 'Open'",
            "$select": "id,number,orderDate,requestedDeliveryDate,totalAmountExcludingTax,customerName,customerNumber,status",
        })

        today_str = date.today().isoformat()
        overdue = [o for o in open_orders if o.get("requestedDeliveryDate") and o["requestedDeliveryDate"] < today_str]

        # Orders this week
        week_start = (date.today() - timedelta(days=date.today().weekday())).isoformat()
        orders_this_week = self._get_all_pages("salesOrders", {
            "$filter": f"orderDate ge {week_start}",
            "$select": "id,number,orderDate",
        })

        # Shipments today
        shipments_today = self._get_all_pages("salesShipments", {
            "$filter": f"postingDate eq {today_str}",
            "$select": "id,number,postingDate",
        })

        # OTD 30-day
        otd = self._compute_otd(days=30)

        # Daily shipments this week (for chart)
        week_shipments = self._get_all_pages("salesShipments", {
            "$filter": f"postingDate ge {week_start}",
            "$select": "id,number,postingDate,orderNo",
        })
        daily_shipments = defaultdict(lambda: {"onTime": 0, "late": 0})
        for s in week_shipments:
            pd = s.get("postingDate", "")
            if pd:
                daily_shipments[pd]["onTime"] += 1  # simplified; full OTD check would need promised date

        daily_chart = []
        for i in range(7):
            d = date.today() - timedelta(days=date.today().weekday()) + timedelta(days=i)
            if d > date.today():
                break
            ds = d.isoformat()
            daily_chart.append({
                "day": d.strftime("%a"),
                "date": ds,
                "onTime": daily_shipments[ds]["onTime"],
                "late": daily_shipments[ds]["late"],
            })

        # Overdue orders detail
        overdue_detail = []
        for o in sorted(overdue, key=lambda x: x.get("requestedDeliveryDate", ""))[:20]:
            req_date = o.get("requestedDeliveryDate", "")
            days_late = (date.today() - date.fromisoformat(req_date)).days if req_date else 0
            overdue_detail.append({
                "orderNo": o.get("number", ""),
                "customer": o.get("customerName", ""),
                "daysLate": days_late,
                "value": o.get("totalAmountExcludingTax", 0),
                "requestedDate": req_date,
            })

        return {
            "openOrders": len(open_orders),
            "overdueOrders": len(overdue),
            "ordersThisWeek": len(orders_this_week),
            "shipmentsToday": len(shipments_today),
            "commitDateMetPct": otd["pct"],
            "dailyShipments": daily_chart,
            "overdueDetail": overdue_detail,
        }

    # =========================================================================
    # SHIPPING METRICS
    # =========================================================================

    def get_shipping_metrics(self) -> Dict[str, Any]:
        """Fetch shipping view KPIs and today's ship queue."""
        today_str = date.today().isoformat()

        # Open orders with delivery date today or past
        open_orders = self._get_all_pages("salesOrders", {
            "$filter": "status eq 'Open'",
            "$select": "id,number,orderDate,requestedDeliveryDate,totalAmountExcludingTax,customerName,status",
            "$orderby": "requestedDeliveryDate asc",
        })

        due_today = [o for o in open_orders if o.get("requestedDeliveryDate") == today_str]
        overdue = [o for o in open_orders if o.get("requestedDeliveryDate") and o["requestedDeliveryDate"] < today_str]

        # Avg days order-to-ship (rolling 30d)
        r30 = self._rolling_30d()
        recent_shipments = self._get_all_pages("salesShipments", {
            "$filter": f"postingDate ge {r30}",
            "$select": "id,number,postingDate,orderNo,orderDate",
        })
        ship_days = []
        for s in recent_shipments:
            od = s.get("orderDate")
            sd = s.get("postingDate")
            if od and sd:
                try:
                    delta = (date.fromisoformat(sd) - date.fromisoformat(od)).days
                    if delta >= 0:
                        ship_days.append(delta)
                except ValueError:
                    pass
        avg_days_to_ship = round(sum(ship_days) / len(ship_days), 1) if ship_days else 0

        # Ship queue (due today + overdue)
        ship_queue = []
        for o in due_today + overdue:
            req = o.get("requestedDeliveryDate", "")
            is_overdue = req < today_str if req else False
            ship_queue.append({
                "orderNo": o.get("number", ""),
                "customer": o.get("customerName", ""),
                "requestedDate": req,
                "value": o.get("totalAmountExcludingTax", 0),
                "status": "overdue" if is_overdue else "due_today",
            })

        return {
            "shipmentsDueToday": len(due_today),
            "overdueShipments": len(overdue),
            "avgDaysToShip": avg_days_to_ship,
            "totalOpenOrders": len(open_orders),
            "shipQueue": ship_queue,
        }

    # =========================================================================
    # CUSTOMER METRICS
    # =========================================================================

    def get_customer_metrics(self, customer_number: str) -> Dict[str, Any]:
        """Fetch metrics for a specific customer."""
        soy = self._start_of_year()
        py_start = self._prior_year_start()
        py_end = self._prior_year_end()

        # Customer profile from BC
        try:
            customers = self._get_all_pages("customers", {
                "$filter": f"number eq '{customer_number}'",
                "$select": "id,number,displayName,city,state,creditLimit,balanceDue,paymentTermsId,salespersonCode",
            })
            profile = customers[0] if customers else {}
        except Exception:
            profile = {}

        # Invoices YTD and prior year
        invoices_ytd = self._get_all_pages("salesInvoices", {
            "$filter": f"customerNumber eq '{customer_number}' and postingDate ge {soy}",
            "$select": "id,number,totalAmountExcludingTax,postingDate",
        })
        invoices_py = self._get_all_pages("salesInvoices", {
            "$filter": f"customerNumber eq '{customer_number}' and postingDate ge {py_start} and postingDate le {py_end}",
            "$select": "id,number,totalAmountExcludingTax,postingDate",
        })

        sales_ytd = sum(inv.get("totalAmountExcludingTax", 0) or 0 for inv in invoices_ytd)
        sales_py = sum(inv.get("totalAmountExcludingTax", 0) or 0 for inv in invoices_py)
        orders_ytd = len(invoices_ytd)
        orders_py = len(invoices_py)
        avg_order = sales_ytd / orders_ytd if orders_ytd else 0
        avg_order_py = sales_py / orders_py if orders_py else 0

        # Monthly sales chart
        monthly_sales = defaultdict(float)
        for inv in invoices_ytd:
            pd = inv.get("postingDate", "")
            if pd:
                monthly_sales[pd[:7]] += inv.get("totalAmountExcludingTax", 0) or 0

        chart_data = []
        for m in range(1, date.today().month + 1):
            key = f"{date.today().year}-{m:02d}"
            chart_data.append({
                "month": datetime(date.today().year, m, 1).strftime("%b"),
                "sales": round(monthly_sales.get(key, 0), 2),
            })

        # Open orders
        open_orders = self._get_all_pages("salesOrders", {
            "$filter": f"customerNumber eq '{customer_number}' and status eq 'Open'",
            "$select": "id,number,totalAmountExcludingTax,orderDate,requestedDeliveryDate",
        })
        open_value = sum(o.get("totalAmountExcludingTax", 0) or 0 for o in open_orders)

        # OTD for this customer (YTD)
        otd = self._compute_otd(customer_number=customer_number, days=365)

        # Recent orders with delivery scorecard
        recent_shipments = self._get_all_pages("salesShipments", {
            "$filter": f"customerNumber eq '{customer_number}' and postingDate ge {soy}",
            "$select": "id,number,postingDate,orderNo",
            "$orderby": "postingDate desc",
            "$top": "20",
        })

        # Credit info
        credit_limit = profile.get("creditLimit", 0) or 0
        balance_due = profile.get("balanceDue", 0) or 0
        credit_utilization = (balance_due / credit_limit * 100) if credit_limit > 0 else 0

        return {
            "profile": {
                "name": profile.get("displayName", ""),
                "number": customer_number,
                "city": profile.get("city", ""),
                "state": profile.get("state", ""),
                "salesperson": profile.get("salespersonCode", ""),
                "creditLimit": credit_limit,
                "balanceDue": round(balance_due, 2),
                "creditUtilization": round(credit_utilization, 1),
            },
            "salesYTD": round(sales_ytd, 2),
            "salesPY": round(sales_py, 2),
            "salesDeltaPct": round(((sales_ytd - sales_py) / sales_py * 100) if sales_py else 0, 1),
            "ordersYTD": orders_ytd,
            "ordersPY": orders_py,
            "avgOrderValue": round(avg_order, 2),
            "avgOrderValuePY": round(avg_order_py, 2),
            "openOrders": len(open_orders),
            "openOrderValue": round(open_value, 2),
            "otdPct": otd["pct"],
            "monthlySales": chart_data,
            "recentShipments": recent_shipments[:20],
        }

    # =========================================================================
    # HELPERS
    # =========================================================================

    def _compute_otd(self, days: int = 30, customer_number: Optional[str] = None) -> Dict[str, Any]:
        """Compute on-time delivery percentage from sales shipments."""
        start = (date.today() - timedelta(days=days)).isoformat()

        filter_parts = [f"postingDate ge {start}"]
        if customer_number:
            filter_parts.append(f"customerNumber eq '{customer_number}'")

        try:
            shipments = self._get_all_pages("salesShipments", {
                "$filter": " and ".join(filter_parts),
                "$select": "id,postingDate,requestedDeliveryDate,orderNo",
            })
        except Exception as e:
            logger.warning(f"Could not fetch shipments for OTD: {e}")
            return {"pct": 0, "total": 0, "on_time": 0}

        total = 0
        on_time = 0
        for s in shipments:
            promised = s.get("requestedDeliveryDate")
            actual = s.get("postingDate")
            if promised and actual:
                total += 1
                if actual <= promised:
                    on_time += 1

        pct = round((on_time / total * 100) if total else 0, 1)
        return {"pct": pct, "total": total, "on_time": on_time}


# Global instance
bc_metrics_service = BCMetricsService()
