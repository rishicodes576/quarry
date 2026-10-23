"""Weighted fair dispatch and shared admission state; no payment is implied by a plan."""

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE workspaces ADD COLUMN plan VARCHAR(20) NOT NULL DEFAULT 'free'")
    op.execute("ALTER TABLE workspaces ADD COLUMN fair_finish FLOAT NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE jobs ADD COLUMN cost_units FLOAT NOT NULL DEFAULT 1")
    op.execute(
        "CREATE TABLE scheduler_state (id VARCHAR(20) PRIMARY KEY, virtual_time FLOAT NOT NULL)"
    )


def downgrade():
    op.execute("DROP TABLE scheduler_state")
    op.execute("ALTER TABLE jobs DROP COLUMN cost_units")
    op.execute("ALTER TABLE workspaces DROP COLUMN fair_finish")
    op.execute("ALTER TABLE workspaces DROP COLUMN plan")
