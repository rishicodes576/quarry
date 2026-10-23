"""Operator-only container commands. There is no public administration endpoint."""

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
import time
import zipfile
from pathlib import PurePosixPath

from langgraph.checkpoint.postgres import PostgresSaver
from sqlalchemy import delete, select

from quarry import storage
from quarry.config import settings
from quarry.db import (
    AccountMail,
    AccountToken,
    ApiKey,
    AuthAudit,
    Conversation,
    Document,
    Event,
    Job,
    LoginSession,
    RateBucket,
    Run,
    User,
    Workspace,
    session,
    uid,
)
from quarry.queue import enqueue
from quarry.security import hash_password, validate_password


def create_owner(value):
    validate_password(value.get("password", ""))
    from email_validator import validate_email

    value["email"] = validate_email(
        value.get("email", ""), check_deliverability=False
    ).normalized.lower()
    with session() as db, db.begin():
        if db.scalar(select(User.id).where(User.email == value["email"].lower())):
            raise ValueError("Account already exists")
        workspace = Workspace(name=value.get("workspace", "Research workspace")[:120])
        db.add(workspace)
        db.flush()
        db.add(
            User(
                email=value["email"].lower(),
                password_hash=hash_password(value["password"]),
                workspace_id=workspace.id,
                role="owner",
            )
        )
    print("Workspace owner created")


def set_plan(value):
    from quarry.queue import PLAN_WEIGHTS
    from quarry.security import audit

    if value.get("plan") not in PLAN_WEIGHTS:
        raise ValueError("Plan must be free, team, or enterprise")
    with session() as db, db.begin():
        workspace = db.get(Workspace, value["workspace_id"], with_for_update=True)
        if not workspace:
            raise ValueError("Workspace not found")
        workspace.plan = value["plan"]
        audit(db, "operator_plan_changed")
    print(
        json.dumps(
            {
                "workspace_id": workspace.id,
                "plan": workspace.plan,
                "weight": PLAN_WEIGHTS[workspace.plan],
                "payment_collected": False,
            }
        )
    )


def export_objects(output):
    with session() as db:
        documents = db.scalars(select(Document).where(Document.deleted.is_(False))).all()
    manifest = []
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for doc in documents:
            body = storage.get(doc.object_key)
            archive.writestr("objects/" + doc.object_key, body)
            manifest.append(
                {
                    "key": doc.object_key,
                    "type": doc.media_type,
                    "sha256": hashlib.sha256(body).hexdigest(),
                }
            )
        archive.writestr("manifest.json", json.dumps(manifest))


def restore_objects(input_stream):
    with tempfile.SpooledTemporaryFile(max_size=32 * 1024 * 1024) as buffered:
        shutil.copyfileobj(input_stream, buffered)
        buffered.seek(0)
        with zipfile.ZipFile(buffered) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            for entry in manifest:
                path = PurePosixPath(entry["key"])
                if path.is_absolute() or ".." in path.parts or len(path.parts) < 2:
                    raise ValueError("Unsafe object key in backup")
                info = archive.getinfo("objects/" + entry["key"])
                if info.file_size > settings().max_upload_bytes:
                    raise ValueError("Backup object exceeds document limit")
                body = archive.read(info)
                if hashlib.sha256(body).hexdigest() != entry["sha256"]:
                    raise ValueError("Backup content hash mismatch")
                storage.put(entry["key"], body, entry["type"])
    print("Object hashes verified and restored")


def reindex():
    count = 0
    with session() as db, db.begin():
        for doc in db.scalars(
            select(Document).where(Document.deleted.is_(False), Document.status == "ready")
        ).all():
            if db.scalar(
                select(Job.id).where(
                    Job.target_id == doc.id,
                    Job.kind == "ingest",
                    Job.status.in_(["pending", "running"]),
                )
            ):
                continue
            doc.status = "pending"
            enqueue(db, doc.workspace_id, "ingest", doc.id)
            count += 1
    print(json.dumps({"reindex_jobs": count}))


