import logging
from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import text
from apps.api.src.middleware.envelope import build_response
from db.session import SessionLocal
import os

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Health"])


@router.get("/healthz")
async def healthz():
    return build_response(data={"status": "ok"})


@router.get("/readyz")
async def readyz(ready: bool = Query(True)):
    checks = {
        "postgres": "unknown",
        "redis": "unknown",
        "qdrant": "unknown",
    }
    all_ok = True

    # 1. PostgreSQL check
    try:
        with SessionLocal() as session:
            session.execute(text("SELECT 1"))
        checks["postgres"] = "connected"
    except Exception as e:
        logger.warning("Postgres readiness check failed: %s", e)
        checks["postgres"] = f"error: {str(e)}"
        all_ok = False

    # 2. Redis check
    try:
        import redis
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        r = redis.Redis.from_url(redis_url, socket_timeout=2.0)
        if r.ping():
            checks["redis"] = "connected"
        else:
            checks["redis"] = "ping failed"
            all_ok = False
        r.close()
    except Exception as e:
        logger.warning("Redis readiness check failed: %s", e)
        checks["redis"] = f"error: {str(e)}"
        all_ok = False

    # 3. Qdrant check
    try:
        from knowledge_service.client import get_qdrant_client
        qdrant = get_qdrant_client()
        qdrant.get_collections()
        checks["qdrant"] = "connected"
    except Exception as e:
        logger.warning("Qdrant readiness check failed: %s", e)
        checks["qdrant"] = f"error: {str(e)}"
        all_ok = False

    overall_status = "ok" if all_ok else "degraded"

    if not ready or not all_ok:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "INTEGRATION_UNAVAILABLE",
                "message": "Readiness probe failed for one or more dependencies",
                "details": checks,
            },
        )

    return build_response(data={"status": overall_status, "checks": checks})

