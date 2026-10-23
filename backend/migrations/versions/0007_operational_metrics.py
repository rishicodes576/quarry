"""Index recent phase telemetry for bounded operational scrapes."""

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index("ix_event_recent_phase", "events", ["created_at", "kind"])


def downgrade():
    op.drop_index("ix_event_recent_phase", table_name="events")
