import os
import logging
import uuid
from contextlib import contextmanager
from typing import Generator, Optional

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

from db.runtime import allows_local_fallbacks

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/rise_dev"
)

def _init_engine() -> Engine:
    if not allows_local_fallbacks() and not DATABASE_URL.startswith("postgresql"):
        raise RuntimeError("DATABASE_UNAVAILABLE: non-local deployments require PostgreSQL")
    if "postgresql" in DATABASE_URL:
        try:
            # Scaled connection pool with auto-reconnect pre-ping & leak listener cleanup
            test_engine = create_engine(
                DATABASE_URL,
                pool_size=25,
                max_overflow=25,
                pool_pre_ping=True,
                pool_recycle=1800,
                isolation_level="READ COMMITTED",
                connect_args={"connect_timeout": 5},
            )
            with test_engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return test_engine
        except Exception as exc:
            if not allows_local_fallbacks():
                raise RuntimeError("DATABASE_UNAVAILABLE: PostgreSQL connection failed") from exc
            logger.warning("PostgreSQL on localhost:5432 not reachable (%s). Falling back to SQLite rise_dev.db", exc)
            sqlite_url = "sqlite:///./rise_dev.db"
            sqlite_engine = create_engine(sqlite_url, connect_args={"check_same_thread": False})
            try:
                from db.base import Base
                import db.models  # noqa: F401 — registers all tables in Base.metadata
                Base.metadata.create_all(bind=sqlite_engine)
            except Exception as e:
                logger.warning("Could not auto-create SQLite tables: %s", e)
            return sqlite_engine
    if DATABASE_URL.startswith("sqlite"):
        if make_url(DATABASE_URL).database in {None, "", ":memory:"}:
            return create_engine(
                DATABASE_URL, pool_pre_ping=True,
                connect_args={"check_same_thread": False}, poolclass=StaticPool,
            )
        return create_engine(
            DATABASE_URL, pool_pre_ping=True, connect_args={"check_same_thread": False},
        )
    return create_engine(DATABASE_URL, pool_pre_ping=True)


engine = _init_engine()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@event.listens_for(Session, "after_begin")
def _set_transaction_tenant(session, transaction, connection) -> None:
    """Re-apply transaction-local RLS context after every commit or rollback.

    SET LOCAL cannot leak a tenant into the next borrower of a pooled connection.
    Session.info survives commits, so subsequent transactions retain their scope.
    """
    tenant_id = session.info.get("tenant_id")
    if tenant_id and connection.dialect.name == "postgresql":
        connection.execute(
            text("SELECT set_config('app.current_tenant_id', :tenant_id, true)"),
            {"tenant_id": str(tenant_id)},
        )


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def tenant_session(tenant_id: str, db: Optional[Session] = None) -> Generator[Session, None, None]:
    """Scope each transaction, preserving or clearing a borrowed session's scope.

    A scoped session cannot be reassigned to another tenant. Transaction-local
    settings are restored when a previously unscoped session is borrowed.
    """
    scoped_tenant = str(uuid.UUID(str(tenant_id)))
    close_session = False
    if db is None:
        db = SessionLocal()
        close_session = True

    previous_tenant = db.info.get("tenant_id")
    if previous_tenant is not None and str(previous_tenant) != scoped_tenant:
        raise ValueError("Cannot change the tenant of an already scoped session")
    db.info["tenant_id"] = scoped_tenant
    try:
        if db.get_bind().dialect.name == "postgresql":
            db.execute(
                text("SELECT set_config('app.current_tenant_id', :tenant_id, true)"),
                {"tenant_id": scoped_tenant},
            )
        yield db
    except BaseException:
        db.rollback()
        raise
    finally:
        if previous_tenant is None:
            db.info.pop("tenant_id", None)
        else:
            db.info["tenant_id"] = previous_tenant
        if close_session:
            db.close()
        elif previous_tenant is None and db.in_transaction() and db.is_active and db.get_bind().dialect.name == "postgresql":
            db.execute(
                text("SELECT set_config('app.current_tenant_id', '', true)"),
            )
