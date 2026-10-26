"""Strict isolated-campaign provenance/arithmetic audit. No model calls."""

import argparse
import csv
import hashlib
import json
import statistics
from datetime import UTC, datetime
from pathlib import Path

from quarry.metric_audit import METRICS, close, export_judges, judge_score, quantile

MODES = ("dense", "bm25", "hybrid", "hybrid_rerank")


def sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def export_research(root, report, filename):
    from quarry.bootstrap import EVAL_WORKSPACE
    from quarry.db import Run, session

    records = {}
    with session() as db:
        for entry in report["rows"]:
            run = db.get(Run, entry["run_id"])
            if (run is None or run.workspace_id != EVAL_WORKSPACE or run.status != "completed"
                    or run.provider != "groq" or run.paid_consent
                    or run.diagnostics.get("evaluation_protocol") != "isolated-v2"
                    or run.diagnostics.get("history_run_ids") != []
                    or run.diagnostics.get("generation_model") != report["model"]
                    or run.diagnostics.get("generation_provider") != "groq"):
                raise ValueError("Primary research is not a completed fixed free-model run")
            records[run.id] = {
                "conversation_id": run.conversation_id, "mode": run.retrieval_mode,
                "response_sha256": hashlib.sha256(run.answer.encode()).hexdigest(),
                "generation_request_sha256": run.diagnostics.get("generation_request_sha256", []),
                "model_calls": run.model_calls, "tokens": run.token_usage,
                "history_run_ids": run.diagnostics["history_run_ids"],
                "evidence_sha256": sha(run.evidence[:5]),
                "answer_contexts_sha256": sha([e["text"][:1200] for e in sorted(run.evidence, key=lambda e: e.get("kind") != "calculation")[:6]]),
            }
    (root / "results" / filename).write_text(json.dumps(records, indent=2))


