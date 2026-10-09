"""Durable approval intent and single-use request results."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0007_approval_intent"
down_revision = "0006_policy_limits"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("approvals", sa.Column("idempotency_key", sa.String(255), nullable=True))
    op.add_column("approvals", sa.Column("request_hash", sa.String(64), nullable=True))
    op.add_column("approvals", sa.Column("response", JSONB(), nullable=True))
    op.create_index("uq_approval_request_key", "approvals", ["tenant_id", "idempotency_key"], unique=True)


def downgrade() -> None:
    op.drop_index("uq_approval_request_key", table_name="approvals")
    for column in ("response", "request_hash", "idempotency_key"):
        op.drop_column("approvals", column)
