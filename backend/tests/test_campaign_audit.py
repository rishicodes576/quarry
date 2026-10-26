"""Simulated 148-row fixtures test audit math/corruption; no model calls or accuracy claims."""

import hashlib
import json
from pathlib import Path

import pytest

from quarry.campaign_audit import MODES, audit_suite, sha


@pytest.fixture
def isolated_matrix(tmp_path):
    original = Path("/app/evaluation")
    (tmp_path / "results").mkdir()
    for name in ("manifest.json", "cases.json", "corpus.json"):
        (tmp_path / name).write_bytes((original / name).read_bytes())
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    cases = [c for c in json.loads((tmp_path / "cases.json").read_text()) if c["split"] == "test" and c["relevant_sources"]][:37]
    for mode in MODES:
        definition = {"version": "isolated-v2", "mode": mode, "case_ids": [c["id"] for c in cases], "dataset_sha256": manifest["sha256"], "provider": "groq", "model": "openai/gpt-oss-120b"}
        report = {"protocol_definition": definition, "protocol_sha256": sha(definition), "dataset_sha256": manifest["sha256"], "protocol": "isolated-v2", "campaign_id": "isolated-v2-" + mode, "mode": mode, "provider": "groq", "model": definition["model"], "status": "completed", "requested_case_count": 37, "automatic_paid_switch": False, "rows": [], "judge_conversation_id": mode + "-judge", "case_conversations": {}}
        exported, research = {}, {}
        for case in cases:
            prefix = mode + "-" + case["id"]
            row = {"case_id": case["id"], "conversation_id": prefix + "-research", "run_id": prefix, "mode": mode, "question": case["question"], "reference": case["reference"], "response": "Simulated answer", "contexts": ["Simulated context"], "evidence": [{"text": "Simulated context"}], "answer_contexts": ["Simulated context"], "model_calls": 1, "tokens": 3, "history_run_ids": [], "generation_request_sha256": ["a" * 64], "metrics": {}, "metric_configuration": {}, "latency_ms": 1, "first_evidence_ms": .5, "answer_kind": "generated"}
            row["response_sha256"] = hashlib.sha256(row["response"].encode()).hexdigest()
            report["case_conversations"][case["id"]] = row["conversation_id"]
            for name in ("context_precision", "context_recall", "faithfulness"):
                outputs = [{"verdict": 1}] if name == "context_precision" else [{"classifications": [{"attributed": 1}]}] if name == "context_recall" else [{"statements": ["Simulated answer"]}, {"statements": [{"statement": "Simulated answer", "verdict": 1, "reason": "Simulated judgment"}]}]
                ids = [prefix + "-" + name + str(i) for i in range(len(outputs))]
                for run_id, output in zip(ids, outputs, strict=True):
                    raw_output=json.dumps(output)
                    exported[run_id] = {"output": output, "raw_output": raw_output, "answer_sha256": hashlib.sha256(raw_output.encode()).hexdigest(), "request_sha256": "b" * 64, "origin_conversation_id": "historical-exact-prompt-cache"}
                arguments = {"user_input": case["question"], "retrieved_contexts": row["contexts"]}
                arguments["response" if name == "faithfulness" else "reference"] = row["response"] if name == "faithfulness" else case["reference"]
                row["metrics"][name] = 1 / (1 + 1e-10) if name == "context_precision" else 1
                row["metric_configuration"][name] = {"provider": "groq", "model": definition["model"], "reasoning_effort": "low", "reasoning_format": "hidden", "max_completion_tokens": 2000, "arguments_sha256": sha(arguments), "judge_run_ids": ids, "judge_requests": [{"run_id": run_id, "request_sha256": "b" * 64} for run_id in ids]}
            research[prefix] = {key: row[key] for key in ("conversation_id", "mode", "response_sha256", "generation_request_sha256", "model_calls", "tokens", "history_run_ids")}
            research[prefix].update(evidence_sha256=sha(row["evidence"]), answer_contexts_sha256=sha(row["answer_contexts"]))
            report["rows"].append(row)
        for suffix, data in (("", report), ("-verdicts", exported), ("-research", research)):
            (tmp_path / "results" / ("isolated-v2-" + mode + suffix + ".json")).write_text(json.dumps(data))
    return tmp_path


def test_complete_simulated_matrix_has_444_recomputed_metrics(isolated_matrix):
    result = audit_suite(isolated_matrix, require_complete=True)
    assert result["complete"] and result["completed"] == 148
    assert sum(s["verdict_metrics_recomputed"] for s in result["summaries"]) == 444
    assert len(result["expected_answer_reviews"]) == 148
    assert len(result["expected_claim_reviews"]) == 148
    worksheet = isolated_matrix / "results/isolated-answer-review.csv"
    assert ",yes," not in worksheet.read_text()  # Real review is never fabricated.


@pytest.mark.parametrize("corruption", ["score", "args", "request", "response", "duplicate", "protocol", "history", "missing-rpc"])
def test_primary_audit_rejects_corruption(isolated_matrix, corruption):
    path = isolated_matrix / "results/isolated-v2-dense.json"
    report = json.loads(path.read_text())
    row = report["rows"][0]
    if corruption == "score":
        row["metrics"]["faithfulness"] = .5
    elif corruption == "args":
        row["metric_configuration"]["faithfulness"]["arguments_sha256"] = "changed"
    elif corruption == "request":
        row["metric_configuration"]["faithfulness"]["judge_requests"] = []
    elif corruption == "response":
        row["response"] = "Altered answer"
    elif corruption == "duplicate":
        report["rows"].append(row)
    elif corruption == "protocol":
        report["protocol_definition"]["model"] = "another-model"
    elif corruption == "history":
        row["history_run_ids"] = ["prior-answer"]
    else:
        (isolated_matrix / "results/isolated-v2-dense-verdicts.json").unlink()
    path.write_text(json.dumps(report))
    with pytest.raises(ValueError):
        audit_suite(isolated_matrix, require_complete=True)
