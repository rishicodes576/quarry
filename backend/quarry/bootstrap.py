import hashlib
import json
import os
import time
from pathlib import Path

from alembic import command
from alembic.config import Config
from langgraph.checkpoint.postgres import PostgresSaver
from sqlalchemy import select
from sqlalchemy.engine import make_url

from quarry import retrieval, storage
from quarry.config import settings
from quarry.db import Document, User, Workspace, session
from quarry.ingest import content_hash
from quarry.model_assets import prepare
from quarry.queue import enqueue
from quarry.security import hash_password

DEMO_WORKSPACE = hashlib.sha256(b"quarry-demo-v1").hexdigest()[:32]
EVAL_WORKSPACE = hashlib.sha256(b"quarry-benchmark-v1").hexdigest()[:32]


def corpus():
    return json.loads(Path("/app/evaluation/corpus.json").read_text())


def seed_corpus(workspace_id: str, name: str):
    with session() as db, db.begin():
        if not db.get(Workspace, workspace_id):
            db.add(Workspace(id=workspace_id, name=name))
            db.flush()
        for item in corpus():
            key = f"sample:{item['id']}"
            if db.scalar(
                select(Document).where(
                    Document.workspace_id == workspace_id, Document.source_key == key
                )
            ):
                continue
            content = item["content"]
            object_key = f"{workspace_id}/{item['id']}.md"
            storage.put(object_key, content.encode(), "text/markdown")
            doc = Document(
                workspace_id=workspace_id,
                title=item["title"],
                content=content,
                content_hash=content_hash(content),
                byte_size=len(content.encode()),
                source_key=key,
                object_key=object_key,
            )
            db.add(doc)
            db.flush()
            enqueue(db, workspace_id, "ingest", doc.id)


def main():
    admin_url = os.environ.get("QUARRY_MIGRATION_DATABASE_URL") or settings().database_url
    command.upgrade(Config("alembic.ini"), "head")
    storage.init_storage()
    for attempt in range(30):
        try:
            retrieval.init_index()
            break
        except Exception:
            if attempt == 29:
                raise
            time.sleep(1)
    with PostgresSaver.from_conn_string(
        admin_url.replace("postgresql+psycopg://", "postgresql://")
    ) as saver:
        saver.setup()
    if admin_url != settings().database_url:
        provision_runtime_role(admin_url)
    prepare()
    if settings().demo_seed:
        seed_corpus(DEMO_WORKSPACE, "Engineering Lab")
        with session() as db, db.begin():
            for email, role in [("demo@quarry.local", "owner"), ("viewer@quarry.local", "viewer")]:
                if not db.scalar(select(User).where(User.email == email)):
                    db.add(
                        User(
                            email=email,
                            password_hash=hash_password("quarry-demo-local"),
                            workspace_id=DEMO_WORKSPACE,
                            role=role,
                        )
                    )
    print(json.dumps({"event": "initialization_completed", "demo": settings().demo_seed}))


def provision_runtime_role(admin_url):
    """Only initialization receives the administrator credential; APIs cannot run DDL."""
    import psycopg
    from psycopg import sql

    runtime = make_url(settings().database_url)
    if runtime.username != "quarry_runtime":
        raise ValueError("Compose runtime connections must use quarry_runtime")
    with psycopg.connect(
        admin_url.replace("postgresql+psycopg://", "postgresql://"), autocommit=True
    ) as connection:
        exists = connection.execute(
            "SELECT 1 FROM pg_roles WHERE rolname=%s", (runtime.username,)
        ).fetchone()
        if not exists:
            connection.execute(
                sql.SQL("CREATE ROLE {} LOGIN").format(sql.Identifier(runtime.username))
            )
        connection.execute(
            sql.SQL(
                "ALTER ROLE {} NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD {}"
            ).format(sql.Identifier(runtime.username), sql.Literal(runtime.password))
        )
        connection.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
        connection.execute(
            sql.SQL("REVOKE CREATE, TEMPORARY ON DATABASE {} FROM PUBLIC").format(
                sql.Identifier(runtime.database)
            )
        )
        connection.execute(
            sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                sql.Identifier(runtime.database), sql.Identifier(runtime.username)
            )
        )
        connection.execute(
            sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(sql.Identifier(runtime.username))
        )
        connection.execute(
            sql.SQL(
                "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {}"
            ).format(sql.Identifier(runtime.username))
        )
        connection.execute(
            sql.SQL("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {}").format(
                sql.Identifier(runtime.username)
            )
        )


if __name__ == "__main__":
    main()
