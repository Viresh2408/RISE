"""Policies Router."""

from fastapi import APIRouter, Depends, status
from schemas import PolicyCreateRequest, PolicyUpdateRequest, RiskPolicyDTO
from apps.api.src.deps import require_role, UserContext
from apps.api.src.middleware.envelope import build_response

router = APIRouter(prefix="/policies", tags=["Policies"])


@router.get("")
async def list_policies(
    user: UserContext = Depends(require_role("admin")),
):
    policies = [
        RiskPolicyDTO(
            id="pol-001",
            action_pattern="k8s.pod.restart",
            environment="production",
            risk_tier="low",
            requires_approval=False,
            max_blast_radius=1,
            version=1,
        ).model_dump()
    ]
    return build_response(data=policies)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_policy(
    req: PolicyCreateRequest,
    user: UserContext = Depends(require_role("admin")),
):
    requires_appr = req.requires_approval
    if req.risk_tier == "critical":
        requires_appr = True

    policy = RiskPolicyDTO(
        id="pol-002",
        action_pattern=req.action_pattern,
        environment=req.environment,
        risk_tier=req.risk_tier,
        requires_approval=requires_appr,
        max_blast_radius=req.max_blast_radius,
        version=1,
    ).model_dump()
    return build_response(data=policy, status_code=201)


@router.put("/{policy_id}")
async def update_policy(
    policy_id: str,
    req: PolicyUpdateRequest,
    user: UserContext = Depends(require_role("admin")),
):
    policy = RiskPolicyDTO(
        id=policy_id,
        action_pattern=req.action_pattern or "k8s.pod.restart",
        environment=req.environment or "production",
        risk_tier=req.risk_tier or "medium",
        requires_approval=req.requires_approval if req.requires_approval is not None else True,
        max_blast_radius=req.max_blast_radius or 2,
        version=2,
    ).model_dump()
    return build_response(data=policy)
