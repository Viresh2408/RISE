"""FastAPI DB session dependency.

Yields a SQLAlchemy Session bound to the request lifecycle.
Every endpoint that needs DB access declares:

    db: Session = Depends(get_db)

The session is **not** committed here — each endpoint (or its audit
helper) is responsible for calling db.commit() exactly once, after
both the data mutation and the audit_event INSERT have been added to
the same transaction.
"""

from typing import AsyncGenerator, Optional
import uuid

from fastapi import Header, HTTPException

from sqlalchemy.orm import Session

from db.session import SessionLocal
from apps.api.src.deps.auth import get_current_user


async def get_db(
    authorization: Optional[str] = Header(None),
) -> AsyncGenerator[Session, None]:
    """Yield a SQLAlchemy Session; close on request teardown."""
    db: Session = SessionLocal()
    try:
        # Webhooks bootstrap identity from a signed integration payload. JWT routes
        # bind RLS independently of dependency ordering and retain explicit WHEREs.
        if authorization:
            user = await get_current_user(authorization)
            try:
                db.info["tenant_id"] = str(uuid.UUID(user.tenant_id))
            except ValueError as exc:
                raise HTTPException(401, detail={"code": "UNAUTHORIZED", "message": "Invalid tenant identity"}) from exc
        yield db
    finally:
        db.close()
