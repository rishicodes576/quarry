"""Independent arithmetic checks over saved measurements; never calls a provider."""

import argparse
import hashlib
import json
import math
import statistics
from datetime import UTC, datetime
from pathlib import Path

METRICS = {"context_precision", "context_recall", "faithfulness"}
MODES = {"dense", "bm25", "hybrid", "hybrid_rerank"}


def close(actual, expected, tolerance=1e-6):
    if not math.isfinite(actual) or not math.isclose(actual, expected, abs_tol=tolerance):
        raise ValueError(f"Measurement mismatch: saved={actual}, recomputed={expected}")


def quantile(values, fraction):
    ordered = sorted(values)
    position = fraction * (len(ordered) - 1)
    lo, hi = math.floor(position), math.ceil(position)
    return ordered[lo] * (hi - position) + ordered[hi] * (position - lo) if lo != hi else ordered[lo]


def ranks(ranked, relevant):
    # Independent implementation: source ranks, binary relevance, base-2 discount.
    unique = list(dict.fromkeys(ranked))[:5]
    relevant = set(relevant)
    if not relevant:
        return None
    found = [i for i, source in enumerate(unique, 1) if source in relevant]
    dcg = math.fsum(1 / math.log2(i + 1) for i in found)
    ideal = math.fsum(1 / math.log2(i + 1) for i in range(1, min(5, len(relevant)) + 1))
    precision, recall = len(found) / max(1, len(unique)), len(found) / len(relevant)
    return {
        "recall_at_5": recall, "mrr": 1 / min(found) if found else 0,
        "ndcg_at_5": dcg / ideal, "precision_at_5": precision,
        "ragas_id_precision": precision, "ragas_id_recall": recall,
    }


def judge_score(name, outputs):
    if name == "context_precision":
        verdicts = [o["verdict"] for o in outputs]
        if any(v not in (0, 1) for v in verdicts):
            raise ValueError("Non-binary precision verdict")
        numerator = math.fsum(sum(verdicts[:i]) / i for i, v in enumerate(verdicts, 1) if v)
        return numerator / (sum(verdicts) + 1e-10)
    if name == "context_recall":
        verdicts = [v["attributed"] for v in outputs[-1]["classifications"]]
    else:
        verdicts = [v["verdict"] for v in outputs[-1]["statements"]]
    if not verdicts or any(v not in (0, 1) for v in verdicts):
        raise ValueError("Missing/non-binary statement verdicts")
    return sum(verdicts) / len(verdicts)


def export_judges(root, live=None, filename="judge-verdicts.json"):
    # Explicit operator action; only the fixed synthetic evaluation workspace is read.
    from quarry.bootstrap import EVAL_WORKSPACE
    from quarry.db import Run, session

    live = live if live is not None else json.loads((root / "results/live-ragas.json").read_text())
    ids = {
        run_id for row in live["rows"]
        for config in row.get("metric_configuration", {}).values()
        for run_id in config.get("judge_run_ids", [])
    }
    exported = {}
    with session() as db:
        for run_id in sorted(ids):
            row = db.get(Run, run_id)
            if (row is None or row.workspace_id != EVAL_WORKSPACE
                    or row.question != "Ragas judge request" or row.status != "completed"
                    or row.provider != "groq" or row.paid_consent
                    or row.diagnostics.get("judge_cache_version") != 1):
                raise ValueError("Judge evidence does not belong to a completed free campaign RPC")
            output = json.loads(row.answer)
            if not isinstance(output, dict):
                raise ValueError("Judge evidence must be a JSON object")
            exported[run_id] = {
                "output": output, "request_sha256": row.request_hash,
                "answer_sha256": hashlib.sha256(row.answer.encode()).hexdigest(),
                "raw_output": row.answer,
                "origin_conversation_id": row.conversation_id,
                "cache_version": row.diagnostics["judge_cache_version"],
            }
    (root / "results" / filename).write_text(json.dumps(exported, indent=2))


