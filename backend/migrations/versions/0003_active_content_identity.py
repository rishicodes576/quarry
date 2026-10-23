"""Allow a historical source version to be uploaded again as a new version."""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("DROP INDEX ix_doc_workspace_hash")
    op.execute(
        "CREATE UNIQUE INDEX ix_doc_workspace_hash ON documents (workspace_id, content_hash) WHERE deleted = false AND status <> 'superseded'"
    )


def downgrade():
    op.execute("DROP INDEX ix_doc_workspace_hash")
    op.execute(
        "CREATE UNIQUE INDEX ix_doc_workspace_hash ON documents (workspace_id, content_hash) WHERE deleted = false"
    )
