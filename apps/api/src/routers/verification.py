"""Verification Router — real DB-backed reads."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models import Incident, VerificationResult
from schemas import CheckItemDTO, VerificationDTO
from apps.api.src.deps import require_role, UserContext, get_db
from apps.api.src.middleware.envelope import build_response
from apps.api.src.services.incident_views import _parse_uuid

router = APIRouter(prefix="/incidents/{incident_id}", tags=["Verification"])


def _normalise_check(check: Any) -> CheckItemDTO:
    """Coerce a stored check entry into a CheckItemDTO.

    Stored checks (VerificationResult.checks JSONB) come from the verification
    agent and use varying key names (result/passed/status, value/actual/detail),
    so normalise defensively rather than assume one shape.
    """
    if not isinstance(check, dict):
        return CheckItemDTO(name=str(check), result="unknown", value="")

    name = str(check.get("name") or check.get("check") or "check")

    result = check.get("result")
    if result is None:
        passed = check.get("passed")
        if passed is not None:
            result = "pass" if passed else "fail"
        else:
            result = str(check.get("status", "unknown"))

    value = check.get("value")
    if value is None:
        value = check.get("actual") or check.get("detail") or check.get("message") or ""

    return CheckItemDTO(name=name, result=str(result), value=str(value))


@router.get("/verification")
async def get_verification(
    incident_id: str,
    user: UserContext = Depends(require_role("viewer")),
    db: Session = Depends(get_db),
):
    tenant_id = _parse_uuid(user.tenant_id)
    inc_uuid = _parse_uuid(incident_id)

    incident = db.execute(
        select(Incident).where(Incident.id == inc_uuid)
    ).scalar_one_or_none()
    if incident is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": f"Incident {incident_id} not found", "details": {}},
        )

    verif = db.execute(
        select(VerificationResult).where(
            VerificationResult.tenant_id == tenant_id,
            VerificationResult.incident_id == incident.id,
        ).order_by(VerificationResult.checked_at.desc())
    ).scalars().first()

    if verif is None:
        # No verification has run for this incident yet — report that honestly
        # rather than fabricating a passed result.
        ver = VerificationDTO(status="pending", checks=[]).model_dump()
        return build_response(data=ver)

    checks = verif.checks if isinstance(verif.checks, list) else []
    ver = VerificationDTO(
        status=verif.status,
        checks=[_normalise_check(c) for c in checks],
    ).model_dump()
    return build_response(data=ver)
