"""Integrations Router."""

from fastapi import APIRouter, Depends, Response, status
from schemas import IntegrationConnectResponse, IntegrationDTO
from apps.api.src.deps import require_role, UserContext
from apps.api.src.middleware.envelope import build_response

router = APIRouter(prefix="/integrations", tags=["Integrations"])


@router.get("")
async def list_integrations(
    user: UserContext = Depends(require_role("admin")),
):
    integrations = [
        IntegrationDTO(
            type="github",
            status="connected",
            scopes=["repo", "workflow"],
        ).model_dump()
    ]
    return build_response(data=integrations)


@router.post("/{type}/connect")
async def connect_integration(
    type: str,
    user: UserContext = Depends(require_role("admin")),
):
    res = IntegrationConnectResponse(
        redirect_url=f"https://github.com/login/oauth/authorize?client_id=rise-app-{type}",
    ).model_dump()
    return build_response(data=res)


@router.delete("/{type}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_integration(
    type: str,
    user: UserContext = Depends(require_role("admin")),
):
    return Response(status_code=status.HTTP_204_NO_CONTENT)
