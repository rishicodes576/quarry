"""Keep completion timestamps on research runs."""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE runs ADD COLUMN IF NOT EXISTS finished_at DOUBLE PRECISION")
    op.execute("ALTER TABLE usage_days DROP COLUMN IF EXISTS finished_at")


def downgrade():
    op.execute("ALTER TABLE usage_days ADD COLUMN IF NOT EXISTS finished_at DOUBLE PRECISION")
    op.execute("ALTER TABLE runs DROP COLUMN IF EXISTS finished_at")
