"""Migration 0005: Impact Assessment Risk Score.

Adds:
  - impact_assessments.risk_score  (INTEGER NOT NULL DEFAULT 0)

Rationale:
  The Impact Analyzer Agent now computes a deterministic composite risk score
  (0-100) from blast-radius breadth, severity, estimated users affected, and
  signal strength (root-cause confidence × correlated event count). The score
  is stored here so it can be surfaced in the API without re-computation at
  query time, and so it participates in the DB-side evidence chain.

  server_default='0' ensures existing rows degrade gracefully to 0 rather
  than requiring a backfill; the impact_analyzer node populates the real
  score for all new agent pipeline runs.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


# revision identifiers
revision = "0005_impact_risk_score"
down_revision = "0004_evidence_grounding"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "impact_assessments",
        sa.Column(
            "risk_score",
            sa.Integer,
            nullable=False,
            server_default="0",
            comment=(
                "Deterministic composite risk score (0-100) computed by "
                "compute_risk_score() in schemas.agent_state. "
                "Combines severity weight, blast radius breadth, estimated users, "
                "and signal strength (confidence x correlated events). "
                "Never set by the LLM."
            ),
        ),
    )


def downgrade() -> None:
    op.drop_column("impact_assessments", "risk_score")
