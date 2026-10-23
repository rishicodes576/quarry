"""Account invitations, recovery, MFA, revocation and durable security events."""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    for statement in [
        "ALTER TABLE users ADD COLUMN disabled BOOLEAN NOT NULL DEFAULT false",
        "ALTER TABLE users ADD COLUMN mfa_secret TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE users ADD COLUMN mfa_pending TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE users ADD COLUMN mfa_pending_until FLOAT NOT NULL DEFAULT 0",
        "ALTER TABLE users ADD COLUMN mfa_last_step INTEGER NOT NULL DEFAULT -1",
        "ALTER TABLE users ADD COLUMN recovery_codes JSON NOT NULL DEFAULT '[]'",
        "ALTER TABLE sessions ADD COLUMN created_at FLOAT NOT NULL DEFAULT EXTRACT(EPOCH FROM NOW())",
        "ALTER TABLE sessions ADD COLUMN last_seen_at FLOAT NOT NULL DEFAULT EXTRACT(EPOCH FROM NOW())",
        "CREATE TABLE account_tokens (digest VARCHAR(64) PRIMARY KEY, purpose VARCHAR(20) NOT NULL, email VARCHAR(254) NOT NULL, workspace_id VARCHAR(32) REFERENCES workspaces(id), role VARCHAR(20) NOT NULL, expires_at FLOAT NOT NULL, consumed_at FLOAT)",
        "CREATE INDEX ix_account_tokens_email ON account_tokens (email)",
        "CREATE TABLE auth_audit (id VARCHAR(32) PRIMARY KEY, user_id VARCHAR(32) NOT NULL, workspace_id VARCHAR(32) NOT NULL, action VARCHAR(40) NOT NULL, created_at FLOAT NOT NULL)",
        "CREATE INDEX ix_auth_audit_user_id ON auth_audit (user_id)",
        "CREATE INDEX ix_auth_audit_workspace_id ON auth_audit (workspace_id)",
        "CREATE TABLE account_mail (id VARCHAR(32) PRIMARY KEY, sealed TEXT NOT NULL, expires_at FLOAT NOT NULL, sent BOOLEAN NOT NULL)",
    ]:
        op.execute(statement)


def downgrade():
    op.execute("DROP TABLE account_mail")
    op.execute("DROP TABLE auth_audit")
    op.execute("DROP TABLE account_tokens")
    for column in ["created_at", "last_seen_at"]:
        op.execute("ALTER TABLE sessions DROP COLUMN " + column)
    for column in [
        "disabled",
        "mfa_secret",
        "mfa_pending",
        "mfa_pending_until",
        "mfa_last_step",
        "recovery_codes",
    ]:
        op.execute("ALTER TABLE users DROP COLUMN " + column)
