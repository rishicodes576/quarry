"""Offline finalizer policy regressions using synthetic artifacts in a temporary tree."""

import csv
import hashlib
import importlib.util
import json

import pytest


@pytest.fixture
def release_tree(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend("/opt/quarry-operator")
    spec = importlib.util.spec_from_file_location("quarry_test_finalizer", "/opt/quarry-operator/finalize.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "fingerprint", lambda: "current-source")
    monkeypatch.setattr(module, "current_protocols", lambda: True)
    folder = tmp_path / "evaluation/results"
    folder.mkdir(parents=True)
    (tmp_path / "evaluation/requirements.json").write_text("[]")

    def save(name, data):
        path = folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data))
        return hashlib.sha256(path.read_bytes()).hexdigest()

    junit = folder / "backend-junit.xml"
    junit.write_text('<testsuites><testsuite><testcase classname="tests.synthetic" name="test_gate"/></testsuite></testsuites>')
    save("verification.json", {"status": "passed", "source_sha256": "current-source", "backend_junit_sha256": hashlib.sha256(junit.read_bytes()).hexdigest()})
    save("security/summary.json", {"status": "passed", "source_sha256": "current-source"})
    legacy_hash = save("live-ragas.json", {"status": "completed", "rows": [{"metrics": {"a": 1, "b": 1, "c": 1}} for _ in range(37)]})
    save("mathematical-audit.json", {"status": "passed", "live_complete": True, "input_sha256": {"results/live-ragas.json": legacy_hash}})
    inputs = {}
    claims, answers, expected_claims, expected_answers = [], [], {}, {}
    for mode in ("dense", "bm25", "hybrid", "hybrid_rerank"):
        for suffix in ("", "-verdicts", "-research"):
            name = f"isolated-v2-{mode}{suffix}.json"
            inputs[name] = save(name, {"synthetic": True})
        for i in range(37):
            case = f"q{i:03}"
            claim = {"mode": mode, "case_id": case, "claim_number": "1", "claim": "Synthetic claim", "model_verdict": "1", "model_reason": "Fixture", "context_sha256": "context", "assistant_support_decision": "supported", "assistant_review_note": "Synthetic test note", "assistant_reviewer": "simulated-test"}
            bound = {k: claim[k] for k in ("claim", "model_reason", "context_sha256")}
            bound["model_verdict"] = 1
            expected_claims[f"{mode}|{case}|1"] = hashlib.sha256(json.dumps(bound, sort_keys=True).encode()).hexdigest()
            claims.append(claim)
            answer = {"mode": mode, "case_id": case, "answer_sha256": "answer", "context_sha256": "context", "answer_review_complete": "yes", "unlisted_claims_reviewed": "yes", "assistant_reviewer": "simulated-test", "support_summary": "Synthetic test note"}
            answers.append(answer)
            expected_answers[f"{mode}|{case}"] = {"answer_sha256": "answer", "context_sha256": "context"}
    for name, rows in (("isolated-factual-support-review.csv", claims), ("isolated-answer-review.csv", answers)):
        with (folder / name).open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    save("isolated-mathematical-audit.json", {"status": "passed", "complete": True, "completed": 148, "input_sha256": inputs, "expected_claim_reviews": expected_claims, "expected_answer_reviews": expected_answers})
    return module, folder


def test_synthetic_complete_readiness_policy(release_tree):
    module, _ = release_tree
    assert module.readiness()["status"] == "complete"


@pytest.mark.parametrize("corruption", ["input", "claims", "context", "answer", "junit"])
def test_readiness_rejects_stale_or_truncated_evidence(release_tree, corruption):
    module, folder = release_tree
    if corruption == "input":
        (folder / "isolated-v2-dense-verdicts.json").write_text('{"changed":true}')
    elif corruption == "junit":
        (folder / "backend-junit.xml").write_text("<changed/>")
    elif corruption == "claims":
        path = folder / "isolated-factual-support-review.csv"
        lines = path.read_text().splitlines()
        path.write_text("\n".join(lines[:2]) + "\n")
    elif corruption == "context":
        path = folder / "isolated-factual-support-review.csv"
        path.write_text(path.read_text().replace("context", "changed-context", 1))
    else:
        path = folder / "isolated-answer-review.csv"
        path.write_text(path.read_text().replace("answer,context", "changed,context", 1))
    assert module.readiness()["status"] == "incomplete"


def test_packaging_refuses_source_change_before_git(release_tree):
    module, _ = release_tree
    with pytest.raises(ValueError, match="Source changed"):
        module.package({"source_sha256": "old-source"})
    with pytest.raises(ValueError, match="unsafe"):
        module.check_payload(".env", b"private configuration", [])
    with pytest.raises(ValueError, match="Credential"):
        module.check_payload("docs/note.md", b"simulated-secret", [b"simulated-secret"])


def test_junit_rejects_entity_declarations(release_tree):
    module,folder=release_tree
    path=folder/'malicious.xml'
    path.write_text('<!DOCTYPE x [<!ENTITY x "amplified">]><testsuite/>')
    with pytest.raises(ValueError,match='DTD/entity'):
        module.passed_junit(path)


def test_source_results_and_assets_are_not_generated_report_exclusions(release_tree, monkeypatch):
    import release

    module,_=release_tree
    root=module.ROOT
    monkeypatch.setattr(release,'ROOT',root)
    for name in ('compose.yaml','.dockerignore','.env.example','.gitignore','.gitattributes'):
        (root/name).write_text('fixture')
    baseline=release.fingerprint()
    route=root/'frontend/src/app/results/page.tsx'
    route.parent.mkdir(parents=True)
    route.write_text('export default function Page() { return null; }')
    with_route=release.fingerprint()
    assert with_route!=baseline
    asset=root/'frontend/src/assets/helper.ts'
    asset.parent.mkdir(parents=True)
    asset.write_text('export const value = 1;')
    with_asset=release.fingerprint()
    assert with_asset!=with_route
    (root/'evaluation/results/generated.json').write_text('{}')
    assert release.fingerprint()==with_asset
