import os
import sys

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-supabase-secret-rise-unit-tests")
os.environ.setdefault("SLACK_SIGNING_SECRET", "test-slack-signing-secret")
os.environ.setdefault("GITHUB_WEBHOOK_SECRET", "test-github-secret")
os.environ.setdefault("ALERTMANAGER_WEBHOOK_SECRET", "test-alertmanager-secret")
os.environ.setdefault("ENVIRONMENT", "test")

from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID

sys.path.insert(0, os.path.abspath("packages/rise-core"))
sys.path.insert(0, os.path.abspath("."))

@compiles(JSONB, "sqlite")
def visit_JSONB(element, compiler, **kw):
    return "JSON"

@compiles(PG_UUID, "sqlite")
def visit_UUID(element, compiler, **kw):
    return "TEXT"

from db.base import Base

def _patch_metadata_for_sqlite(metadata):
    for table in metadata.tables.values():
        for col in table.columns:
            if col.server_default is None:
                continue
            try:
                raw = str(col.server_default.arg)
            except Exception:
                raw = ""
            if "gen_random_uuid" in raw:
                col.server_default = None

_patch_metadata_for_sqlite(Base.metadata)
