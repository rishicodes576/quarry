import time
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from quarry import providers, retrieval
from quarry.api import app
from quarry.config import settings
from quarry.db import Document, Event, Job, Run, UsageDay, session
from quarry.queue import LeaseLost, claim, fenced
from quarry.worker import process
from tests.conftest import finish_document


def conversation(client):
    response = client.post("/v1/conversations", json={"title": "New research"})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def submission(client, conversation_id, key="test-request-0001", **kwargs):
    return client.post(
        "/v1/runs",
        headers={"Idempotency-Key": key},
        json={
            "conversation_id": conversation_id,
            "question": "How do worker leases prevent stale commits?",
            **kwargs,
        },
    )


def test_authentication_logout_and_cross_origin(client):
    assert client.get("/v1/auth/me").status_code == 200
    assert (
        client.post(
            "/v1/conversations", json={"title": "x"}, headers={"Origin": "https://attacker.example"}
        ).status_code
        == 403
    )
    response = client.post("/v1/auth/logout")
    assert response.status_code == 204
    assert client.get("/v1/auth/me").status_code == 401
    assert (
        client.post(
            "/v1/auth/login", json={"email": "owner@example.com", "password": "wrong"}
        ).status_code
        == 401
    )


def test_upload_is_deduplicated_and_private(client, actors):
    doc = finish_document(client)
    repeated = client.post(
        "/v1/documents",
        files={
            "file": (
                "copy.md",
                b"A worker uses a 90 second lease. Every result is fenced by the current token.",
                "text/markdown",
            )
        },
    )
    assert repeated.json()["id"] == doc.id
    assert client.get(f"/v1/documents/{doc.id}/source").status_code == 200
    assert client.get(f"/v1/documents/{doc.id}/passages").json()
    with TestClient(app) as other:
        other.post(
            "/v1/auth/login",
            json={"email": "other@example.com", "password": "a-long-test-password"},
        )
        for suffix in ["source", "passages"]:
            assert other.get(f"/v1/documents/{doc.id}/{suffix}").status_code == 404
        assert other.delete(f"/v1/documents/{doc.id}").status_code == 404
        assert not other.get("/v1/documents").json()
        assert not retrieval.search(actors["other"].workspace_id, "worker lease")["hits"]


def test_viewer_cannot_mutate(client):
    client.post("/v1/auth/logout")
    client.post(
        "/v1/auth/login", json={"email": "viewer@example.com", "password": "a-long-test-password"}
    )
    assert client.post("/v1/conversations", json={"title": "denied"}).status_code == 403
    assert (
        client.post("/v1/documents", files={"file": ("x.txt", b"data", "text/plain")}).status_code
        == 403
    )
    assert (
        client.post(
            "/v1/members", json={"email": "new@example.com", "password": "new-long-password"}
        ).status_code
        == 403
    )


def test_payload_idempotency_and_transactional_queue(client):
    cid = conversation(client)
    first = submission(client, cid)
    assert first.status_code == 202, first.text
    second = submission(client, cid)
    assert second.json()["id"] == first.json()["id"]
    assert submission(client, cid, question="Changed question").status_code == 409
    assert submission(client, cid, provider="openai", paid_consent=True).status_code == 422
    with session() as db:
        assert len(db.scalars(select(Job).where(Job.kind == "research")).all()) == 1
        assert len(db.scalars(select(Event)).all()) == 1


def test_complete_real_retrieval_graph_export_and_event_replay(client):
    finish_document(client)
    cid = conversation(client)
    response = submission(client, cid)
    run_id = response.json()["id"]
    job = claim()
    assert job and job.kind == "research"
    process(job)
    result = client.get(f"/v1/runs/{run_id}").json()
    assert result["status"] == "completed", result
    assert result["evidence"] and "Extractive mode" in result["answer"]
    assert result["token_usage"] == 0
    assert result["diagnostics"]["citations"]["references_valid"]
    events = client.get(f"/v1/runs/{run_id}/events").json()
    assert any(e["kind"] == "completed" for e in events)
    cursor = events[2]["id"]
    later = client.get(f"/v1/runs/{run_id}/events?after={cursor}").json()
    assert all(e["id"] > cursor for e in later)
    streamed = client.get(f"/v1/runs/{run_id}/stream?after={cursor}")
    assert streamed.status_code == 200 and "event: done" in streamed.text
    exported = client.get(f"/v1/runs/{run_id}/export")
    assert "SHA-256" in exported.text and "Provider: extractive" in exported.text
    assert client.get("/v1/overview").json()["completed_runs"] == 1