def retention(apply=False):
    cutoff = time.time() - 30 * 86400
    with session() as db:
        rows = db.scalars(
            select(Run).where(
                Run.created_at < cutoff,
                Run.status.in_(["completed", "failed", "cancelled", "quota_exhausted"]),
            )
        ).all()
        ids = [r.id for r in rows]
    if not apply:
        print(json.dumps({"dry_run": True, "run_snapshots_to_redact": len(ids)}))
        return
    with PostgresSaver.from_conn_string(
        settings().database_url.replace("postgresql+psycopg://", "postgresql://")
    ) as saver:
        for run_id in ids:
            saver.delete_thread(run_id)
    with session() as db, db.begin():
        for run_id in ids:
            row = db.get(Run, run_id, with_for_update=True)
            row.question = "[expired research]"
            row.answer = ""
            row.evidence = []
            row.diagnostics = {"retention_redacted": True}
        db.execute(delete(Event).where(Event.created_at < time.time() - 90 * 86400))
        db.execute(delete(LoginSession).where(LoginSession.expires_at < time.time()))
        db.execute(delete(RateBucket).where(RateBucket.expires_at < time.time()))
        db.execute(delete(AccountToken).where(AccountToken.expires_at < time.time()))
        db.execute(delete(AccountMail).where(AccountMail.expires_at < time.time()))
        db.execute(delete(ApiKey).where(ApiKey.expires_at < time.time()))
        db.execute(delete(AuthAudit).where(AuthAudit.created_at < time.time() - 90 * 86400))
        for user in db.scalars(
            select(User).where(User.mfa_pending_until < time.time(), User.mfa_pending != "")
        ).all():
            user.mfa_pending, user.mfa_pending_until = "", 0
        db.execute(
            delete(Job).where(
                Job.created_at < time.time() - 90 * 86400, Job.status.in_(["done", "dead"])
            )
        )
        for conversation in db.scalars(
            select(Conversation).where(Conversation.created_at < cutoff)
        ).all():
            recent = db.scalar(
                select(Run.id)
                .where(Run.conversation_id == conversation.id, Run.created_at >= cutoff)
                .limit(1)
            )
            if not recent:
                conversation.title = "[expired conversation]"
    print(json.dumps({"run_snapshots_redacted": len(ids)}))


def verify_restore():
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        with session() as db:
            docs = db.scalars(
                select(Document).where(Document.deleted.is_(False), Document.status != "superseded")
            ).all()
        if docs and all(d.status == "ready" for d in docs):
            break
        if any(d.status == "failed" for d in docs):
            raise RuntimeError("Restored source indexing failed")
        time.sleep(1)
    else:
        raise TimeoutError("Restored sources did not become ready")
    for doc in docs:
        if hashlib.sha256(storage.get(doc.object_key)).hexdigest() != doc.content_hash:
            raise ValueError("Restored source hash mismatch")
    with session() as db, db.begin():
        conversation = Conversation(
            workspace_id=docs[0].workspace_id, title="Restoration verification"
        )
        db.add(conversation)
        db.flush()
        run = Run(
            workspace_id=conversation.workspace_id,
            conversation_id=conversation.id,
            question="Explain " + docs[0].title,
            provider="extractive",
            request_key=uid(),
            request_hash="restore",
        )
        db.add(run)
        db.flush()
        enqueue(db, run.workspace_id, "research", run.id)
        run_id = run.id
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        with session() as db:
            run = db.get(Run, run_id)
            if run.status == "completed":
                if not run.evidence:
                    raise ValueError("Restored research had no evidence")
                print(
                    json.dumps(
                        {
                            "status": "passed",
                            "source_hashes_verified": len(docs),
                            "research_run": run_id,
                            "cited_passages": len(run.evidence),
                        }
                    )
                )
                return
            if run.status == "failed":
                raise RuntimeError("Restored research failed")
        time.sleep(1)
    raise TimeoutError("Restored research did not finish")


def verify_objects():
    with session() as db:
        docs = db.scalars(
            select(Document).where(Document.deleted.is_(False), Document.object_key != "")
        ).all()
    for doc in docs:
        if hashlib.sha256(storage.get(doc.object_key)).hexdigest() != doc.content_hash:
            raise ValueError("Source object hash mismatch")
    print(json.dumps({"source_hashes_verified": len(docs), "status": "passed"}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        choices=[
            "create-owner",
            "export-objects",
            "restore-objects",
            "reindex",
            "retention",
            "verify-restore",
            "set-plan",
            "verify-objects",
        ],
    )
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--acknowledge-isolated", action="store_true")
    args = parser.parse_args()
    if args.action == "create-owner":
        create_owner(json.load(sys.stdin))
    elif args.action == "set-plan":
        set_plan(json.load(sys.stdin))
    elif args.action == "export-objects":
        export_objects(sys.stdout.buffer)
    elif args.action == "restore-objects":
        if not args.acknowledge_isolated:
            raise SystemExit(
                "Restore requires --acknowledge-isolated; use a separate restoration stack"
            )
        restore_objects(sys.stdin.buffer)
    elif args.action == "reindex":
        reindex()
    elif args.action == "verify-restore":
        verify_restore()
    elif args.action == "verify-objects":
        verify_objects()
    else:
        retention(args.apply)


if __name__ == "__main__":
    main()
