"""
Project / Lot Manager API Endpoints
Multi-lot project management for home builder customers
"""

import logging
import uuid
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func
from pydantic import BaseModel
from typing import Optional, List, Any, Dict

from app.db.database import SessionLocal
from app.db.models import User, Project, ProjectLot
from app.api.customer_auth import get_current_customer

router = APIRouter(prefix="/api/customer/portal/projects", tags=["projects"])
logger = logging.getLogger(__name__)


# Dependency to get DB session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ============================================================================
# REQUEST/RESPONSE MODELS
# ============================================================================

class ProjectCreateRequest(BaseModel):
    """Create a new project"""
    name: str
    billing_mode: str = "full"  # full or staged
    notes: Optional[str] = None


class ProjectUpdateRequest(BaseModel):
    """Update a project"""
    name: Optional[str] = None
    notes: Optional[str] = None
    billing_mode: Optional[str] = None


class LotCreateItem(BaseModel):
    """Single lot in a bulk-add request"""
    lot_number: str
    address: Optional[str] = None
    door_spec: Optional[Dict[str, Any]] = None
    stage: Optional[int] = None


class LotsCreateRequest(BaseModel):
    """Bulk-add lots to a project"""
    lots: List[LotCreateItem]


class LotUpdateRequest(BaseModel):
    """Update a lot"""
    address: Optional[str] = None
    door_spec: Optional[Dict[str, Any]] = None
    stage: Optional[int] = None


class ReleaseRequest(BaseModel):
    """Release lots for ordering"""
    stage: Optional[int] = None  # null = full release, int = staged release


class LotResponse(BaseModel):
    """Lot response"""
    id: str
    project_id: str
    lot_number: str
    address: Optional[str]
    door_config_id: Optional[int]
    door_spec: Optional[Dict[str, Any]]
    stage: Optional[int]
    lot_status: str
    bc_order_id: Optional[str]
    bc_order_number: Optional[str]
    bc_invoice_id: Optional[str]
    bc_invoice_number: Optional[str]
    install_referral_id: Optional[str]
    created_at: datetime
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True


class ProjectResponse(BaseModel):
    """Project response"""
    id: str
    customer_id: int
    name: str
    status: str
    billing_mode: str
    bc_quote_id: Optional[str]
    bc_quote_number: Optional[str]
    notes: Optional[str]
    created_at: datetime
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True


class ProjectListItem(ProjectResponse):
    """Project list item with lot summary"""
    lot_count: int = 0
    lots_quoted: int = 0
    lots_released: int = 0
    lots_ordered: int = 0
    lots_shipped: int = 0
    lots_complete: int = 0


class ProjectDetailResponse(ProjectResponse):
    """Project detail with lots"""
    lots: List[LotResponse] = []


class InvoiceSummaryStage(BaseModel):
    """Invoice summary for a single stage"""
    stage: Optional[int]
    lot_count: int
    lots: List[LotResponse]
    bc_invoice_references: List[Dict[str, Optional[str]]]


class InvoiceSummaryResponse(BaseModel):
    """Invoice summary grouped by stage"""
    project_id: str
    project_name: str
    stages: List[InvoiceSummaryStage]


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def _get_project_or_404(
    db: Session, project_id: str, customer_id: int
) -> Project:
    """Get project by id, verify ownership, or raise 404."""
    project = db.query(Project).filter(
        Project.id == project_id,
        Project.customer_id == customer_id
    ).first()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found"
        )
    return project


def _lot_to_response(lot: ProjectLot) -> LotResponse:
    """Convert a ProjectLot ORM object to LotResponse."""
    return LotResponse(
        id=lot.id,
        project_id=lot.project_id,
        lot_number=lot.lot_number,
        address=lot.address,
        door_config_id=lot.door_config_id,
        door_spec=lot.door_spec,
        stage=lot.stage,
        lot_status=lot.lot_status,
        bc_order_id=lot.bc_order_id,
        bc_order_number=lot.bc_order_number,
        bc_invoice_id=lot.bc_invoice_id,
        bc_invoice_number=lot.bc_invoice_number,
        install_referral_id=lot.install_referral_id,
        created_at=lot.created_at,
        updated_at=lot.updated_at,
    )


# ============================================================================
# ENDPOINTS
# ============================================================================

