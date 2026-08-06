"""Header dependencies for RISE API."""

from typing import Optional
from fastapi import Header, HTTPException, status


async def require_idempotency_key(
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
) -> str:
    if not idempotency_key:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Missing required header: Idempotency-Key",
        )
    return idempotency_key