def audit(root, require_complete=False):
    hashes = {}

    def load(name):
        data = (root / name).read_bytes()
        hashes[name] = hashlib.sha256(data).hexdigest()
        return json.loads(data)

    manifest, cases = load("manifest.json"), load("cases.json")
    for name, expected in manifest["sha256"].items():
        load(name)
        if hashes[name] != expected:
            raise ValueError("Frozen dataset hash mismatch: " + name)
    labels = {c["id"]: c for c in cases}
    summaries = []
    for filename in ("retrieval-all.json", "retrieval-dev.json", "latest.json"):
        artifact = load("results/" + filename)
        allowed_splits = {"all", "test"} if filename == "latest.json" else {filename.removeprefix("retrieval-").removesuffix(".json")}
        summary_modes = [s["mode"] for s in artifact["results"]]
        if (artifact["split"] not in allowed_splits or artifact["status"] != "completed"
                or len(summary_modes) != 4 or set(summary_modes) != MODES):
            raise ValueError("Incorrect retrieval split/status/summary matrix")
        if artifact["manifest"]["sha256"] != manifest["sha256"]:
            raise ValueError("Retrieval dataset mismatch")
        expected = {c["id"] for c in cases if artifact["split"] == "all" or c["split"] == artifact["split"]}
        seen = set()
        for row in artifact["rows"]:
            key = row["mode"], row["id"]
            if key in seen or key[0] not in MODES or key[1] not in expected or row["status"] != "completed":
                raise ValueError("Duplicate, missing or failed retrieval measurement")
            seen.add(key)
            if not math.isfinite(row["latency_ms"]) or row["latency_ms"] < 0:
                raise ValueError("Invalid retrieval latency")
            case = labels[row["id"]]
            if row["relevant_sources"] != case["relevant_sources"] or row["split"] != case["split"]:
                raise ValueError("Changed relevance labels/split")
            computed = ranks(row["sources"], case["relevant_sources"])
            if computed is None:
                if row["metrics"] is not None:
                    raise ValueError("Unanswerable/tool case entered relevance aggregate")
            else:
                for name, value in computed.items():
                    close(row["metrics"][name], value)
        if seen != {(mode, case_id) for mode in MODES for case_id in expected}:
            raise ValueError("Incomplete retrieval matrix")
        for summary in artifact["results"]:
            rows = [r for r in artifact["rows"] if r["mode"] == summary["mode"]]
            scored = [r for r in rows if r["metrics"] is not None]
            if (summary["count"], summary["timed_count"], summary["failure_count"]) != (len(scored), len(rows), 0):
                raise ValueError("Incorrect sample counts")
            for name in scored[0]["metrics"]:
                close(summary[name], statistics.mean(r["metrics"][name] for r in scored))
            for name, fraction in (("p50_ms", .5), ("p95_ms", .95)):
                # Row and summary latencies were independently rounded to .001 ms.
                close(summary[name], quantile([r["latency_ms"] for r in rows], fraction), .0011)
        summaries.append({"artifact": filename, "rows_checked": len(seen)})
    agent = load("results/agent-local.json")
    if {r["case_id"] for r in agent["rows"]} != set(labels) or len(agent["rows"]) != len(cases):
        raise ValueError("Incomplete agent matrix")
    completed = sum(r["status"] == "completed" for r in agent["rows"])
    if (agent["cases"] != len(cases) or agent["completed"] != completed
            or completed != len(cases) or agent["status"] != "completed"
            or agent["manifest"]["sha256"] != manifest["sha256"]):
        raise ValueError("Incorrect agent completion aggregate/dataset")
    for row in agent["rows"]:
        expected_tools = sorted(labels[row["case_id"]]["expected_tools"])
        if row["expected_tools"] != expected_tools or row["tool_selection_correct"] != (sorted(row["selected_tools"]) == expected_tools):
            raise ValueError("Incorrect tool-selection score")
    for prefix, field in (("worker", "worker_wall_ms"), ("first_evidence", "first_evidence_ms")):
        values = [r[field] for r in agent["rows"] if r[field] is not None]
        for p, fraction in ((50, .5), (95, .95)):
            close(agent[f"{prefix}_p{p}_ms"], quantile(values, fraction))
    tools = [r for r in agent["rows"] if r["expected_tools"]]
    if agent["tool_case_count"] != len(tools):
        raise ValueError("Incorrect tool case count")
    close(agent["tool_case_accuracy"], statistics.mean(r["tool_selection_correct"] for r in tools))
    close(agent["all_case_tool_match"], statistics.mean(r["tool_selection_correct"] for r in agent["rows"]))
    for aggregate, field in (("model_calls", "model_calls"), ("token_usage", "tokens")):
        close(agent[aggregate], sum(r[field] for r in agent["rows"]))
    for workers in (1, 2, 4):
        load_result = load(f"results/load-{workers}.json")
        close(load_result["completed_per_second"], load_result["completed"] / load_result["duration_seconds"], .001)
    live = load("results/live-ragas.json")
    expected_ids = [c["id"] for c in cases if c["split"] == "test" and c["relevant_sources"]][:37]
    ids = [r["case_id"] for r in live["rows"]]
    if (len(ids) != len(set(ids)) or not set(ids) <= set(expected_ids)
            or live["requested_case_count"] != 37 or live["dataset_sha256"] != manifest["sha256"]
            or live["provider"] != "groq" or live["model"] != "openai/gpt-oss-120b"
            or live["automatic_paid_switch"]):
        raise ValueError("Live campaign identity/dataset mismatch")
    judged, checked, legacy = [], 0, []
    evidence_path = root / "results/judge-verdicts.json"
    evidence = load("results/judge-verdicts.json") if evidence_path.exists() else {}
    for row in live["rows"]:
        if set(row["metrics"]) - METRICS:
            raise ValueError("Unknown live metric")
        for name, value in row["metrics"].items():
            if not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError("Nonfinite/out-of-range live score")
            configuration = row.get("metric_configuration", {}).get(name, {})
            if (configuration.get("provider", "groq") != "groq"
                    or configuration.get("model", live["model"]) != live["model"]):
                raise ValueError("Changed metric provider/model")
            run_ids = configuration.get("judge_run_ids", [])
            if run_ids and evidence:
                outputs = [evidence[run_id]["output"] for run_id in run_ids]
                if name == "context_precision" and len(outputs) != len(row["contexts"]):
                    raise ValueError("Precision verdict count differs from context count")
                close(value, judge_score(name, outputs), 1e-12)
                checked += 1
            else:
                legacy.append({"case_id": row["case_id"], "metric": name})
        if set(row["metrics"]) == METRICS:
            judged.append(row)
    complete = len(judged) == 37 and set(ids) == set(expected_ids) and live["status"] == "completed"
    if require_complete and (not complete or not evidence):
        raise ValueError("Release requires 37/37 and exported judge evidence")
    result = {
        "status": "passed", "created_at": datetime.now(UTC).isoformat(),
        "scope": "Arithmetic/integrity audit; not independent factual-support or label validation",
        "retrieval": summaries, "agent_cases": len(agent["rows"]), "tool_cases": len(tools),
        "load_throughput_configurations": [1, 2, 4], "live_complete": complete,
        "live_fully_judged": len(judged), "live_requested": 37,
        "live_means": {name: statistics.mean(r["metrics"][name] for r in judged) for name in sorted(METRICS)} if judged else {},
        "live_verdict_metrics_recomputed": checked,
        "metrics_without_exported_rpc_provenance": legacy,
        "input_sha256": hashes, "provider_calls": 0,
        "latency_method": "Linear interpolation at (n-1)*p, tolerance .0011 ms for rounded retrieval rows",
        "relevance_method": "Unique source ranks @5; binary DCG/log2(rank+1); macro means over relevance-labeled cases only",
    }
    (root / "results/mathematical-audit.json").write_text(json.dumps(result, indent=2, allow_nan=False))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evaluation-root", type=Path, default=Path("/app/evaluation"))
    parser.add_argument("--export-judges", action="store_true")
    parser.add_argument("--require-live-complete", action="store_true")
    args = parser.parse_args()
    if args.export_judges:
        export_judges(args.evaluation_root)
    result = audit(args.evaluation_root, args.require_live_complete)
    print(json.dumps({k: result[k] for k in ("status", "live_complete", "live_fully_judged", "live_means", "live_verdict_metrics_recomputed")}))


if __name__ == "__main__":
    main()
