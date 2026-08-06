"""Auth Router — /auth/session endpoint.

POST /auth/session
    Exchanges a Supabase JWT for the internal session context (roles, tenant_id).
    The JWT is verified by the get_current_user dependency before the handler runs.
    Returns 401 for missing/invalid tokens (no session is created server-side).
"""

from fastapi import APIRouter, Depends
from schemas import SessionResponse
from apps.api.src.deps import get_current_user, UserContext
from apps.api.src.middleware.envelope import build_response

router = APIRouter(prefix="/auth", tags=["Auth"])


@router.post("/session")
async def get_session(user: UserContext = Depends(get_current_user)) -> dict:
    """Exchange a Supabase JWT for internal session context.

    The Authorization: Bearer <jwt> header is verified by get_current_user.
    On success, returns the decoded user_id, roles list, and tenant_id.

    Returns:
        200: SessionResponse with user_id, roles, tenant_id.
        401: Missing or invalid JWT.
    """
    data = SessionResponse(
        user_id=user.user_id,
        roles=user.roles,
        tenant_id=user.tenant_id,
    ).model_dump()
    return build_response(data=data)
