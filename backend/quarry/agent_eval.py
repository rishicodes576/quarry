"""No-key operational evaluation of the real durable graph on every frozen case."""

import hashlib
import json
import statistics
import time

from sqlalchemy import select

from quarry.benchmark import ROOT, percentile, validate_dataset
from quarry.bootstrap import EVAL_WORKSPACE
from quarry.db import Conversation, Event, Run, session
from quarry.live_eval import evaluation_run
from quarry.retrieval import warm_models
from quarry.worker import process


def run():
    manifest = validate_dataset()
    cases = json.loads((ROOT / "cases.json").read_text())
    cold = time.perf_counter()
    warm_models()
    initialization_ms = (time.perf_counter() - cold) * 1000
    rows = []
    started = time.perf_counter()
    for case in cases:
        # A fresh conversation prevents earlier evaluation answers contaminating later inputs.
        with session() as db, db.begin():
            conversation = Conversation(
                workspace_id=EVAL_WORKSPACE, title="Frozen operational evaluation " + case["id"]
            )
            db.add(conversation)
            db.flush()
            conversation_id = conversation.id
        row, job = evaluation_run(case["question"], conversation_id, provider="extractive")
        began = time.perf_counter()
        process(job)
        elapsed = (time.perf_counter() - began) * 1000
        with session() as db:
            row = db.get(Run, row.id)
            first_evidence = db.scalar(
                select(Event.created_at)
                .where(
                    Event.run_id == row.id,
                    Event.kind == "stage_completed",
                    Event.payload["stage"].as_string() == "retrieve",
                )
                .order_by(Event.id)
                .limit(1)
            )
        chosen = sorted(tool["name"] for tool in row.diagnostics.get("plan", {}).get("tools", []))
        rows.append(
            {
                "case_id": case["id"],
                "split": case["split"],
                "kind": case["kind"],
                "run_id": row.id,
                "status": row.status,
                "worker_wall_ms": round(elapsed, 3),
                "first_evidence_ms": round((first_evidence - row.created_at) * 1000, 3)
                if first_evidence
                else None,
                "expected_tools": sorted(case["expected_tools"]),
                "selected_tools": chosen,
                "tool_selection_correct": chosen == sorted(case["expected_tools"]),
                "citation_validation": row.diagnostics.get("citations", {}),
                "tokens": row.token_usage,
                "model_calls": row.model_calls,
                "semantic_task_success": None,
            }
        )
    timed = [r["worker_wall_ms"] for r in rows if r["status"] == "completed"]
    first = [r["first_evidence_ms"] for r in rows if r["first_evidence_ms"] is not None]
    tools = [r for r in rows if r["expected_tools"]]
    duration = time.perf_counter() - started
    artifact = {
        "status": "completed" if len(timed) == len(cases) else "partial",
        "provider": "extractive",
        "manifest": manifest,
        "cases": len(rows),
        "completed": len(timed),
        "worker_p50_ms": percentile(timed, 0.5),
        "worker_p95_ms": percentile(timed, 0.95),
        "first_evidence_p50_ms": percentile(first, 0.5),
        "first_evidence_p95_ms": percentile(first, 0.95),
        "sequential_runs_per_second": len(timed) / duration,
        "model_warmup_ms": initialization_ms,
        "tool_case_count": len(tools),
        "tool_case_accuracy": statistics.mean(r["tool_selection_correct"] for r in tools),
        "all_case_tool_match": statistics.mean(r["tool_selection_correct"] for r in rows),
        "model_calls": sum(r["model_calls"] for r in rows),
        "token_usage": sum(r["tokens"] for r in rows),
        "method": "Real PostgreSQL checkpointed worker graph, Qdrant and ONNX. One sequential inline worker; no HTTP admission or queue wait. First response means first durable retrieval-completed event, not a streamed generation token. Tool-labeled cases cover arithmetic only. Execution completion and valid citation IDs do not establish semantic correctness or appropriate abstention.",
        "semantic_task_success": "Requires separate factual-support/abstention review; not automatically scored",
        "model_manifest_sha256": hashlib.sha256(
            __import__("pathlib").Path("/models/manifest.json").read_bytes()
        ).hexdigest(),
        "rows": rows,
    }
    (ROOT / "results/agent-local.json").write_text(json.dumps(artifact, indent=2))
    print(
        json.dumps({k: v for k, v in artifact.items() if k not in {"rows", "manifest"}}), flush=True
    )
    if artifact["status"] != "completed":
        raise SystemExit("Operational graph evaluation has incomplete cases")


if __name__ == "__main__":
    run()
