"""Migration 0004: Evidence Grounding — add grounding fields to Evidence table.

Adds:
  - evidence.commit_sha     (TEXT, nullable)   — GitHub commit SHA at fetch time
  - evidence.file_path      (TEXT, nullable)   — repo-relative file path
  - evidence.line_start     (INTEGER, nullable) — first relevant line (1-indexed)
  - evidence.line_end       (INTEGER, nullable) — last relevant line (1-indexed)
  - evidence.fetched_at     (TIMESTAMPTZ, nullable) — when evidence was fetched

Also adds:
  - agent_state.raw_evidence_record (JSONB, nullable) — verbatim fetch record for grounding audit

Rationale:
  Before this migration, Evidence rows stored only a text excerpt and reference.
  This made it impossible to verify that a code diff was grounded in the real
  file content at a known commit. These columns store the structured attribution
  that the evidence chain endpoint exposes for verification.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


# revision identifiers
revision = "0004_evidence_grounding"
down_revision = "0003_llm_usage_log"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Evidence table: grounding attribution columns
    op.add_column(
        "evidence",
        sa.Column("commit_sha", sa.Text, nullable=True, comment="GitHub commit SHA at which this evidence was fetched"),
    )
    op.add_column(
        "evidence",
        sa.Column("file_path", sa.Text, nullable=True, comment="Repo-relative file path (e.g. apps/api/src/deps/redis.py)"),
    )
    op.add_column(
        "evidence",
        sa.Column("line_start", sa.Integer, nullable=True, comment="First line of relevant code region (1-indexed)"),
    )
    op.add_column(
        "evidence",
        sa.Column("line_end", sa.Integer, nullable=True, comment="Last line of relevant code region (1-indexed)"),
    )
    op.add_column(
        "evidence",
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Timestamp when evidence was fetched from its real source",
        ),
    )

    # agent_step_results: store raw verbatim evidence record for grounding audit
    # This avoids a separate table — the raw record is indexed per pipeline run.
    op.add_column(
        "agent_step_results",
        sa.Column(
            "raw_evidence_record",
            sa.JSON,
            nullable=True,
            comment=(
                "Verbatim fetch record from Context Builder: exact bytes returned by "
                "each data source fetcher. Used for grounding audit, not an LLM summary."
            ),
        ),
    )


def downgrade() -> None:
    op.drop_column("agent_step_results", "raw_evidence_record")
    op.drop_column("evidence", "fetched_at")
    op.drop_column("evidence", "line_end")
    op.drop_column("evidence", "line_start")
    op.drop_column("evidence", "file_path")
    op.drop_column("evidence", "commit_sha")