@router.post("", response_model=ProjectResponse)
def create_project(
    data: ProjectCreateRequest,
    current_user: User = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    """Create a new project."""
    if data.billing_mode not in ("full", "staged"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="billing_mode must be 'full' or 'staged'"
        )

    project = Project(
        id=str(uuid.uuid4()),
        customer_id=current_user.id,
        name=data.name,
        billing_mode=data.billing_mode,
        notes=data.notes,
    )
    db.add(project)
    db.commit()
    db.refresh(project)

    logger.info(f"Project created: {project.id} by user {current_user.id}")
    return project


@router.get("", response_model=List[ProjectListItem])
def list_projects(
    current_user: User = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    """List customer's projects with lot counts and status summary."""
    projects = (
        db.query(Project)
        .filter(Project.customer_id == current_user.id)
        .order_by(Project.created_at.desc())
        .all()
    )

    result = []
    for p in projects:
        # Count lots by status
        status_counts = (
            db.query(ProjectLot.lot_status, func.count(ProjectLot.id))
            .filter(ProjectLot.project_id == p.id)
            .group_by(ProjectLot.lot_status)
            .all()
        )
        counts = dict(status_counts)

        result.append(ProjectListItem(
            id=p.id,
            customer_id=p.customer_id,
            name=p.name,
            status=p.status,
            billing_mode=p.billing_mode,
            bc_quote_id=p.bc_quote_id,
            bc_quote_number=p.bc_quote_number,
            notes=p.notes,
            created_at=p.created_at,
            updated_at=p.updated_at,
            lot_count=sum(counts.values()),
            lots_quoted=counts.get("quoted", 0),
            lots_released=counts.get("released", 0),
            lots_ordered=counts.get("ordered", 0),
            lots_shipped=counts.get("shipped", 0),
            lots_complete=counts.get("complete", 0),
        ))

    return result


@router.get("/{project_id}", response_model=ProjectDetailResponse)
def get_project(
    project_id: str,
    current_user: User = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    """Get project detail with all lots."""
    project = _get_project_or_404(db, project_id, current_user.id)

    lots = (
        db.query(ProjectLot)
        .filter(ProjectLot.project_id == project.id)
        .order_by(ProjectLot.lot_number)
        .all()
    )

    return ProjectDetailResponse(
        id=project.id,
        customer_id=project.customer_id,
        name=project.name,
        status=project.status,
        billing_mode=project.billing_mode,
        bc_quote_id=project.bc_quote_id,
        bc_quote_number=project.bc_quote_number,
        notes=project.notes,
        created_at=project.created_at,
        updated_at=project.updated_at,
        lots=[_lot_to_response(lot) for lot in lots],
    )


@router.patch("/{project_id}", response_model=ProjectResponse)
def update_project(
    project_id: str,
    data: ProjectUpdateRequest,
    current_user: User = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    """Update a project. billing_mode can only change if no lots have been released yet."""
    project = _get_project_or_404(db, project_id, current_user.id)

    if data.name is not None:
        project.name = data.name

    if data.notes is not None:
        project.notes = data.notes

    if data.billing_mode is not None:
        if data.billing_mode not in ("full", "staged"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="billing_mode must be 'full' or 'staged'"
            )
        # Check if any lots have been released (status beyond 'quoted')
        released_count = (
            db.query(func.count(ProjectLot.id))
            .filter(
                ProjectLot.project_id == project.id,
                ProjectLot.lot_status != "quoted",
            )
            .scalar()
        )
        if released_count > 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot change billing_mode after lots have been released"
            )
        project.billing_mode = data.billing_mode

    db.commit()
    db.refresh(project)

    logger.info(f"Project updated: {project.id}")
    return project


@router.post("/{project_id}/lots", response_model=List[LotResponse])
def add_lots(
    project_id: str,
    data: LotsCreateRequest,
    current_user: User = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    """Bulk-add lots to a project."""
    project = _get_project_or_404(db, project_id, current_user.id)

    if not data.lots:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one lot is required"
        )

    created_lots = []
    for item in data.lots:
        lot = ProjectLot(
            id=str(uuid.uuid4()),
            project_id=project.id,
            lot_number=item.lot_number,
            address=item.address,
            door_spec=item.door_spec,
            stage=item.stage,
        )
        db.add(lot)
        created_lots.append(lot)

    db.commit()
    for lot in created_lots:
        db.refresh(lot)

    logger.info(f"Added {len(created_lots)} lots to project {project.id}")
    return [_lot_to_response(lot) for lot in created_lots]


@router.patch("/{project_id}/lots/{lot_id}", response_model=LotResponse)
def update_lot(
    project_id: str,
    lot_id: str,
    data: LotUpdateRequest,
    current_user: User = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    """Update a lot. Only allowed if lot_status is 'quoted'."""
    project = _get_project_or_404(db, project_id, current_user.id)

    lot = db.query(ProjectLot).filter(
        ProjectLot.id == lot_id,
        ProjectLot.project_id == project.id,
    ).first()
    if not lot:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lot not found"
        )

    if lot.lot_status != "quoted":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Can only update lots with status 'quoted'"
        )

    if data.address is not None:
        lot.address = data.address
    if data.door_spec is not None:
        lot.door_spec = data.door_spec
    if data.stage is not None:
        lot.stage = data.stage

    db.commit()
    db.refresh(lot)

    logger.info(f"Lot updated: {lot.id} in project {project.id}")
    return _lot_to_response(lot)


@router.delete("/{project_id}/lots/{lot_id}")
def delete_lot(
    project_id: str,
    lot_id: str,
    current_user: User = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    """Remove a lot. Only allowed if lot_status is 'quoted'."""
    project = _get_project_or_404(db, project_id, current_user.id)

    lot = db.query(ProjectLot).filter(
        ProjectLot.id == lot_id,
        ProjectLot.project_id == project.id,
    ).first()
    if not lot:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lot not found"
        )

    if lot.lot_status != "quoted":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Can only delete lots with status 'quoted'"
        )

    db.delete(lot)
    db.commit()

    logger.info(f"Lot deleted: {lot_id} from project {project.id}")
    return {"message": "Lot deleted successfully"}


@router.post("/{project_id}/release", response_model=List[LotResponse])
def release_lots(
    project_id: str,
    data: ReleaseRequest,
    current_user: User = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    """
    Release lots for ordering.
    - Full mode (billing_mode='full'): stage must be null — releases all 'quoted' lots.
    - Staged mode (billing_mode='staged'): stage must be an int — releases matching stage lots.
    """
    project = _get_project_or_404(db, project_id, current_user.id)

    # Validate release type matches billing mode
    if project.billing_mode == "full" and data.stage is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Project is in 'full' billing mode — stage must be null for full release"
        )
    if project.billing_mode == "staged" and data.stage is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Project is in 'staged' billing mode — stage number is required"
        )

    # Build query for lots to release
    query = db.query(ProjectLot).filter(
        ProjectLot.project_id == project.id,
        ProjectLot.lot_status == "quoted",
    )

    if data.stage is not None:
        query = query.filter(ProjectLot.stage == data.stage)

    lots_to_release = query.all()

    if not lots_to_release:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No eligible lots found to release"
        )

    # Update lot statuses
    for lot in lots_to_release:
        lot.lot_status = "released"

    # TODO: BC integration — create BC sales orders for released lots.
    # This will call bc_client.create_sales_order() and bc_client.add_order_line()
    # for each released lot's door_spec, then store bc_order_id/bc_order_number on the lot.

    db.commit()
    for lot in lots_to_release:
        db.refresh(lot)

    logger.info(
        f"Released {len(lots_to_release)} lots in project {project.id} "
        f"(stage={data.stage})"
    )
    return [_lot_to_response(lot) for lot in lots_to_release]


