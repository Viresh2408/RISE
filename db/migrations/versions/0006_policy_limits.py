"""Persist the limits that authorize scoped automatic execution."""

from alembic import op
import sqlalchemy as sa

revision = "0006_policy_limits"
down_revision = "0005_impact_risk_score"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("risk_policies", sa.Column("max_blast_radius", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("risk_policies", sa.Column("min_confidence", sa.Float(), nullable=False, server_default="0.90"))
    op.create_check_constraint("ck_policy_blast_radius", "risk_policies", "max_blast_radius >= 0")
    op.create_check_constraint("ck_policy_confidence", "risk_policies", "min_confidence >= 0 AND min_confidence <= 1")


def downgrade() -> None:
    op.drop_constraint("ck_policy_confidence", "risk_policies", type_="check")
    op.drop_constraint("ck_policy_blast_radius", "risk_policies", type_="check")
    op.drop_column("risk_policies", "min_confidence")
    op.drop_column("risk_policies", "max_blast_radius")
