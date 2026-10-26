"""Real-DB isolation and API guards; simulated metrics issue no provider requests."""

import asyncio
import copy
import json
import sys
import types
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from quarry import agent, campaigns, live_eval
from quarry import campaign_runner as runner
from quarry.api import app
from quarry.bootstrap import EVAL_WORKSPACE
from quarry.config import settings
from quarry.db import Conversation, Job, Run, Workspace, session
from quarry.queue import claim


def saved_report():
    return {"status": "quota_wait", "provider": "groq", "model": "openai/gpt-oss-120b", "requested_case_count": 37,
            "rows": [{"case_id": "q001", "run_id": "public-sample", "response": "<script>inert sample</script>", "contexts": ["passage"], "metrics": {"faithfulness": .5}, "diagnostics": {"private_key": "never-serialize"}}], "next_retry_at": "2026-10-26T00:01:00Z", "quota": {"scope": "deployment", "private": "never-serialize"}}


@pytest.fixture
def report_root(monkeypatch, tmp_path):
    (tmp_path / "results").mkdir()
    monkeypatch.setattr(campaigns, "ROOT", tmp_path)
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    return tmp_path


def test_campaign_api_authentication_and_public_field_allowlist(client, report_root):
    (report_root / "results/live-ragas.json").write_text(json.dumps(saved_report()))
    with TestClient(app) as anonymous:
        assert anonymous.get("/v1/evaluations/campaigns").status_code == 401
    response = client.get("/v1/evaluations/campaigns")
    assert response.status_code == 200 and len(response.json()) == 5
    assert response.json()[0]["completed"] == 0
    detail = client.get("/v1/evaluations/campaigns/legacy")
    assert detail.status_code == 200
    assert detail.json()["rows"][0]["response"] == "<script>inert sample</script>"
    assert "never-serialize" not in detail.text and "private_key" not in detail.text
    assert client.get("/v1/evaluations/campaigns/unknown").status_code == 404
    with pytest.raises(ValueError, match="Unknown"):
        campaigns.report_path("../private")


@pytest.mark.parametrize("kind", ["nan", "duplicate", "identity", "syntax", "shape"])
def test_campaign_rejects_corrupt_reports(client, report_root, kind):
    value = saved_report()
    if kind == "nan":
        value["rows"][0]["metrics"]["faithfulness"] = float("nan")
    elif kind == "duplicate":
        value["rows"] *= 2
    elif kind == "identity":
        value["model"] = "different-model"
    elif kind == "shape":
        value["rows"] = {}
    text = "{broken" if kind == "syntax" else json.dumps(value)
    (report_root / "results/live-ragas.json").write_text(text)
    response = client.get("/v1/evaluations/campaigns")
    assert response.status_code == 503 and "never-serialize" not in response.text


def test_changed_protocol_is_rejected(report_root, monkeypatch):
    value = saved_report()
    value.update(campaign_id="isolated-v2-dense", mode="dense", protocol="isolated-v2", protocol_sha256="old", protocol_definition={})
    (report_root / "results/isolated-v2-dense.json").write_text(json.dumps(value))
    monkeypatch.setattr(settings(), "groq_api_key", "local-simulated-key")
    monkeypatch.setattr(settings(), "groq_free_plan_confirmed", True)
    monkeypatch.setattr(runner, "protocol", lambda _: ({"version": "new"}, "new", []))
    with pytest.raises(SystemExit, match="Frozen protocol changed"):
        runner.run_isolated_once("dense")


def test_registry_rejects_symlinks_oversize_and_false_completion(client, report_root):
    path = report_root / "results/live-ragas.json"
    with path.open('wb') as handle:
        handle.truncate(17 * 1024 * 1024)
    assert client.get('/v1/evaluations/campaigns').status_code == 503
    path.unlink()
    target = report_root/'other.json'
    target.write_text(json.dumps(saved_report()))
    path.symlink_to(target)
    assert client.get('/v1/evaluations/campaigns').status_code == 503
    path.unlink()
    value=saved_report()
    value['status']='completed'
    path.write_text(json.dumps(value))
    assert client.get('/v1/evaluations/campaigns').status_code == 503
    value['status']='partial'
    value['rows'][0]['metrics']={name:1 for name in campaigns.METRICS}
    path.write_text(json.dumps(value))
    data=client.get('/v1/evaluations/campaigns/legacy').json()
    assert data['completed']==1 and data['provenance_gaps']==3


def test_agent_rejects_contaminated_isolated_history(make_run):
    row=make_run(diagnostics={'evaluation_protocol':'isolated-v2'})
    with session() as db, db.begin():
        db.add(Run(workspace_id=row.workspace_id,conversation_id=row.conversation_id,question='Previous answer',answer='Must not influence this case',status='completed',request_key='prior',request_hash='prior'))
    with pytest.raises(ValueError,match='cannot consume earlier'):
        agent.execute_run(claim())


