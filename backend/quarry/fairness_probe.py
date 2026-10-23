"""Live HTTP noisy-tenant probe within normal request limits; no model calls."""

import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
from sqlalchemy import select

from quarry.benchmark import percentile
from quarry.db import Run, Workspace, session, uid
from quarry.loadtest import fixture
from quarry.security import COOKIE


def run():
    heavy, small = fixture(25)[:2]
    with session() as db, db.begin():
        db.get(Workspace, heavy["workspace"]).plan = "enterprise"

    def submit(value):
        tenant, item = value
        with httpx.Client(
            base_url="http://api:8000", cookies={COOKIE: item["token"]}, timeout=20, trust_env=False
        ) as client:
            response = client.post(
                "/v1/runs",
                headers={"Idempotency-Key": uid()},
                json={
                    "conversation_id": item["conversation"],
                    "question": "How do worker leases and fencing protect results?",
                    "provider": "extractive",
                },
            )
        response.raise_for_status()
        return tenant, response.json()["id"]

    with ThreadPoolExecutor(max_workers=10) as pool:
        heavy_ids = list(pool.map(submit, [("enterprise", heavy)] * 20))
        small_ids = list(pool.map(submit, [("free", small)] * 5))
    submissions = heavy_ids + small_ids
    ids = [identifier for _, identifier in submissions]
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        with session() as db:
            rows = db.scalars(select(Run).where(Run.id.in_(ids))).all()
        if all(row.status in {"completed", "failed", "cancelled"} for row in rows):
            break
        time.sleep(0.2)
    groups = {
        name: [
            row
            for row in rows
            if row.id in {identifier for tenant, identifier in submissions if tenant == name}
        ]
        for name in ["enterprise", "free"]
    }
    successful = all(row.status == "completed" for row in rows) and len(rows) == 25
    progress = successful and min(row.started_at for row in groups["free"]) < max(
        row.started_at for row in groups["enterprise"]
    )
    report = {
        "status": "passed" if progress else "failed",
        "api_replicas": 2,
        "workers": 1,
        "requested": 25,
        "completed": sum(row.status == "completed" for row in rows),
        "free_progress_before_enterprise_backlog_drained": progress,
        "plan_weights": {"enterprise": 4, "free": 1},
        "tenant_queue_p95_ms": {
            name: percentile(
                [(row.started_at - row.created_at) * 1000 for row in values if row.started_at], 0.95
            )
            for name, values in groups.items()
        },
        "dispatch_order": [
            {
                "run_id": row.id,
                "tenant": "enterprise" if row.workspace_id == heavy["workspace"] else "free",
                "created_at": row.created_at,
                "started_at": row.started_at,
            }
            for row in sorted(rows, key=lambda row: row.started_at or float("inf"))
        ],
        "method": "20 enterprise requests followed by five free requests while one actual worker drains the queue. Both accounts remain within the normal 20/min admission rate. Verifies finite progress, not a latency SLA or weighted CPU-time guarantee.",
        "generation_api_calls": 0,
    }
    Path("/app/evaluation/results/fairness-live.json").write_text(json.dumps(report, indent=2))
    print(
        json.dumps({key: value for key, value in report.items() if key != "dispatch_order"}),
        flush=True,
    )
    if not progress:
        raise SystemExit("Free tenant did not progress before the enterprise backlog drained")


if __name__ == "__main__":
    run()
