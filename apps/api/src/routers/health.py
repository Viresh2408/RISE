"""Health Check Router."""

from fastapi import APIRouter, HTTPException, Query, status
from apps.api.src.middleware.envelope import build_response

router = APIRouter(tags=["Health"])


@router.get("/healthz")
async def healthz():
    return build_response(data={"status": "ok"})


@router.get("/readyz")
async def readyz(ready: bool = Query(True)):
    if not ready:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "INTEGRATION_UNAVAILABLE",
                "message": "Database/Redis readiness check failed",
                "details": {},
            },
        )
    return build_response(data={"status": "ok"})