def test_suite_preserves_legacy_then_visits_every_mode(report_root, monkeypatch):
    legacy = Mock(return_value={"status": "completed"})
    isolated = Mock(return_value={"status": "completed"})
    monkeypatch.setattr(live_eval, "run_live", legacy)
    monkeypatch.setattr(runner, "run_isolated_once", isolated)
    assert runner.run_suite()["status"] == "completed"
    assert [c.args[0] for c in isolated.call_args_list] == list(campaigns.MODES)
    legacy.assert_called_once_with(until_complete=False)
    with pytest.raises(ValueError):
        runner.run_suite(modes=["dense", "dense"])
    assert runner.run_suite(campaign="legacy")["status"] == "completed"


def test_malformed_scores_are_quarantined_without_filtering_low_scores():
    transport=live_eval.FreeJudgeTransport('simulated-conversation')
    transport.used_runs=['structured-but-empty-judgment']
    output={}
    assert live_eval.checked_score(0,output,transport,isolated=True)==0
    assert live_eval.checked_score(.25,output,transport,isolated=True)==.25
    assert not transport.rejected_run_ids
    with pytest.raises(ValueError,match='nonfinite'):
        live_eval.checked_score(float('nan'),output,transport,isolated=True)
    assert output['rejected_judge_runs']==['structured-but-empty-judgment']


def test_suite_stops_on_nonquota_failure_and_resumes_quota(report_root, monkeypatch):
    failed = {"status": "partial", "stopped_reason": "SchemaFailure"}
    monkeypatch.setattr(runner, "run_isolated_once", Mock(return_value=failed))
    assert runner.run_suite(campaign="isolated-v2", until_complete=True) == failed
    waiting = {"campaign_id": "isolated-v2-dense", "status": "partial", "quota": {"scope": "deployment"}}
    run = Mock(side_effect=[waiting, {"status": "completed"}])
    monkeypatch.setattr(runner, "run_isolated_once", run)
    pause = Mock()
    monkeypatch.setattr(live_eval, "wait_for_quota_reset", pause)
    assert runner.run_suite(campaign="isolated-v2", modes=["dense"], until_complete=True)["status"] == "completed"
    assert run.call_count == 2 and pause.call_count == 1


def test_isolated_case_conversations_exclude_judge_history(monkeypatch):
    # Metrics/planner transport are simulated; PostgreSQL conversations/jobs are real.
    modules = {}
    for name in ("openai", "ragas", "ragas.llms", "ragas.metrics", "ragas.metrics.collections"):
        module = types.ModuleType(name)
        module.__path__ = []
        modules[name] = module
        monkeypatch.setitem(sys.modules, name, module)
    modules["openai"].AsyncOpenAI = lambda **_: object()
    modules["ragas.llms"].llm_factory = lambda *_args, **_kwargs: object()

    class Metric:
        def __init__(self, **_):
            pass

        async def ascore(self, **_):
            return types.SimpleNamespace(value=1.0)

    for name in ("ContextPrecision", "ContextRecall", "Faithfulness"):
        setattr(modules["ragas.metrics.collections"], name, Metric)
    with session() as db, db.begin():
        db.add(Workspace(id=EVAL_WORKSPACE, name="Frozen sample"))
        db.flush()
        judge = Conversation(workspace_id=EVAL_WORKSPACE, title="Judge only")
        db.add(judge)
        db.flush()
        judge_id = judge.id
        db.add(Run(workspace_id=EVAL_WORKSPACE, conversation_id=judge_id, question="Ragas judge request", answer="Judge JSON must not enter history", status="completed", request_key="simulated-judge", request_hash="simulated"))
        orphan = Conversation(workspace_id=EVAL_WORKSPACE, title="Committed before JSON receipt")
        db.add(orphan)
        db.flush()
        orphan_id = orphan.id
        db.add(Run(workspace_id=EVAL_WORKSPACE, conversation_id=orphan_id, question="Old orphan attempt", answer="Must not leak into a fresh attempt", status="completed", request_key="orphan", request_hash="simulated"))
    seen = []

    def process(job):
        with session() as db, db.begin():
            row = db.get(Run, job.target_id)
            assert row.conversation_id != judge_id and row.retrieval_mode == "bm25"
            assert db.query(Run).filter(Run.conversation_id == row.conversation_id, Run.status == "completed").count() == 0
            seen.append(row.conversation_id)
            row.status, row.answer = "completed", "Synthetic answer [E1]"
            row.evidence = [{"text": "Synthetic passage", "kind": "document"}]
            row.diagnostics = {**row.diagnostics, "history_run_ids": []}
            db.get(Job, job.id).status = "done"

    monkeypatch.setattr(live_eval, "process", process)
    output = {"campaign_id": "isolated-v2-bm25", "rows": [], "case_conversations": {"q001": orphan_id}}
    cases = [{"id": f"q00{i}", "question": "Synthetic question", "reference": "Synthetic reference"} for i in (1, 2)]
    snapshots = []
    asyncio.run(live_eval.evaluate_cases(output, cases, judge_id, persist=lambda v: snapshots.append(copy.deepcopy(v)), isolated=True, mode="bm25"))
    assert output["status"] == "completed" and len(set(seen)) == 2
    assert orphan_id not in seen and output["case_conversations"]["q001"] != orphan_id
    assert len(output["rows"]) == 2 and snapshots
    assert all(r["mode"] == "bm25" and len(r["metrics"]) == 3 for r in output["rows"])
