"""Free, bounded multi-workspace workload. Designed for the local Compose verification."""

import argparse
import json
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
from sqlalchemy import select

from quarry import storage
from quarry.benchmark import percentile
from quarry.db import Conversation, Document, LoginSession, Run, User, Workspace, session, uid
from quarry.ingest import content_hash
from quarry.queue import enqueue
from quarry.security import COOKIE, digest, hash_password


def fixture(count):
    fixtures = []
    for _number in range(5):
        with session() as db, db.begin():
            workspace = Workspace(name=f"Load verification {uid()[:8]}")
            db.add(workspace)
            db.flush()
            user = User(
                email=f"{uid()}@load.example",
                workspace_id=workspace.id,
                role="owner",
                password_hash=hash_password(uid()),
            )
            db.add(user)
            db.flush()
            token = uid() + uid()
            db.add(
                LoginSession(digest=digest(token), user_id=user.id, expires_at=time.time() + 3600)
            )
            conversation = Conversation(workspace_id=workspace.id, title="Measured local workload")
            db.add(conversation)
            text = (
                "Original synthetic load source. Workers use a 90 second lease and renew every "
                "30 seconds. A fencing token prevents stale workers publishing results. "
                "Every result transaction checks the current job token and lease expiry. "
                "The daily workspace token budget is shared in PostgreSQL. No paid provider is used."
            )
            key = f"{workspace.id}/load.md"
            storage.put(key, text.encode(), "text/markdown")
            doc = Document(
                workspace_id=workspace.id,
                title="Worker lease verification",
                content=text,
                content_hash=content_hash(text),
                source_key="load-fixture",
                object_key=key,
                byte_size=len(text.encode()),
            )
            db.add(doc)
            db.flush()
            enqueue(db, workspace.id, "ingest", doc.id)
            fixtures.append(
                {
                    "workspace": workspace.id,
                    "document": doc.id,
                    "conversation": conversation.id,
                    "token": token,
                }
            )
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        with session() as db:
            docs = db.scalars(
                select(Document).where(Document.id.in_([f["document"] for f in fixtures]))
            ).all()
        if all(d.status == "ready" for d in docs):
            return fixtures
        if any(d.status == "failed" for d in docs):
            raise RuntimeError("Load fixture ingestion failed")
        time.sleep(0.5)
    raise TimeoutError("Load fixtures did not index")


def run(worker_count, requests=100):
    if requests > 100 or requests < 5:
        raise ValueError("Use 5–100 requests so the normal admission limits remain in force")
    fixtures = fixture(requests)
    started = time.monotonic()

    def submit(number):
        item = fixtures[number % len(fixtures)]
        began = time.perf_counter()
        # New connections allow Docker DNS to distribute requests across API replicas.
        with httpx.Client(
            base_url="http://api:8000", cookies={COOKIE: item["token"]}, timeout=30, trust_env=False
        ) as client:
            try:
                result = client.post(
                    "/v1/runs",
                    headers={"Idempotency-Key": uid()},
                    json={
                        "conversation_id": item["conversation"],
                        "question": "How do lease renewal and fencing protect worker results?",
                        "provider": "extractive",
                        "retrieval_mode": "hybrid_rerank",
                    },
                )
            except httpx.HTTPError as error:
                return {
                    "status": 0,
                    "run_id": None,
                    "submission_ms": (time.perf_counter() - began) * 1000,
                    "error": type(error).__name__,
                }
        return {
            "status": result.status_code,
            "run_id": result.json().get("id"),
            "submission_ms": (time.perf_counter() - began) * 1000,
        }

    with ThreadPoolExecutor(max_workers=10) as pool:
        submissions = list(pool.map(submit, range(requests)))
    ids = [s["run_id"] for s in submissions if s["run_id"]]
    deadline = time.monotonic() + 600
    while time.monotonic() < deadline:
        with session() as db:
            rows = db.scalars(select(Run).where(Run.id.in_(ids))).all()
        if all(r.status in {"completed", "failed", "cancelled", "quota_exhausted"} for r in rows):
            break
        time.sleep(0.5)
    duration = time.monotonic() - started
    completed = [r for r in rows if r.status == "completed"]
    latencies = [(r.finished_at - r.created_at) * 1000 for r in completed]
    queue = [max(0, (r.started_at - r.created_at) * 1000) for r in completed]
    report = {
        "status": "passed" if len(completed) == requests else "failed",
        "workers": worker_count,
        "api_replicas": 2,
        "requested": requests,
        "accepted": len(ids),
        "completed": len(completed),
        "unfinished_or_failed": len(ids) - len(completed),
        "rejected": requests - len(ids),
        "duration_seconds": round(duration, 3),
        "completed_per_second": round(len(completed) / duration, 3),
        "end_to_end_p50_ms": round(percentile(latencies, 0.5), 3),
        "end_to_end_p95_ms": round(percentile(latencies, 0.95), 3),
        "queue_p50_ms": round(percentile(queue, 0.5), 3),
        "submission_p50_ms": round(statistics.median(s["submission_ms"] for s in submissions), 3),
        "generation_api_calls": 0,
        "method": "Five isolated sample workspaces; 100 requests; 10 submission threads; local ONNX; includes queueing.",
        "run_ids": ids,
        "submission_statuses": [s["status"] for s in submissions],
    }
    output = Path("/app/evaluation/results")
    (output / f"load-{worker_count}.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report))
    if len(completed) != requests:
        raise SystemExit(
            "Load verification did not complete every request; inspect the saved report"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, required=True)
    args = parser.parse_args()
    run(args.workers)