def audit_suite(root, *, export=False, require_complete=False):
    manifest = json.loads((root / "manifest.json").read_text())
    for name, digest in manifest["sha256"].items():
        if hashlib.sha256((root / name).read_bytes()).hexdigest() != digest:
            raise ValueError("Frozen corpus changed")
    cases = [c for c in json.loads((root / "cases.json").read_text()) if c["split"] == "test" and c["relevant_sources"]][:37]
    selected = {c["id"]: c for c in cases}
    if len(selected) != 37:
        raise ValueError("Expected 37 frozen selected cases")
    summaries, inputs, conversations, claims, judges, reviews, origins = [], {}, set(), [], set(), [], set()
    for mode in MODES:
        path = root / "results" / ("isolated-v2-" + mode + ".json")
        if not path.exists():
            summaries.append({"mode": mode, "status": "pending", "completed": 0, "requested": 37})
            continue
        raw = path.read_bytes()
        report = json.loads(raw)
        inputs[path.name] = hashlib.sha256(raw).hexdigest()
        definition = report["protocol_definition"]
        if (report["protocol_sha256"] != sha(definition) or definition["version"] != "isolated-v2"
                or definition["mode"] != mode or definition["case_ids"] != list(selected)
                or definition["dataset_sha256"] != manifest["sha256"]
                or report["dataset_sha256"] != manifest["sha256"]
                or report["mode"] != mode or report["protocol"] != "isolated-v2"
                or report["campaign_id"] != "isolated-v2-" + mode
                or report["provider"] != definition["provider"] or report["provider"] != "groq"
                or report["model"] != definition["model"] or report["model"] != "openai/gpt-oss-120b"
                or report["requested_case_count"] != 37 or report["automatic_paid_switch"]):
            raise ValueError("Campaign protocol identity mismatch")
        if report["judge_conversation_id"] in conversations or report["judge_conversation_id"] in judges:
            raise ValueError("Judge conversation isolation violated")
        judges.add(report["judge_conversation_id"])
        for case_id, conversation in report.get("case_conversations", {}).items():
            if case_id not in selected or conversation in conversations or conversation in judges:
                raise ValueError("Evaluation conversation isolation violated")
            conversations.add(conversation)
        filename = "isolated-v2-" + mode + "-verdicts.json"
        research_filename = "isolated-v2-" + mode + "-research.json"
        if export:
            export_judges(root, report, filename)
            export_research(root, report, research_filename)
        evidence_path = root / "results" / filename
        evidence = json.loads(evidence_path.read_text()) if evidence_path.exists() else {}
        research_path = root / "results" / research_filename
        research = json.loads(research_path.read_text()) if research_path.exists() else {}
        if evidence_path.exists():
            inputs[filename] = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
        if research_path.exists():
            inputs[research_filename] = hashlib.sha256(research_path.read_bytes()).hexdigest()
        seen, completed, checked = set(), [], 0
        for row in report["rows"]:
            case_id = row["case_id"]
            if case_id in seen or case_id not in selected:
                raise ValueError("Duplicate or unexpected case")
            seen.add(case_id)
            case = selected[case_id]
            reviews.append({"mode": mode, "case_id": case_id, "answer_sha256": row["response_sha256"], "context_sha256": sha(row["answer_contexts"]), "answer_review_complete": "", "unlisted_claims_reviewed": "", "assistant_reviewer": "", "support_summary": "", "human_verdict": ""})
            expected_research = {
                "conversation_id": row["conversation_id"], "mode": row["mode"],
                "response_sha256": row["response_sha256"],
                "generation_request_sha256": row["generation_request_sha256"],
                "model_calls": row["model_calls"], "tokens": row["tokens"],
                "history_run_ids": row["history_run_ids"],
                "evidence_sha256": sha(row["evidence"]), "answer_contexts_sha256": sha(row["answer_contexts"]),
            }
            if research.get(row["run_id"]) != expected_research:
                raise ValueError("Primary research lacks matching exported database provenance")
            if row["history_run_ids"] != []:
                raise ValueError("Primary research consumed conversation history")
            if (row["conversation_id"] != report["case_conversations"][case_id]
                    or row["mode"] != mode or row["question"] != case["question"]
                    or row["reference"] != case["reference"]
                    or row["response_sha256"] != hashlib.sha256(row["response"].encode()).hexdigest()
                    or not row["generation_request_sha256"]
                    or len(row["generation_request_sha256"]) != row["model_calls"]
                    or row["contexts"] != [e["text"] for e in row["evidence"]]):
                raise ValueError("Research provenance mismatch")
            if set(row["metrics"]) - METRICS:
                raise ValueError("Unknown metric")
            for name, value in row["metrics"].items():
                configuration = row["metric_configuration"][name]
                arguments = {"user_input": case["question"], "retrieved_contexts": row["answer_contexts"] if name == "faithfulness" else row["contexts"]}
                arguments["response" if name == "faithfulness" else "reference"] = row["response"] if name == "faithfulness" else case["reference"]
                if (configuration.get("arguments_sha256") != sha(arguments)
                        or configuration.get("provider") != "groq" or configuration.get("model") != report["model"]
                        or configuration.get("reasoning_effort") != "low" or configuration.get("reasoning_format") != "hidden"
                        or configuration.get("max_completion_tokens") != 2000):
                    raise ValueError("Metric arguments/provider mismatch")
                ids = configuration.get("judge_run_ids", [])
                if not ids or any(run_id not in evidence for run_id in ids):
                    raise ValueError("Primary metric lacks saved judge provenance")
                requests = configuration.get('judge_requests', [])
                if [r.get('run_id') for r in requests] != ids or any(r.get('request_sha256') != evidence[r['run_id']]['request_sha256'] for r in requests):
                    raise ValueError("Judge request hashes do not match exported RPC provenance")
                for run_id in ids:
                    saved=evidence[run_id]
                    if hashlib.sha256(saved['raw_output'].encode()).hexdigest() != saved['answer_sha256'] or json.loads(saved['raw_output']) != saved['output']:
                        raise ValueError('Raw judge output digest/content mismatch')
                origins.update(evidence[run_id]['origin_conversation_id'] for run_id in ids)
                outputs = [evidence[run_id]["output"] for run_id in ids]
                if name == "context_precision" and len(outputs) != len(row["contexts"]):
                    raise ValueError("Precision verdict count mismatch")
                close(value, judge_score(name, outputs), 1e-12)
                checked += 1
                if name == "faithfulness":
                    for index, statement in enumerate(outputs[-1]["statements"], 1):
                        claims.append({
                            "mode": mode, "case_id": case_id, "claim_number": index,
                            "claim": statement["statement"], "model_verdict": statement["verdict"],
                            "model_reason": statement.get("reason", ""),
                            "context_sha256": sha(row["answer_contexts"]),
                            "assistant_support_decision": "", "assistant_review_note": "", "assistant_reviewer": "", "human_verdict": "",
                        })
            if set(row["metrics"]) == METRICS:
                completed.append(row)
        if report["status"] == "completed" and len(completed) != 37:
            raise ValueError("Completed campaign is missing cases")
        summary = {"mode": mode, "status": report["status"], "completed": len(completed), "requested": 37, "verdict_metrics_recomputed": checked}
        if completed:
            summary["means"] = {name: statistics.mean(r["metrics"][name] for r in completed) for name in sorted(METRICS)}
            summary["generated_answers"] = sum(r["answer_kind"] == "generated" for r in completed)
            summary["citation_fallback_answers"] = sum(r["answer_kind"] == "citation_fallback" for r in completed)
            for name, key in (("answer_latency", "latency_ms"), ("first_evidence", "first_evidence_ms")):
                values = [r[key] for r in completed if r.get(key) is not None]
                if values:
                    summary[name + "_p50_ms"] = quantile(values, .5)
                    summary[name + "_p95_ms"] = quantile(values, .95)
            summary["generation_tokens"] = sum(r["tokens"] for r in completed)
        summaries.append(summary)
    if origins & conversations:
        raise ValueError('Judge RPC origin overlaps isolated research history')
    complete = all(s["status"] == "completed" and s["completed"] == 37 for s in summaries)
    result = {
        "status": "passed", "created_at": datetime.now(UTC).isoformat(), "complete": complete,
        "completed": sum(s["completed"] for s in summaries), "requested": 148,
        "summaries": summaries, "input_sha256": inputs, "provider_calls": 0,
        "scope": "Independent arithmetic/provenance checks; model judgments and corpus labels are not certified factual truth",
        "expected_claim_reviews": {
            f"{r['mode']}|{r['case_id']}|{r['claim_number']}": sha({key: r[key] for key in ("claim", "model_verdict", "model_reason", "context_sha256")})
            for r in claims
        },
        "expected_answer_reviews": {
            f"{r['mode']}|{r['case_id']}": {key: r[key] for key in ("answer_sha256", "context_sha256")}
            for r in reviews
        },
    }
    (root / "results/isolated-mathematical-audit.json").write_text(json.dumps(result, indent=2, allow_nan=False))
    # Preserve actual review decisions across repeated exports; never auto-fill them.
    worksheet = root / "results/isolated-factual-support-review.csv"
    existing = {}
    if worksheet.exists():
        with worksheet.open(newline="") as handle:
            existing = {(r["mode"], r["case_id"], r["claim_number"]): r for r in csv.DictReader(handle)}
    if claims:
        for claim in claims:
            old = existing.get((claim["mode"], claim["case_id"], str(claim["claim_number"])))
            if old and old["claim"] == claim["claim"] and old.get("context_sha256") == claim["context_sha256"]:
                for key in ("assistant_support_decision", "assistant_review_note", "assistant_reviewer", "human_verdict"):
                    claim[key] = old.get(key, "")
        with worksheet.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(claims[0]))
            writer.writeheader()
            writer.writerows(claims)
    case_worksheet = root / "results/isolated-answer-review.csv"
    previous_reviews = {}
    if case_worksheet.exists():
        with case_worksheet.open(newline="") as handle:
            previous_reviews = {(r["mode"], r["case_id"]): r for r in csv.DictReader(handle)}
    if reviews:
        for review in reviews:
            old = previous_reviews.get((review["mode"], review["case_id"]))
            if old and old["answer_sha256"] == review["answer_sha256"] and old["context_sha256"] == review["context_sha256"]:
                for name in ("answer_review_complete", "unlisted_claims_reviewed", "assistant_reviewer", "support_summary", "human_verdict"):
                    review[name] = old.get(name, "")
        with case_worksheet.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(reviews[0]))
            writer.writeheader()
            writer.writerows(reviews)
    if require_complete and not complete:
        raise ValueError("All 148 isolated evaluations must be completed; partial scores do not satisfy release")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evaluation-root", type=Path, default=Path("/app/evaluation"))
    parser.add_argument("--export-judges", action="store_true")
    parser.add_argument("--require-complete", action="store_true")
    args = parser.parse_args()
    print(json.dumps(audit_suite(args.evaluation_root, export=args.export_judges, require_complete=args.require_complete)))


if __name__ == "__main__":
    main()
