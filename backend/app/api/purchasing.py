"""
Purchasing tool API (Admin).

Live purchasing requirements (demand netted against stock + open POs),
vendor mapping management, daily-report trigger, and per-vendor PO generation.
"""

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status, Query
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
