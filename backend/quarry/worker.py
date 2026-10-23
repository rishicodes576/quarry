import json
import signal
import threading
import time

from sqlalchemy import cast, delete, select
from sqlalchemy.dialects.postgresql import JSONB

from quarry import agent, providers, retrieval, storage
from quarry.config import settings
from quarry.db import Chunk, Document, Run, Workspace
from quarry.ingest import chunk_text, isolated_extract
from quarry.queue import Cancelled, Heartbeat, LeaseLost, claim, enqueue, event, fenced, retry_delay

stop = threading.Event()


def ingest(job):
    with fenced(job) as (db, _):
        doc = db.get(Document, job.target_id)
        if doc.deleted:
            return
        doc.status = "indexing"
        text, workspace_id, doc_id = doc.content, doc.workspace_id, doc.id
        object_key, media_type, title = doc.object_key, doc.media_type, doc.title
    if not text:
        text = isolated_extract(storage.get(object_key), media_type, title)
    chunks = chunk_text(doc_id, text)
    retrieval.index_chunks(workspace_id, doc_id, chunks)
    with fenced(job) as (db, _):
        db.scalar(select(Workspace).where(Workspace.id == workspace_id).with_for_update())
        doc = db.get(Document, doc_id, with_for_update=True)
        if doc.deleted:
            return
        db.execute(delete(Chunk).where(Chunk.document_id == doc_id))
        doc.content = text
        for chunk in chunks:
            db.add(Chunk(workspace_id=workspace_id, document_id=doc_id, **chunk))
        if doc.source_key:
            newer = db.scalar(
                select(Document.id)
                .where(
                    Document.workspace_id == workspace_id,
                    Document.source_key == doc.source_key,
                    Document.version > doc.version,
                    Document.status == "ready",
                    Document.deleted.is_(False),
                )
                .limit(1)
            )
            if newer:
                doc.status = "superseded"
                enqueue(db, workspace_id, "cleanup", doc.id)
                return
            for old in db.scalars(
                select(Document)
                .where(
                    Document.workspace_id == workspace_id,
                    Document.source_key == doc.source_key,
                    Document.id != doc_id,
                    Document.status == "ready",
                    Document.deleted.is_(False),
                )
                .with_for_update()
            ).all():
                old.status = "superseded"
                enqueue(db, workspace_id, "cleanup", old.id)
        doc.status, doc.chunk_count, doc.error = "ready", len(chunks), ""


def cleanup(job):
    with fenced(job) as (db, _):
        doc = db.get(Document, job.target_id)
        key = doc.object_key if doc and doc.deleted else ""
    retrieval.delete_document(job.target_id)
    if key:
        storage.remove(key)
    # Source deletion also covers historical snapshots and graph state.
    with fenced(job) as (db, _):
        affected = db.scalars(
            select(Run.id).where(
                Run.workspace_id == job.workspace_id,
                cast(Run.diagnostics, JSONB).contains({"deleted_documents": [job.target_id]}),
            )
        ).all()
    if affected:
        from langgraph.checkpoint.postgres import PostgresSaver

        with PostgresSaver.from_conn_string(
            settings().database_url.replace("postgresql+psycopg://", "postgresql://")
        ) as saver:
            for run_id in affected:
                saver.delete_thread(run_id)
    with fenced(job) as (db, _):
        db.execute(delete(Chunk).where(Chunk.document_id == job.target_id))
        doc = db.get(Document, job.target_id)
        if doc and doc.deleted:
            doc.content = ""
            doc.object_key = ""
            doc.byte_size = 0


