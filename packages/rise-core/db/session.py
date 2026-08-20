import os
import logging
from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/rise_dev"
)

def _init_engine():
    if "postgresql" in DATABASE_URL:
        try:
            # Scaled connection pool with auto-reconnect pre-ping & leak listener cleanup
            test_engine = create_engine(
                DATABASE_URL,
                pool_size=25,
                max_overflow=25,
                pool_pre_ping=True,
                pool_recycle=1800,
                connect_args={"connect_timeout": 5},
            )
            with test_engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return test_engine
        except Exception as exc:
            logger.warning("PostgreSQL on localhost:5432 not reachable (%s). Falling back to SQLite rise_dev.db", exc)
            sqlite_url = "sqlite:///./rise_dev.db"
            sqlite_engine = create_engine(sqlite_url, connect_args={"check_same_thread": False})
            try:
                from db.base import Base
                import db.models  # Ensure models are loaded
                Base.metadata.create_all(bind=sqlite_engine)
            except Exception as e:
                logger.warning("Could not auto-create SQLite tables: %s", e)
            return sqlite_engine
    return create_engine(DATABASE_URL, pool_pre_ping=True)


engine = _init_engine()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def tenant_session(tenant_id: str, db: Session = None) -> Generator[Session, None, None]:
    close_session = False
    if db is None:
        db = SessionLocal()
        close_session = True

    try:
        if "postgresql" in str(db.bind.url):
            db.execute(
                text("SELECT set_config('app.current_tenant_id', :tenant_id, false)"),
                {"tenant_id": str(tenant_id)},
            )
        yield db
    finally:
        if close_session:
            db.close()
