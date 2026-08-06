"""Verification Router."""

from fastapi import APIRouter, Depends
from schemas import CheckItemDTO, VerificationDTO
from apps.api.src.deps import require_role, UserContext
from apps.api.src.middleware.envelope import build_response

router = APIRouter(prefix="/incidents/{incident_id}", tags=["Verification"])


@router.get("/verification")
async def get_verification(
    incident_id: str,
    user: UserContext = Depends(require_role("viewer")),
):
    ver = VerificationDTO(
        status="passed",
        checks=[
            CheckItemDTO(
                name="error_rate",
                result="pass",
                value="0.1%",
            )
        ],
    ).model_dump()
    return build_response(data=ver)
