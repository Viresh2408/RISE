"""Create llm_usage_log table

Revision ID: 0003_llm_usage_log
Revises: 0002_incidents_updated_at_service_auto_created
Create Date: 2026-08-02 03:00:00.000000

One row per LLM call (primary + repair attempts, successes and failures).
Tracks provider, model, token counts, estimated cost, latency, and outcome.

Design notes
------------
- ``prompt_hash`` stores SHA-256 of the prompt, not the prompt itself, to avoid
  inadvertently persisting PII or secrets from log/telemetry context.
- ``cost_usd`` is an estimate; 0.0 for self-hosted providers (Ollama).
- ``is_repair_attempt`` distinguishes the first call from the repair (second) call
  so aggregate queries can break down first-attempt vs. repair rates.
- Index on ``called_at DESC`` supports time-range queries for cost dashboards.
- Index on ``provider`` supports per-provider aggregation.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003_llm_usage_log"
down_revision: Union[str, None] = "0002_incidents_updated_at_service_auto_created"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "llm_usage_log",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        # SHA-256 hex digest of the prompt text.
        sa.Column("prompt_hash", sa.String(64), nullable=False),
        sa.Column("input_tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer, nullable=False, server_default="0"),
        # Estimated cost in USD; 0.0 if pricing is unknown.
        sa.Column(
            "cost_usd",
            sa.Numeric(precision=18, scale=10),
            nullable=False,
            server_default="0",
        ),
        sa.Column("latency_ms", sa.Integer, nullable=False, server_default="0"),
        sa.Column("success", sa.Boolean, nullable=False),
        # "provider_error" | "validation_error" | "repair_failed" | NULL
        sa.Column("error_type", sa.String(50), nullable=True),
        sa.Column(
            "is_repair_attempt",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "called_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # Supports time-range queries (cost dashboards, recent-call drilldowns).
    op.create_index(
        "idx_llm_usage_log_called_at",
        "llm_usage_log",
        [sa.text("called_at DESC")],
    )
    # Supports per-provider aggregation queries.
    op.create_index(
        "idx_llm_usage_log_provider",
        "llm_usage_log",
        ["provider"],
    )


def downgrade() -> None:
    op.drop_index("idx_llm_usage_log_provider", table_name="llm_usage_log")
    op.drop_index("idx_llm_usage_log_called_at", table_name="llm_usage_log")
    op.drop_table("llm_usage_log")
