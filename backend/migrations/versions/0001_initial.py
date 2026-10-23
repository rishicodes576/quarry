from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

STATEMENTS = [
    "\nCREATE TABLE checkpoint_meta (\n\tid VARCHAR(80) NOT NULL, \n\tvalue JSON NOT NULL, \n\tPRIMARY KEY (id)\n)\n\n",
    "\nCREATE TABLE jobs (\n\tid VARCHAR(32) NOT NULL, \n\tworkspace_id VARCHAR(32) NOT NULL, \n\tkind VARCHAR(20) NOT NULL, \n\ttarget_id VARCHAR(32) NOT NULL, \n\tstatus VARCHAR(20) NOT NULL, \n\tattempt INTEGER NOT NULL, \n\tfence VARCHAR(32) NOT NULL, \n\tlease_until FLOAT NOT NULL, \n\tavailable_at FLOAT NOT NULL, \n\terror TEXT NOT NULL, \n\tcreated_at FLOAT NOT NULL, \n\tPRIMARY KEY (id)\n)\n\n",
    "\nCREATE TABLE rate_buckets (\n\tid VARCHAR(100) NOT NULL, \n\tcount INTEGER NOT NULL, \n\texpires_at FLOAT NOT NULL, \n\tPRIMARY KEY (id)\n)\n\n",
    "\nCREATE TABLE usage_days (\n\tid VARCHAR(64) NOT NULL, \n\tworkspace_id VARCHAR(32) NOT NULL, \n\tday VARCHAR(10) NOT NULL, \n\ttokens INTEGER NOT NULL, \n\treserved INTEGER NOT NULL, \n\tfinished_at FLOAT, \n\tPRIMARY KEY (id)\n)\n\n",
    "\nCREATE TABLE workspaces (\n\tid VARCHAR(32) NOT NULL, \n\tname VARCHAR(120) NOT NULL, \n\tcreated_at FLOAT NOT NULL, \n\tPRIMARY KEY (id)\n)\n\n",
    "\nCREATE TABLE conversations (\n\tid VARCHAR(32) NOT NULL, \n\tworkspace_id VARCHAR(32) NOT NULL, \n\ttitle VARCHAR(160) NOT NULL, \n\tcreated_at FLOAT NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(workspace_id) REFERENCES workspaces (id)\n)\n\n",
    "\nCREATE TABLE documents (\n\tid VARCHAR(32) NOT NULL, \n\tworkspace_id VARCHAR(32) NOT NULL, \n\ttitle VARCHAR(240) NOT NULL, \n\tsource_url TEXT NOT NULL, \n\tsource_key VARCHAR(240) NOT NULL, \n\tversion INTEGER NOT NULL, \n\tobject_key VARCHAR(320) NOT NULL, \n\tcontent_hash VARCHAR(64) NOT NULL, \n\tcontent TEXT NOT NULL, \n\tstatus VARCHAR(24) NOT NULL, \n\terror TEXT NOT NULL, \n\tmedia_type VARCHAR(80) NOT NULL, \n\tchunk_count INTEGER NOT NULL, \n\tdeleted BOOLEAN NOT NULL, \n\tcreated_at FLOAT NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(workspace_id) REFERENCES workspaces (id)\n)\n\n",
    "\nCREATE TABLE users (\n\tid VARCHAR(32) NOT NULL, \n\temail VARCHAR(254) NOT NULL, \n\tpassword_hash TEXT NOT NULL, \n\tworkspace_id VARCHAR(32) NOT NULL, \n\trole VARCHAR(20) NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (email), \n\tFOREIGN KEY(workspace_id) REFERENCES workspaces (id)\n)\n\n",
    "\nCREATE TABLE chunks (\n\tid VARCHAR(36) NOT NULL, \n\tworkspace_id VARCHAR(32) NOT NULL, \n\tdocument_id VARCHAR(32) NOT NULL, \n\tposition INTEGER NOT NULL, \n\ttext TEXT NOT NULL, \n\tpage INTEGER NOT NULL, \n\tsection VARCHAR(240) NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(document_id) REFERENCES documents (id)\n)\n\n",
    "\nCREATE TABLE runs (\n\tid VARCHAR(32) NOT NULL, \n\tworkspace_id VARCHAR(32) NOT NULL, \n\tconversation_id VARCHAR(32) NOT NULL, \n\tquestion TEXT NOT NULL, \n\trequest_key VARCHAR(100) NOT NULL, \n\trequest_hash VARCHAR(64) NOT NULL, \n\tprovider VARCHAR(20) NOT NULL, \n\tpaid_consent BOOLEAN NOT NULL, \n\tparent_run_id VARCHAR(32), \n\tallow_web BOOLEAN NOT NULL, \n\tretrieval_mode VARCHAR(30) NOT NULL, \n\tstatus VARCHAR(24) NOT NULL, \n\tanswer TEXT NOT NULL, \n\tevidence JSON NOT NULL, \n\tdiagnostics JSON NOT NULL, \n\ttoken_usage INTEGER NOT NULL, \n\tmodel_calls INTEGER NOT NULL, \n\treserved_tokens INTEGER NOT NULL, \n\tbilled_tokens INTEGER NOT NULL, \n\tstarted_at FLOAT, \n\terror TEXT NOT NULL, \n\tcancel_requested BOOLEAN NOT NULL, \n\tcreated_at FLOAT NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(workspace_id) REFERENCES workspaces (id), \n\tFOREIGN KEY(conversation_id) REFERENCES conversations (id)\n)\n\n",
    "\nCREATE TABLE sessions (\n\tdigest VARCHAR(64) NOT NULL, \n\tuser_id VARCHAR(32) NOT NULL, \n\texpires_at FLOAT NOT NULL, \n\tPRIMARY KEY (digest), \n\tFOREIGN KEY(user_id) REFERENCES users (id)\n)\n\n",
    "\nCREATE TABLE events (\n\tid SERIAL NOT NULL, \n\tworkspace_id VARCHAR(32) NOT NULL, \n\trun_id VARCHAR(32) NOT NULL, \n\tkind VARCHAR(40) NOT NULL, \n\tpayload JSON NOT NULL, \n\tcreated_at FLOAT NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(run_id) REFERENCES runs (id)\n)\n\n",
    "CREATE INDEX ix_jobs_workspace_id ON jobs (workspace_id)",
    "CREATE INDEX ix_jobs_target_id ON jobs (target_id)",
    "CREATE INDEX ix_job_available ON jobs (status, available_at, lease_until)",
    "CREATE INDEX ix_rate_buckets_expires_at ON rate_buckets (expires_at)",
    "CREATE INDEX ix_usage_days_workspace_id ON usage_days (workspace_id)",
    "CREATE INDEX ix_conversations_workspace_id ON conversations (workspace_id)",
    "CREATE INDEX ix_documents_workspace_id ON documents (workspace_id)",
    "CREATE UNIQUE INDEX ix_doc_workspace_hash ON documents (workspace_id, content_hash) WHERE deleted = false",
    "CREATE INDEX ix_documents_status ON documents (status)",
    "CREATE INDEX ix_users_workspace_id ON users (workspace_id)",
    "CREATE INDEX ix_chunks_workspace_id ON chunks (workspace_id)",
    "CREATE UNIQUE INDEX ix_chunk_doc_position ON chunks (document_id, position)",
    "CREATE INDEX ix_chunks_document_id ON chunks (document_id)",
    "CREATE INDEX ix_runs_conversation_id ON runs (conversation_id)",
    "CREATE INDEX ix_runs_workspace_id ON runs (workspace_id)",
    "CREATE INDEX ix_runs_status ON runs (status)",
    "CREATE UNIQUE INDEX ix_run_request ON runs (workspace_id, request_key)",
    "CREATE INDEX ix_sessions_user_id ON sessions (user_id)",
    "CREATE INDEX ix_sessions_expires_at ON sessions (expires_at)",
    "CREATE INDEX ix_events_workspace_id ON events (workspace_id)",
    "CREATE INDEX ix_events_run_id ON events (run_id)",
]


def upgrade():
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade():
    for name in [
        "events",
        "sessions",
        "runs",
        "chunks",
        "users",
        "documents",
        "conversations",
        "workspaces",
        "usage_days",
        "rate_buckets",
        "jobs",
        "checkpoint_meta",
    ]:
        op.drop_table(name)
