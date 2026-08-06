"""Root Cause and Impact Router."""

from fastapi import APIRouter, Depends
from schemas import EvidenceDTO, ImpactDTO, IncidentRefDTO, RootCauseDTO
from apps.api.src.deps import require_role, UserContext
from apps.api.src.middleware.envelope import build_response

router = APIRouter(prefix="/incidents/{incident_id}", tags=["Root Cause & Impact"])


@router.get("/root-cause")
async def get_root_cause(
    incident_id: str,
    user: UserContext = Depends(require_role("viewer")),
):
    rc = RootCauseDTO(
        cause="Memory leak in auth handler during JWT validation",
        confidence=0.87,
        evidence=[
            EvidenceDTO(
                id="ev-1",
                type="k8s_event",
                description="OOMKilled event on pod auth-service-7f8d",
                source="Kubernetes",
            )
        ],
        similar_incidents=[
            IncidentRefDTO(
                id="inc-old-45",
                title="Auth service OOM under load",
                similarity=0.92,
            )
        ],
    ).model_dump()
    return build_response(data=rc)


@router.get("/impact")
async def get_impact(
    incident_id: str,
    user: UserContext = Depends(require_role("viewer")),
):
    impact = ImpactDTO(
        blast_radius=["auth-service", "api-gateway"],
        severity="SEV2",
        estimated_users_affected=1200,
        business_impact_notes="Latency degradation for login API",
    ).model_dump()
    return build_response(data=impact)