def test_deletion_immediately_excludes_passages_and_cleans_storage(client, actors):
    doc = finish_document(client)
    assert retrieval.search(actors["owner"].workspace_id, "worker lease")["hits"]
    assert client.delete(f"/v1/documents/{doc.id}").status_code == 204
    assert not retrieval.search(actors["owner"].workspace_id, "worker lease")["hits"]
    assert client.get(f"/v1/documents/{doc.id}/source").status_code == 404
    job = claim()
    process(job)
    # Identical content may be uploaded again after deletion; deleted hashes do not block it.
    new_doc = finish_document(client)
    assert new_doc.id != doc.id


def test_malformed_upload_fails_asynchronously_with_visible_reason(client):
    result = client.post(
        "/v1/documents", files={"file": ("broken.pdf", b"broken pdf", "application/pdf")}
    )
    assert result.status_code == 202
    process(claim())
    doc = next(d for d in client.get("/v1/documents").json() if d["id"] == result.json()["id"])
    assert doc["status"] == "failed" and "PDF" in doc["error"]
    assert client.post(f"/v1/documents/{doc['id']}/retry").status_code == 200
    assert (
        client.post("/v1/documents", files={"file": ("empty.txt", b"", "text/plain")}).status_code
        == 422
    )


def test_worker_claim_recovery_and_fencing(make_run):
    run = make_run()
    old = claim()
    with session() as db, db.begin():
        db.get(Job, old.id).lease_until = time.time() - 1
    replacement = claim()
    assert replacement.id == old.id and replacement.fence != old.fence
    with pytest.raises(LeaseLost):
        with fenced(old):
            pytest.fail("Stale worker entered a result transaction")
    process(replacement)
    with session() as db:
        assert db.get(Run, run.id).status == "completed"


def test_parallel_claims_are_unique_and_workspace_capacity_is_shared(make_run):
    for _ in range(8):
        make_run()
    with ThreadPoolExecutor(max_workers=8) as pool:
        claimed = list(pool.map(lambda _: claim(), range(8)))
    claimed = [j for j in claimed if j]
    assert len(claimed) == 4
    assert len({j.id for j in claimed}) == 4


def test_cancellation_before_execution_and_isolation(client, make_run):
    run = make_run()
    assert client.post(f"/v1/runs/{run.id}/cancel").status_code == 202
    process(claim())
    with session() as db:
        assert db.get(Run, run.id).status == "cancelled"
    assert client.get(f"/v1/runs/{run.id}/export").status_code == 409
    assert client.get("/v1/runs/unknown").status_code == 404


def test_429_pauses_without_any_provider_switch(make_run, monkeypatch):
    cfg = settings()
    monkeypatch.setattr(cfg, "groq_api_key", "gsk_test_key")
    monkeypatch.setattr(cfg, "groq_free_plan_confirmed", True)
    run = make_run("groq")
    job = claim()
    called = []

    def response(request):
        called.append(str(request.url))
        return httpx.Response(429, headers={"retry-after": "7"})

    with pytest.raises(providers.ProviderQuota):
        providers.complete(
            job, [{"role": "user", "content": "test"}], transport=httpx.MockTransport(response)
        )
    assert len(called) == 1 and called[0].startswith("https://api.groq.com/")
    with session() as db:
        row = db.get(Run, run.id)
        assert row.provider == "groq" and row.reserved_tokens == 0 and row.token_usage == 0
        assert db.scalars(select(UsageDay)).first().reserved == 0
    monkeypatch.setattr(
        "quarry.agent.execute_run",
        lambda _: (_ for _ in ()).throw(providers.ProviderQuota(retry_after=7)),
    )
    process(job)
    with session() as db:
        assert db.get(Run, run.id).status == "quota_exhausted"


