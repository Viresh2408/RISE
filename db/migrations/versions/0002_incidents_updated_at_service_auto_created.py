"""Add incidents.updated_at and services.is_auto_created

Revision ID: 0002_incidents_updated_at_service_auto_created
Revises: 0001_initial_schema
Create Date: 2026-08-01 22:00:00.000000

Two additive changes:
  1. incidents.updated_at — timestamp kept in sync with a BEFORE UPDATE trigger so
     every mutating write (ORM or raw SQL) refreshes it without relying on
     SQLAlchemy onupdate, which only fires through ORM flush.
  2. services.is_auto_created — boolean flag set TRUE when a Service row is created
     automatically by the POST /incidents name-lookup fallback so admins can later
     review near-duplicate service names.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002_incidents_updated_at_service_auto_created"
down_revision: Union[str, None] = "0001_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── 1. incidents.updated_at ───────────────────────────────────────────────
    op.add_column(
        "incidents",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # DB-level trigger: keeps updated_at fresh on every UPDATE regardless of
    # whether the mutation comes from the ORM or a raw SQL statement.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION set_incidents_updated_at()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            NEW.updated_at := now();
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_incidents_updated_at
        BEFORE UPDATE ON incidents
        FOR EACH ROW EXECUTE FUNCTION set_incidents_updated_at();
        """
    )

    # ── 2. services.is_auto_created ───────────────────────────────────────────
    op.add_column(
        "services",
        sa.Column(
            "is_auto_created",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    # Remove trigger before dropping column to avoid dependency errors
    op.execute("DROP TRIGGER IF EXISTS trg_incidents_updated_at ON incidents")
    op.execute("DROP FUNCTION IF EXISTS set_incidents_updated_at()")
    op.drop_column("incidents", "updated_at")
    op.drop_column("services", "is_auto_created")
