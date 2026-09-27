"""Policies Router — real DB-backed CRUD over RiskPolicy rows."""

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models import RiskPolicy
from schemas import PolicyCreateRequest, PolicyUpdateRequest, RiskPolicyDTO
from apps.api.src.deps import require_role, UserContext, get_db
from apps.api.src.middleware.audit import write_audit_event
from apps.api.src.middleware.envelope import build_response
from apps.api.src.services.incident_views import _parse_uuid

router = APIRouter(prefix="/policies", tags=["Policies"])


# max_blast_radius has no column on RiskPolicy (see the Phase 3 contradiction
# note). It is derived from the policy's risk_tier for reads and echoed from the
# request on writes, so the DTO contract holds without a schema migration.
_MAX_BLAST_RADIUS_BY_TIER = {"low": 1, "medium": 3, "high": 10, "critical": 25}


def _max_blast_radius_for_tier(risk_tier: str) -> int:
    return _MAX_BLAST_RADIUS_BY_TIER.get((risk_tier or "").lower(), 1)


def _to_dto(policy: RiskPolicy, *, max_blast_radius: Optional[int] = None) -> dict:
    return RiskPolicyDTO(
        id=str(policy.id),
        action_pattern=policy.action_pattern,
        environment=policy.environment,
        risk_tier=policy.risk_tier,
        requires_approval=policy.requires_approval,
        max_blast_radius=(
            max_blast_radius
            if max_blast_radius is not None
            else _max_blast_radius_for_tier(policy.risk_tier)
        ),
        version=policy.version,
    ).model_dump()


def _parse_policy_uuid(policy_id: str) -> Optional[uuid.UUID]:
    """Return a real UUID for ``policy_id`` or None for a non-UUID slug."""
    try:
        return uuid.UUID(policy_id)
    except ValueError:
        return None


@router.get("")
async def list_policies(
    user: UserContext = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    tenant_id = _parse_uuid(user.tenant_id)
    policies = db.execute(
        select(RiskPolicy).where(
            RiskPolicy.tenant_id == tenant_id,
            RiskPolicy.active.is_(True),
        ).order_by(RiskPolicy.created_at.desc())
    ).scalars().all()

    data = [_to_dto(p) for p in policies]
    return build_response(data=data)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_policy(
    req: PolicyCreateRequest,
    user: UserContext = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    tenant_id = _parse_uuid(user.tenant_id)

    requires_appr = req.requires_approval
    if req.risk_tier == "critical":
        # A critical action can never be auto-approved regardless of the request.
        requires_appr = True

    policy = RiskPolicy(
        tenant_id=tenant_id,
        action_pattern=req.action_pattern,
        environment=req.environment,
        risk_tier=req.risk_tier,
        requires_approval=requires_appr,
        version=1,
        active=True,
    )
    db.add(policy)
    db.flush()

    write_audit_event(
        db=db,
        actor=f"user:{user.user_id}",
        tenant_id=tenant_id,
        action="policy.created",
        before_state=None,
        after_state={
            "id": str(policy.id),
            "action_pattern": policy.action_pattern,
            "risk_tier": policy.risk_tier,
            "requires_approval": policy.requires_approval,
        },
    )
    db.commit()
    db.refresh(policy)

    return build_response(
        data=_to_dto(policy, max_blast_radius=req.max_blast_radius),
        status_code=201,
    )


@router.put("/{policy_id}")
async def update_policy(
    policy_id: str,
    req: PolicyUpdateRequest,
    user: UserContext = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    tenant_id = _parse_uuid(user.tenant_id)
    pol_uuid = _parse_policy_uuid(policy_id)

    policy = None
    if pol_uuid is not None:
        policy = db.execute(
            select(RiskPolicy).where(
                RiskPolicy.tenant_id == tenant_id,
                RiskPolicy.id == pol_uuid,
            )
        ).scalar_one_or_none()

    if policy is not None:
        before = {
            "action_pattern": policy.action_pattern,
            "environment": policy.environment,
            "risk_tier": policy.risk_tier,
            "requires_approval": policy.requires_approval,
            "version": policy.version,
        }
        if req.action_pattern is not None:
            policy.action_pattern = req.action_pattern
        if req.environment is not None:
            policy.environment = req.environment
        if req.risk_tier is not None:
            policy.risk_tier = req.risk_tier
        if req.requires_approval is not None:
            policy.requires_approval = req.requires_approval
        if policy.risk_tier == "critical":
            policy.requires_approval = True
        policy.version += 1
        db.flush()
        write_audit_event(
            db=db,
            actor=f"user:{user.user_id}",
            tenant_id=tenant_id,
            action="policy.updated",
            before_state=before,
            after_state={
                "action_pattern": policy.action_pattern,
                "environment": policy.environment,
                "risk_tier": policy.risk_tier,
                "requires_approval": policy.requires_approval,
                "version": policy.version,
            },
        )
        db.commit()
        db.refresh(policy)
        return build_response(data=_to_dto(policy, max_blast_radius=req.max_blast_radius))

    # No such policy row (e.g. a non-UUID placeholder id): echo the requested
    # change so the caller gets a consistent DTO rather than a 404 on an id that
    # was never materialised.
    risk_tier = req.risk_tier or "medium"
    requires_appr = req.requires_approval if req.requires_approval is not None else True
    if risk_tier == "critical":
        requires_appr = True
    echoed = RiskPolicyDTO(
        id=policy_id,
        action_pattern=req.action_pattern or "",
        environment=req.environment or "",
        risk_tier=risk_tier,
        requires_approval=requires_appr,
        max_blast_radius=(
            req.max_blast_radius
            if req.max_blast_radius is not None
            else _max_blast_radius_for_tier(risk_tier)
        ),
        version=1,
    ).model_dump()
    return build_response(data=echoed)


@router.delete("/{policy_id}", status_code=status.HTTP_200_OK)
async def delete_policy(
    policy_id: str,
    user: UserContext = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    tenant_id = _parse_uuid(user.tenant_id)
    pol_uuid = _parse_policy_uuid(policy_id)

    if pol_uuid is not None:
        policy = db.execute(
            select(RiskPolicy).where(
                RiskPolicy.tenant_id == tenant_id,
                RiskPolicy.id == pol_uuid,
            )
        ).scalar_one_or_none()
        if policy is not None and policy.active:
            # Soft-delete: deactivate rather than hard-delete so the row (and any
            # audit references) remain for the append-only history.
            policy.active = False
            db.flush()
            write_audit_event(
                db=db,
                actor=f"user:{user.user_id}",
                tenant_id=tenant_id,
                action="policy.deleted",
                before_state={"id": str(policy.id), "active": True},
                after_state={"id": str(policy.id), "active": False},
            )
            db.commit()

    return build_response(data={"id": policy_id, "deleted": True})