def test_optional_paid_provider_requires_both_controls_and_mocked_transport(make_run, monkeypatch):
    cfg = settings()
    monkeypatch.setattr(cfg, "openai_api_key", "simulated-key")
    with pytest.raises(ValueError):
        providers.require_provider("openai", True)
    monkeypatch.setattr(cfg, "allow_paid_providers", True)
    with pytest.raises(ValueError):
        providers.require_provider("openai", False)
    run = make_run("openai", paid_consent=True)
    job = claim()
    calls = []

    def response(request):
        calls.append(request)
        return httpx.Response(
            200,
            json={
                "usage": {"total_tokens": 42},
                "choices": [{"message": {"content": "Test response"}}],
            },
        )

    assert (
        providers.complete(
            job, [{"role": "user", "content": "test"}], transport=httpx.MockTransport(response)
        )
        == "Test response"
    )
    assert len(calls) == 1
    with session() as db:
        assert db.get(Run, run.id).token_usage == 42
    # MockTransport intercepted this request; no paid endpoint was contacted.


def test_shared_token_reservation_enforces_budget(make_run, monkeypatch):
    monkeypatch.setattr(settings(), "max_daily_tokens", providers.RESERVATION)
    first, _second = make_run(), make_run()
    a, b = claim(), claim()
    providers.reserve(a)
    with pytest.raises(providers.ProviderQuota):
        providers.reserve(b)
    providers.settle(a, None)
    with session() as db:
        row = db.get(Run, first.id)
        assert row.billed_tokens == providers.RESERVATION and row.diagnostics["usage_unknown"]


def test_missing_web_service_degrades_instead_of_failing_the_brief(client, monkeypatch):
    finish_document(client)
    cid = conversation(client)
    response = submission(client, cid, allow_web=True)
    monkeypatch.setattr("quarry.tools.execute", lambda *_: (_ for _ in ()).throw(TimeoutError()))
    process(claim())
    result = client.get("/v1/runs/" + response.json()["id"]).json()
    assert result["status"] == "completed" and result["diagnostics"]["tool_errors"]


def test_all_retrieval_modes_use_real_local_models(client, actors):
    finish_document(client)
    result = client.post(
        "/v1/search/compare", json={"query": "How does a fencing token protect a worker result?"}
    )
    assert result.status_code == 200
    values = result.json()
    assert len(values) == 4 and all(v["hits"] for v in values)
    assert all(v["latency_ms"] > 0 for v in values)
    assert client.get("/health/ready").status_code == 200
    assert client.get("/metrics").status_code == 200
    assert client.get("/v1/evaluations").status_code == 200


def test_worker_process_death_resumes_persisted_graph_stages(client, make_run):
    import os
    import subprocess
    import sys

    finish_document(client)
    run = make_run()
    script = (
        "import os; from quarry import agent; from quarry.queue import claim; "
        "from quarry.worker import process; "
        "agent.excerpt_answer=lambda evidence: os._exit(137); process(claim())"
    )
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-c", script],
        env={**os.environ, "QUARRY_LEASE_SECONDS": "2"},
        capture_output=True,
        timeout=45,
    )
    assert result.returncode == 137, result.stderr.decode()
    time.sleep(2.2)
    job = claim()
    assert job and job.target_id == run.id and job.attempt == 2
    process(job)
    with session() as db:
        recovered = db.get(Run, run.id)
        assert recovered.status == "completed"
        stages = [
            e.payload.get("stage")
            for e in db.scalars(
                select(Event).where(Event.run_id == run.id, Event.kind == "stage_completed")
            ).all()
        ]
        assert stages.count("plan") == 1 and stages.count("retrieve") == 1


def test_newer_version_wins_even_when_older_indexing_finishes_later(client, actors):
    old = client.post(
        "/v1/documents",
        files={"file": ("version.md", b"Old setting uses 30 second cache TTL.", "text/markdown")},
    ).json()
    new = client.post(
        "/v1/documents",
        files={"file": ("version.md", b"New setting uses 90 second cache TTL.", "text/markdown")},
    ).json()
    a, b = claim(), claim()
    process(b)
    process(a)
    with session() as db:
        assert db.get(Document, new["id"]).status == "ready"
        assert db.get(Document, old["id"]).status == "superseded"
    result = retrieval.search(actors["owner"].workspace_id, "cache TTL")
    assert all(hit["document_id"] == new["id"] for hit in result["hits"])


def test_deletion_redacts_historical_evidence_and_checkpoints(client):
    doc = finish_document(client)
    result = submission(client, conversation(client)).json()
    process(claim())
    assert client.get("/v1/runs/" + result["id"]).json()["evidence"]
    client.delete("/v1/documents/" + doc.id)
    process(claim())
    value = client.get("/v1/runs/" + result["id"]).json()
    assert value["evidence"] == [] and "deleted" in value["answer"]
    assert "90 second" not in value["answer"]