def process(job):
    try:
        with Heartbeat(job):
            if job.kind == "ingest":
                ingest(job)
            elif job.kind == "cleanup":
                cleanup(job)
            elif job.kind == "mail":
                from quarry.accounts import deliver

                deliver(job)
            elif job.kind in {"research", "evaluation_judge"}:
                with fenced(job) as (db, current):
                    run = db.get(Run, job.target_id)
                    from quarry.bootstrap import EVAL_WORKSPACE

                    if job.kind == "evaluation_judge" or (
                        run.workspace_id == EVAL_WORKSPACE
                        and run.question == "Ragas judge request"
                    ):
                        # The campaign owns judge prompts, not the research graph.
                        # Recover interrupted calls conservatively and let it retry.
                        providers.settle_run(db, run, None)
                        run.status, run.finished_at = "failed", time.time()
                        run.error = "Judge interrupted; resume the evaluation campaign"
                        current.status, current.error = "dead", "InterruptedJudge"
                        event(db, run, "failed", {"reason": "interrupted_judge"})
                        return
                    if run.cancel_requested:
                        raise Cancelled("Research was cancelled")
                    # Ambiguous in-flight provider calls are charged conservatively after crashes.
                    providers.settle_run(db, run, None)
                    run.status = "running"
                    run.started_at = run.started_at or time.time()
                    event(db, run, "running", {"attempt": job.attempt})
                result = agent.execute_run(job)
                with fenced(job) as (db, _):
                    run = db.get(Run, job.target_id)
                    if run.cancel_requested:
                        raise Cancelled("Research was cancelled")
                    eligible = agent.active_evidence(run.workspace_id, result["evidence"])
                    run.answer = (
                        result["answer"]
                        if len(eligible) == len(result["evidence"])
                        else agent.excerpt_answer(eligible)
                    )
                    run.evidence = eligible
                    run.diagnostics = {
                        **run.diagnostics,
                        **result["diagnostics"],
                        "total_ms": round((time.time() - run.started_at) * 1000, 2),
                    }
                    run.status, run.finished_at, run.error = "completed", time.time(), ""
                    event(db, run, "completed", {"total_ms": run.diagnostics["total_ms"]})
            else:
                raise ValueError("Unknown job kind")
            with fenced(job) as (_, current):
                current.status = "done"
    except LeaseLost:
        return
    except providers.ProviderQuota as error:
        with fenced(job) as (db, current):
            run = db.get(Run, job.target_id)
            run.status, run.error = "quota_exhausted", str(error)
            run.diagnostics = {
                **run.diagnostics,
                "retry_after": error.retry_after,
                "quota_scope": error.scope,
            }
            event(
                db,
                run,
                "quota_exhausted",
                {"retry_after": error.retry_after, "scope": error.scope, "automatic_switch": False},
            )
            current.status = "done"
    except Cancelled:
        with fenced(job) as (db, current):
            run = db.get(Run, job.target_id)
            providers.settle_run(db, run, None)
            run.status, run.finished_at = "cancelled", time.time()
            event(db, run, "cancelled", {})
            current.status = "done"
    except Exception as error:
        # Exception class is useful operationally; exception strings can contain external secrets.
        with fenced(job) as (db, current):
            terminal = job.attempt >= settings().max_attempts or isinstance(
                error,
                (ValueError, providers.ProviderFailure, TimeoutError),
            )
            current.error = type(error).__name__
            current.status = "dead" if terminal else "pending"
            current.available_at = time.time() + retry_delay(job.attempt)
            if job.kind in {"research", "evaluation_judge"}:
                run = db.get(Run, job.target_id)
                providers.settle_run(db, run, None)
                run.status = "failed" if terminal else "queued"
                run.error = "Research failed: " + type(error).__name__
                if terminal:
                    run.finished_at = time.time()
                event(
                    db, run, "failed" if terminal else "retrying", {"reason": type(error).__name__}
                )
            elif job.kind == "ingest":
                doc = db.get(Document, job.target_id)
                doc.status = "failed" if terminal else "pending"
                doc.error = (
                    str(error)[:220]
                    if isinstance(error, ValueError)
                    else "Indexing failed: " + type(error).__name__
                )
        print(
            json.dumps(
                {
                    "event": "job_failed",
                    "kind": job.kind,
                    "reason": type(error).__name__,
                    "attempt": job.attempt,
                }
            ),
            flush=True,
        )


def main():
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    retrieval.warm_models()
    print(json.dumps({"event": "worker_ready"}), flush=True)
    while not stop.is_set():
        try:
            job = claim()
            if job:
                process(job)
            else:
                stop.wait(0.3)
        except Exception as error:
            print(json.dumps({"event": "worker_error", "reason": type(error).__name__}), flush=True)
            stop.wait(2)


if __name__ == "__main__":
    main()
