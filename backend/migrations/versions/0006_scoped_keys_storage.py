"""Scoped machine credentials and accounted raw source storage."""

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "CREATE TABLE api_keys (digest VARCHAR(64) PRIMARY KEY, user_id VARCHAR(32) NOT NULL REFERENCES users(id), label VARCHAR(100) NOT NULL, scope VARCHAR(20) NOT NULL, expires_at FLOAT NOT NULL, created_at FLOAT NOT NULL)"
    )
    op.execute("CREATE INDEX ix_api_keys_user_id ON api_keys (user_id)")
    op.execute("ALTER TABLE documents ADD COLUMN byte_size BIGINT NOT NULL DEFAULT 0")
    op.execute("UPDATE documents SET byte_size=OCTET_LENGTH(content) WHERE content<>''")


def downgrade():
    op.execute("DROP TABLE api_keys")
    op.execute("ALTER TABLE documents DROP COLUMN byte_size")