@router.get("/{project_id}/invoice-summary", response_model=InvoiceSummaryResponse)
def get_invoice_summary(
    project_id: str,
    current_user: User = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    """Invoice summary grouped by stage with BC invoice references."""
    project = _get_project_or_404(db, project_id, current_user.id)

    lots = (
        db.query(ProjectLot)
        .filter(ProjectLot.project_id == project.id)
        .order_by(ProjectLot.stage, ProjectLot.lot_number)
        .all()
    )

    # Group lots by stage
    stages_map: Dict[Optional[int], List[ProjectLot]] = {}
    for lot in lots:
        stages_map.setdefault(lot.stage, []).append(lot)

    stages = []
    for stage_num in sorted(stages_map.keys(), key=lambda x: (x is None, x)):
        stage_lots = stages_map[stage_num]
        invoice_refs = []
        for lot in stage_lots:
            if lot.bc_invoice_id or lot.bc_invoice_number:
                invoice_refs.append({
                    "lot_id": lot.id,
                    "lot_number": lot.lot_number,
                    "bc_invoice_id": lot.bc_invoice_id,
                    "bc_invoice_number": lot.bc_invoice_number,
                })

        stages.append(InvoiceSummaryStage(
            stage=stage_num,
            lot_count=len(stage_lots),
            lots=[_lot_to_response(lot) for lot in stage_lots],
            bc_invoice_references=invoice_refs,
        ))

    return InvoiceSummaryResponse(
        project_id=project.id,
        project_name=project.name,
        stages=stages,
    )
