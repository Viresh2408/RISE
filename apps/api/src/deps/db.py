"""FastAPI DB session dependency.

Yields a SQLAlchemy Session bound to the request lifecycle.
Every endpoint that needs DB access declares:

    db: Session = Depends(get_db)

The session is **not** committed here — each endpoint (or its audit
helper) is responsible for calling db.commit() exactly once, after
both the data mutation and the audit_event INSERT have been added to
the same transaction.
"""

from typing import Generator

from sqlalchemy.orm import Session

from db.session import SessionLocal


def get_db() -> Generator[Session, None, None]:
    """Yield a SQLAlchemy Session; close on request teardown."""
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()
