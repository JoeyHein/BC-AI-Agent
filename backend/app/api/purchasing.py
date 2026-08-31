"""
Purchasing tool API (Admin).

Live purchasing requirements (demand netted against stock + open POs),
vendor mapping management, daily-report trigger, and per-vendor PO generation.
"""

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status, Query, Response
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.database import SessionLocal
from app.db.models import User
from app.services.auth_service import auth_service
from app.services.purchasing_demand_service import purchasing_demand_service
from app.services.vendor_map_service import vendor_map_service
from app.services.purchasing_report_service import purchasing_report_service
from app.services.purchasing_po_service import purchasing_po_service
from app.services.planning_workbook_service import planning_workbook_service, XLSX_MIME
from app.services.so_coverage_service import (
    so_coverage_service,
    BUY_WINDOW_DAYS_DEFAULT as SO_BUY_WINDOW_DEFAULT,
    ATTENTION_WINDOW_DAYS_DEFAULT as SO_ATTENTION_WINDOW_DEFAULT,
)
from app.services.so_master_crosscheck_service import so_master_crosscheck_service
from app.integrations.bc.client import bc_client

router = APIRouter(prefix="/api/admin/purchasing", tags=["purchasing"])
logger = logging.getLogger(__name__)

security = HTTPBearer()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_admin(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    token = credentials.credentials
    payload = auth_service.decode_token(token)
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    if payload.get("user_type") == "customer":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    user = db.query(User).get(int(payload.get("sub")))
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive")
    return user


class VendorAssignment(BaseModel):
    item_no: str
    vendor_no: Optional[str] = None
    vendor_name: Optional[str] = None


class SendReportRequest(BaseModel):
    recipients: Optional[List[str]] = None


class POLineIn(BaseModel):
    item_no: str
    description: Optional[str] = ""
    quantity: float
    unit_cost: float = 0


class GeneratePORequest(BaseModel):
    vendor_no: Optional[str] = None
    vendor_name: str
    lines: List[POLineIn]
    notes: Optional[str] = None
    send_email: bool = True
    cc: Optional[List[str]] = None


@router.get("/requirements")
async def get_requirements(
    include_met: bool = Query(False, description="Include items whose demand is already covered"),
    horizon_weeks: Optional[int] = Query(5, description="Only count sales-order demand due within N weeks (time-phasing); 0/blank = no horizon"),
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """Live purchasing requirements: per-item net need + vendor grouping."""
    return purchasing_demand_service.compute_requirements(
        db, include_met=include_met,
        horizon_weeks=horizon_weeks if horizon_weeks else None,
    )


@router.get("/so-coverage")
async def get_so_coverage(
    buy_window_days: int = Query(
        SO_BUY_WINDOW_DEFAULT,
        ge=0, le=180,
        description="Items bought this close to delivery are deliberate just-in-time buys; "
                    "anything still uncovered inside this window is a genuine miss",
    ),
    attention_window_days: int = Query(
        SO_ATTENTION_WINDOW_DEFAULT,
        ge=0, le=365,
        description="How far out an order still counts as needing attention now",
    ),
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """Per-sales-order purchasing coverage — what has nothing bought for it yet,
    and what has had items missed."""
    return so_coverage_service.build(
        db,
        buy_window_days=buy_window_days,
        attention_window_days=attention_window_days,
    )


@router.get("/so-master-crosscheck")
async def get_so_master_crosscheck(
    buy_window_days: int = Query(SO_BUY_WINDOW_DEFAULT, ge=0, le=180),
    attention_window_days: int = Query(SO_ATTENTION_WINDOW_DEFAULT, ge=0, le=365),
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """Cross-check our SO coverage (raw-material purchasing) against BC's
    native SalesOrderMaster per-line production status. Surfaces orders
    where the two signals disagree — see so_master_crosscheck_service for
    what that means in each direction."""
    return so_master_crosscheck_service.build(
        db,
        buy_window_days=buy_window_days,
        attention_window_days=attention_window_days,
    )


@router.post("/refresh-vendors")
async def refresh_vendors(
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """Repopulate item→vendor mapping from purchase history + BC item cards."""
    stats = vendor_map_service.refresh(db)
    db.commit()
    return {"success": True, "stats": stats}


@router.get("/vendors")
async def list_vendors(
    admin: User = Depends(get_current_admin),
):
    """BC vendor list for assignment dropdowns."""
    vendors = bc_client.get_vendors(top=500)
    return {
        "vendors": [
            {"number": v.get("number"), "name": v.get("displayName")}
            for v in vendors
            if v.get("number")
        ]
    }


@router.put("/vendor-map")
async def assign_vendor(
    body: VendorAssignment,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """Manually assign/override an item's vendor (always wins over auto sources)."""
    row = vendor_map_service.set_manual(db, body.item_no, body.vendor_no, body.vendor_name)
    db.commit()
    return {
        "success": True,
        "item_no": row.bc_item_number,
        "vendor_no": row.vendor_no,
        "vendor_name": row.vendor_name,
        "source": row.source,
    }


@router.post("/send-report")
async def send_report(
    body: SendReportRequest = None,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """Send the purchasing digest now (manual trigger)."""
    recipients = body.recipients if body else None
    result = purchasing_report_service.send_daily_report(db, recipients=recipients)
    return result


@router.post("/planning-workbook/run")
async def run_planning_workbook(
    body: SendReportRequest = None,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """Build, snapshot, and deliver the daily planning workbook now (manual trigger)."""
    recipients = body.recipients if body else None
    vendor_map_service.refresh(db)
    db.commit()
    return planning_workbook_service.build_and_deliver(db, recipients=recipients)


@router.get("/planning-workbook/download")
async def download_planning_workbook(
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """Build and return the planning workbook for preview (no snapshot, no delivery)."""
    xlsx, _ = planning_workbook_service.build_workbook_bytes(db)
    from datetime import date as _date
    fname = f"OPENDC_Planning_{_date.today().isoformat()}.xlsx"
    return Response(
        content=xlsx,
        media_type=XLSX_MIME,
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@router.post("/generate-po")
async def generate_po(
    body: GeneratePORequest,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """Create a PO in BC for one vendor and email the PDF to that vendor."""
    try:
        result = purchasing_po_service.create_and_send(
            db,
            vendor_no=body.vendor_no,
            vendor_name=body.vendor_name,
            lines=[ln.model_dump() for ln in body.lines],
            user_id=admin.id,
            notes=body.notes,
            send_email=body.send_email,
            cc=body.cc,
        )
        db.commit()
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"PO generation failed: {e}")
        raise HTTPException(status_code=502, detail=f"PO generation failed: {e}")


# ==================== Nightly auto-PO ====================

@router.get("/auto-po/status")
async def auto_po_status(
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """Whether the nightly auto-PO job is enabled, plus the most recent runs."""
    from app.db.models import AppSettings, POAgentLog
    setting = db.query(AppSettings).filter(
        AppSettings.setting_key == "auto_po_enabled"
    ).first()
    recent = (
        db.query(POAgentLog)
        .filter(POAgentLog.is_auto.is_(True))
        .order_by(POAgentLog.created_at.desc())
        .limit(50)
        .all()
    )
    return {
        "enabled": bool(setting.setting_value) if setting else False,
        "schedule": "05:00 America/Edmonton, Mon-Fri",
        "recent_pos": [
            {
                "id": r.id,
                "bc_po_number": r.bc_po_number,
                "vendor_name": r.vendor_name,
                "status": r.bc_status or r.status,
                "total_amount": float(r.total_amount or 0),
                "sales_orders": list((r.so_allocations or {}).keys()),
                "po_run_id": r.po_run_id,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in recent
        ],
    }


@router.post("/auto-po/run")
async def auto_po_run(
    dry_run: bool = Query(True, description="Preview only — don't create POs in BC or advance the watermark"),
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """Run the nightly auto-PO logic now. Defaults to dry-run; pass
    dry_run=false to actually draft the POs in BC (Draft status, no email)."""
    from app.services.auto_po_service import auto_po_service
    if not dry_run:
        vendor_map_service.refresh(db)
        db.commit()
    try:
        result = auto_po_service.run(db, dry_run=dry_run, created_by=admin.id)
        db.commit()
        return result
    except Exception as e:
        db.rollback()
        logger.error(f"Auto-PO run failed: {e}", exc_info=True)
        raise HTTPException(status_code=502, detail=f"Auto-PO run failed: {e}")


@router.post("/auto-po/seed")
async def auto_po_seed(
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """Mark all currently-open SO demand as already covered (no POs drafted).
    Run once before turning the nightly job on so its first run only acts on
    orders that arrive afterwards."""
    from app.services.auto_po_service import auto_po_service
    try:
        result = auto_po_service.seed_snapshot(db)
        db.commit()
        return result
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=502, detail=f"Auto-PO seed failed: {e}")


@router.get("/so-po-links")
async def so_po_links(
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """Per-sales-order purchase-order linkage (tool-created POs only)."""
    from app.services.po_so_link_service import po_so_link_service
    return {"links": po_so_link_service.links_by_so(db)}


# ==================== Cut work orders (yay/nay approval) ====================

class CutDecisionRequest(BaseModel):
    so_number: str
    reason: Optional[str] = None


@router.get("/cut-work-orders")
async def list_cut_work_orders(
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """Live per-SO cut proposals for the approval window: which jobs become
    shippable now by cutting stock on hand, each with the donor inventory that
    triggered it and any prior verdict."""
    from app.services.cut_work_order_service import cut_work_order_service
    proposals = cut_work_order_service.build_live_proposals(db)
    return {"work_orders": proposals, "count": len(proposals)}


@router.post("/cut-work-orders/approve")
async def approve_cut_work_order(
    body: CutDecisionRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """Approve one SO's cut plan. Rebuilds the proposal server-side (so the
    journal is authoritative), persists it, and records a verdict per cut."""
    from app.services.cut_work_order_service import cut_work_order_service
    proposals = cut_work_order_service.build_live_proposals(db, so_number=body.so_number)
    if not proposals:
        raise HTTPException(status_code=404, detail=f"No cut proposal for {body.so_number}")
    wo = cut_work_order_service.approve(db, proposals[0], created_by=admin.id)
    db.commit()
    return {"success": True, "work_order": wo.to_dict()}


@router.post("/cut-work-orders/reject")
async def reject_cut_work_order(
    body: CutDecisionRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """Reject one SO's cut plan, recording the reason as the learning signal."""
    from app.services.cut_work_order_service import cut_work_order_service
    proposals = cut_work_order_service.build_live_proposals(db, so_number=body.so_number)
    if not proposals:
        raise HTTPException(status_code=404, detail=f"No cut proposal for {body.so_number}")
    wo = cut_work_order_service.reject(db, proposals[0], reason=body.reason, created_by=admin.id)
    db.commit()
    return {"success": True, "work_order": wo.to_dict()}


@router.get("/cut-work-orders/journals")
async def cut_work_order_journals(
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """Filled-out item journals for approved cuts awaiting manual posting."""
    from app.services.cut_worksheet_service import cut_worksheet_service
    from app.services.cut_work_order_service import cut_work_order_service
    return {
        "journals": cut_worksheet_service.journal_rows(db),
        "pending": [wo.to_dict() for wo in cut_work_order_service.pending_posting(db)],
    }


class MarkPostedRequest(BaseModel):
    work_order_id: int
    document_no: str


@router.post("/cut-work-orders/mark-posted")
async def mark_cut_work_order_posted(
    body: MarkPostedRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """Mark an approved work order's journal as posted in BC (Joey posts by hand)."""
    from app.services.cut_work_order_service import cut_work_order_service
    wo = cut_work_order_service.mark_posted(db, body.work_order_id, body.document_no)
    if wo is None:
        raise HTTPException(status_code=404, detail="Work order not found")
    db.commit()
    return {"success": True, "work_order": wo.to_dict()}


@router.get("/cut-rules/proposals")
async def cut_rule_proposals(
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """Suggested suppression rules from repeated rejections (not yet in effect)."""
    from app.services.cut_rule_service import cut_rule_service
    return {"proposals": cut_rule_service.propose(db)}


@router.get("/cut-rules")
async def list_cut_rules(
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """Active ratified cut rules the solver honours."""
    from app.services.cut_rule_service import cut_rule_service
    return {"rules": [r.to_dict() for r in cut_rule_service.list_rules(db)]}


class CutRuleIn(BaseModel):
    scope: str = "pair"                 # pair | family
    donor_sku: Optional[str] = None
    target_sku: Optional[str] = None
    cut_family: Optional[str] = None
    reason: Optional[str] = None


@router.post("/cut-rules")
async def create_cut_rule(
    body: CutRuleIn,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """Ratify a rule — from here the solver stops proposing that cut."""
    from app.services.cut_rule_service import cut_rule_service
    try:
        rule = cut_rule_service.create_rule(
            db, scope=body.scope, donor_sku=body.donor_sku, target_sku=body.target_sku,
            cut_family=body.cut_family, reason=body.reason, created_by=admin.id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    db.commit()
    return {"success": True, "rule": rule.to_dict()}


@router.delete("/cut-rules/{rule_id}")
async def deactivate_cut_rule(
    rule_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """Turn a rule off — the solver may propose that cut again."""
    from app.services.cut_rule_service import cut_rule_service
    rule = cut_rule_service.deactivate(db, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Rule not found")
    db.commit()
    return {"success": True, "rule": rule.to_dict()}


@router.get("/cut-work-orders/history")
async def cut_work_order_history(
    limit: int = Query(50, le=200),
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """Recently decided cut work orders (approved / rejected / posted)."""
    from app.db.models import CutWorkOrder
    rows = (
        db.query(CutWorkOrder)
        .order_by(CutWorkOrder.created_at.desc())
        .limit(limit)
        .all()
    )
    return {"work_orders": [r.to_dict() for r in rows]}
