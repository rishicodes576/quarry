import time

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from langgraph.checkpoint.postgres import PostgresSaver
from sqlalchemy import delete

from quarry import retrieval, storage
from quarry.api import app
from quarry.config import settings
from quarry.db import Base, Conversation, Document, Run, User, Workspace, session
from quarry.queue import enqueue
from quarry.security import hash_password


@pytest.fixture(scope="session", autouse=True)
def services():
    config = settings()
    assert config.database_url.rsplit("/", 1)[-1] == "quarry_test", (
        "Tests require the isolated quarry_test database"
    )
    command.upgrade(Config("alembic.ini"), "head")
    with PostgresSaver.from_conn_string(
        config.database_url.replace("postgresql+psycopg://", "postgresql://")
    ) as saver:
        saver.setup()
    retrieval.init_index()
    storage.init_storage()
    retrieval.warm_models()


@pytest.fixture(autouse=True)
def clean_database(services):
    with session() as db, db.begin():
        for table in reversed(Base.metadata.sorted_tables):
            db.execute(delete(table))
    yield
    with session() as db:
        docs = db.query(Document).all()
        for doc in docs:
            retrieval.delete_document(doc.id)
            if doc.object_key:
                storage.remove(doc.object_key)


@pytest.fixture
def actors():
    with session() as db, db.begin():
        first = Workspace(name="First team")
        second = Workspace(name="Second team")
        db.add_all([first, second])
        db.flush()
        result = {}
        for email, workspace, role in [
            ("owner@example.com", first, "owner"),
            ("viewer@example.com", first, "viewer"),
            ("other@example.com", second, "owner"),
        ]:
            user = User(
                email=email,
                workspace_id=workspace.id,
                role=role,
                password_hash=hash_password("a-long-test-password"),
            )
            db.add(user)
            db.flush()
            result[role if email != "other@example.com" else "other"] = user
        return result


@pytest.fixture
def client(actors):
    with TestClient(app) as value:
        result = value.post(
            "/v1/auth/login",
            json={"email": "owner@example.com", "password": "a-long-test-password"},
        )
        assert result.status_code == 200
        yield value


@pytest.fixture
def make_run(actors):
    def create(
        provider="extractive",
        question="How do worker leases prevent stale result commits?",
        **kwargs,
    ):
        with session() as db, db.begin():
            conversation = Conversation(
                workspace_id=actors["owner"].workspace_id, title="Test research"
            )
            db.add(conversation)
            db.flush()
            run = Run(
                workspace_id=conversation.workspace_id,
                conversation_id=conversation.id,
                question=question,
                request_key=str(time.time_ns()),
                request_hash="test",
                provider=provider,
                **kwargs,
            )
            db.add(run)
            db.flush()
            enqueue(db, run.workspace_id, "research", run.id)
            return run

    return create


def finish_document(
    client,
    text="A worker uses a 90 second lease. Every result is fenced by the current token.",
    filename="worker.md",
):
    from quarry.queue import claim
    from quarry.worker import process

    response = client.post(
        "/v1/documents", files={"file": (filename, text.encode(), "text/markdown")}
    )
    assert response.status_code == 202, response.text
    doc = response.json()
    job = claim()
    assert job and job.kind == "ingest"
    process(job)
    with session() as db:
        row = db.get(Document, doc["id"])
        assert row.status == "ready", row.error
        return row
