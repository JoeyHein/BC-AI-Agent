"""Staff sales analysis.

GET /api/admin/sales/invoice-lines
    Posted sales invoice lines for a header posting-date window.
    Auth: staff admin JWT (same dependency as the other /api/admin routes).

    Query:
        start_date   YYYY-MM-DD  (required, inclusive, invoice postingDate)
        end_date     YYYY-MM-DD  (required, inclusive)
        customer_no  optional BC customer number
        page         default 1
        page_size    default 200, max 1000

    The date filter is applied to the invoice header. Lines are expanded
    from those headers, so a line entity with no posting date is not a
    problem. Pages cover the whole window: totalLines / totalInvoices are
    the window totals, and complete=false means BC paging stopped early.

GET /api/admin/sales/item-categories
    Item category list (code, description, parent when BC has one) and
    item number -> category code + description.
"""

import logging
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.admin_customers import get_current_admin
from app.db.models import User
from app.services import sales_invoice_lines_service as lines_service

router = APIRouter(prefix="/api/admin/sales", tags=["admin-sales"])
logger = logging.getLogger(__name__)


@router.get("/invoice-lines")
def get_sales_invoice_lines(
    start_date: date = Query(..., description="Inclusive invoice posting date, YYYY-MM-DD"),
    end_date: date = Query(..., description="Inclusive invoice posting date, YYYY-MM-DD"),
    customer_no: Optional[str] = Query(None, description="BC customer number"),
    page: int = Query(1, ge=1),
    page_size: int = Query(200, ge=1, le=1000),
    _admin: User = Depends(get_current_admin),
):
    """Posted sales invoice lines joined to their headers. Read-only."""
    try:
        return lines_service.get_invoice_lines(
            start_date=start_date,
            end_date=end_date,
            customer_no=customer_no,
            page=page,
            page_size=page_size,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        logger.exception("Sales invoice line query failed")
        raise HTTPException(
            status_code=502,
            detail="Business Central invoice query failed",
        )


@router.get("/item-categories")
def get_sales_item_categories(
    _admin: User = Depends(get_current_admin),
):
    """Item number -> category, plus the BC item category list. Read-only."""
    try:
        return lines_service.get_item_category_catalog()
    except Exception:
        logger.exception("Item category query failed")
        raise HTTPException(
            status_code=502,
            detail="Business Central item category query failed",
        )
