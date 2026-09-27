"""Root Cause and Impact Router — real DB-backed reads."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models import Incident, Service
from apps.api.src.deps import require_role, UserContext, get_db
from apps.api.src.middleware.envelope import build_response
from apps.api.src.services.incident_views import (
    _parse_uuid,
    build_impact_view,
    build_root_cause_view,
)

router = APIRouter(prefix="/incidents/{incident_id}", tags=["Root Cause & Impact"])


def _load_incident(db: Session, tenant_id, incident_id: str) -> Incident:
    inc = db.execute(
        select(Incident).where(Incident.id == _parse_uuid(incident_id))
    ).scalar_one_or_none()
    if inc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": f"Incident {incident_id} not found", "details": {}},
        )
    return inc


def _service_name(db: Session, incident: Incident) -> str:
    if incident.affected_service_id:
        svc = db.execute(
            select(Service).where(Service.id == incident.affected_service_id)
        ).scalar_one_or_none()
        return svc.name if svc else ""
    return ""


@router.get("/root-cause")
async def get_root_cause(
    incident_id: str,
    user: UserContext = Depends(require_role("viewer")),
    db: Session = Depends(get_db),
):
    tenant_id = _parse_uuid(user.tenant_id)
    incident = _load_incident(db, tenant_id, incident_id)
    service_name = _service_name(db, incident)
    rc = build_root_cause_view(db, tenant_id, incident, service_name)
    return build_response(data=rc)


@router.get("/impact")
async def get_impact(
    incident_id: str,
    user: UserContext = Depends(require_role("viewer")),
    db: Session = Depends(get_db),
):
    tenant_id = _parse_uuid(user.tenant_id)
    incident = _load_incident(db, tenant_id, incident_id)
    service_name = _service_name(db, incident)
    rc = build_root_cause_view(db, tenant_id, incident, service_name)
    impact = build_impact_view(db, tenant_id, incident, service_name, rc)
    return build_response(data=impact)
