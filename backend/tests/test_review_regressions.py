"""Regressions for concrete independent-review findings using isolated real services."""

import asyncio
import json
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from unittest.mock import Mock

import httpx
import pytest
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import func, select

from quarry import admin, api, ingest, live_eval, network, providers, storage, tools, worker
from quarry.config import settings
from quarry.db import Conversation, Document, Job, session
from quarry.live_eval import FreeJudgeTransport
from quarry.queue import claim
from quarry.schemas import ConversationInput


def test_stalled_api_bodies_release_all_slots(monkeypatch):
    monkeypatch.setattr(api, "BODY_TIMEOUT_SECONDS", 0.05)

    async def scenario():
        async def receive():
            await asyncio.sleep(2)
            return {"type": "http.request", "body": b"", "more_body": False}

        async def next_handler(_):
            return JSONResponse({}, status_code=401)

        def request():
            return Request(
                {"type": "http", "method": "POST", "path": "/v1/auth/login", "headers": []},
                receive=receive,
            )

        tasks = [asyncio.create_task(api.boundary(request(), next_handler)) for _ in range(16)]
        await asyncio.sleep(0.01)
        assert (await api.boundary(request(), next_handler)).status_code == 503
        assert all(r.status_code == 408 for r in await asyncio.gather(*tasks))

        async def empty():
            return {"type": "http.request", "body": b"", "more_body": False}

        healthy = Request(
            {"type": "http", "method": "POST", "path": "/", "headers": []}, receive=empty
        )
        assert (await api.boundary(healthy, next_handler)).status_code == 401

    asyncio.run(scenario())


def test_web_tool_uses_isolated_parser(monkeypatch):
    monkeypatch.setattr(
        tools, "fetch_public", lambda *_: (b"untrusted", "application/pdf", "https://example.com/a")
    )
    parser = Mock(return_value="Bounded parsed evidence")
    monkeypatch.setattr(tools, "isolated_extract", parser)
    assert (
        tools.execute("fetch_url", "https://example.com/a", True)[0]["text"]
        == "Bounded parsed evidence"
    )
    parser.assert_called_once_with(b"untrusted", "application/pdf", "https://example.com/a")


def test_dns_capacity_and_deadline_are_bounded(monkeypatch):
    release = threading.Event()
    futures = []
    monkeypatch.setattr(network, "public_addresses", lambda *_: release.wait(1) and ["8.8.8.8"])
    try:
        for _ in range(4):
            with pytest.raises(network.FetchError, match="deadline"):
                network.resolve_before_deadline("example.com", 443, time.monotonic() + 0.01)
        with pytest.raises(network.FetchError, match="busy"):
            network.resolve_before_deadline("example.com", 443, time.monotonic() + 1)
    finally:
        release.set()
        # Wait for the four submitted resolvers to finish, keeping later tests independent.
        for _ in range(4):
            assert network._DNS_SLOTS.acquire(timeout=1)
            futures.append(True)
        for _ in futures:
            network._DNS_SLOTS.release()


def test_expired_socket_is_closed_before_request(monkeypatch):
    sock = Mock()
    connection = network.PinnedHTTP("example.com", "8.8.8.8", 443, False)
    connection._fetch_expired = threading.Event()
    connection._fetch_deadline = time.monotonic() + 1

    def connect(*_):
        connection._fetch_expired.set()
        return sock

    monkeypatch.setattr(socket, "create_connection", connect)
    with pytest.raises(network.FetchError, match="deadline"):
        connection.connect()
    sock.shutdown.assert_called_once()
    sock.close.assert_called_once()
    connection.abort()
    empty = network.PinnedHTTP("example.com", "8.8.8.8", 443, False)
    empty.abort()  # DNS/connect expiry before there is any socket is also safe.


@pytest.mark.parametrize(
    "status,body,error",
    [
        (503, {}, ingest.ParserUnavailable),
        (408, {}, ingest.ParserUnavailable),
        (413, {}, ValueError),
        (200, {"text": None}, ValueError),
        (200, {}, ingest.ParserUnavailable),
    ],
)
def test_parser_protocol_distinguishes_transient_failures(monkeypatch, status, body, error):
    monkeypatch.setattr(settings(), "parser_socket", "/parser/inert.sock")
    transport = httpx.MockTransport(
        lambda request: httpx.Response(status, request=request, json=body)
    )
    monkeypatch.setattr(ingest.httpx, "HTTPTransport", lambda **_: transport)
    with pytest.raises(error):
        ingest.isolated_extract(b"source", "text/plain", "source.txt")
    monkeypatch.setattr(settings(), "max_upload_bytes", 2)
    with pytest.raises(ValueError, match="upload limit"):
        ingest.isolated_extract(b"source", "text/plain", "source.txt")


def test_conversation_ceiling_is_serialized(actors, monkeypatch):
    monkeypatch.setattr(settings(), "max_workspace_conversations", 2)

    def create(_):
        try:
            return api.create_conversation(
                ConversationInput(title="Concurrent"), actors["owner"]
            ).id
        except HTTPException as error:
            assert error.status_code == 429
            return None

    with ThreadPoolExecutor(max_workers=6) as pool:
        values = list(pool.map(create, range(6)))
    assert len([v for v in values if v]) == 2
    with session() as db:
        assert db.scalar(select(func.count()).select_from(Conversation)) == 2


def test_retained_source_cap_includes_deleted_and_allows_duplicate(client, monkeypatch):
    monkeypatch.setattr(settings(), "max_workspace_documents", 1)

    def upload(value):
        return client.post("/v1/documents", files={"file": ("tiny.md", value, "text/markdown")})

    first = upload(b"Unique source")
    assert first.status_code == 202
    assert upload(b"Unique source").json()["id"] == first.json()["id"]
    assert upload(b"Another unique source").status_code == 429
    with session() as db, db.begin():
        db.get(Document, first.json()["id"]).deleted = True
    assert upload(b"Third unique source").status_code == 429
    usage = client.get("/v1/usage").json()["metadata"]
    assert usage["retained_source_versions"] == usage["source_version_limit"] == 1


def test_research_ceiling_preserves_idempotent_replay(client, monkeypatch):
    monkeypatch.setattr(settings(), "max_workspace_runs", 1)
    conversation = client.post("/v1/conversations", json={"title": "Bounded research"}).json()
    payload = {"conversation_id": conversation["id"], "question": "How does fencing work?"}
    first = client.post("/v1/runs", json=payload, headers={"Idempotency-Key": "bounded-first"})
    assert first.status_code == 202
    replay = client.post("/v1/runs", json=payload, headers={"Idempotency-Key": "bounded-first"})
    assert replay.json()["id"] == first.json()["id"]
    assert (
        client.post(
            "/v1/runs", json=payload, headers={"Idempotency-Key": "bounded-next"}
        ).status_code
        == 429
    )
    assert client.get("/v1/usage").json()["metadata"]["retained_runs"] == 1


def test_member_and_pending_invitation_limits_are_enforced(client, monkeypatch):
    monkeypatch.setattr(settings(), "max_workspace_members", 3)
    invitations = []
    for i in range(3):
        response = client.post(
            "/v1/invitations", json={"email": f"bounded-{i}@example.com", "role": "editor"}
        )
        assert response.status_code == 201
        invitations.append(response.json()["link"].split("=", 1)[1])
    assert (
        client.post(
            "/v1/invitations", json={"email": "bounded-more@example.com", "role": "editor"}
        ).status_code
        == 429
    )
    payload = {"token": invitations[0], "password": "a long verified passphrase"}
    assert client.post("/v1/auth/redeem", json=payload).status_code == 204
    payload["token"] = invitations[1]
    assert client.post("/v1/auth/redeem", json=payload).status_code == 429
    usage = client.get("/v1/usage").json()["metadata"]
    assert usage["members"] == usage["member_limit"] == 3


def test_judge_quota_retry_links_attempts_and_persists_reusable_output(actors, monkeypatch):
    monkeypatch.setattr(live_eval, "EVAL_WORKSPACE", actors["owner"].workspace_id)
    with session() as db, db.begin():
        conversation = Conversation(
            workspace_id=actors["owner"].workspace_id, title="Judge retry test"
        )
        db.add(conversation)
        db.flush()
        conversation_id = conversation.id
    transport = FreeJudgeTransport(conversation_id)
    complete = Mock(side_effect=[providers.ProviderQuota(retry_after=1), '{"verdict":1}'])
    monkeypatch.setattr(providers, "complete", complete)
    pauses = []

    async def wait(seconds):
        pauses.append(seconds)
        transport.next_call = 0

    monkeypatch.setattr(live_eval.asyncio, "sleep", wait)
    request = httpx.Request(
        "POST",
        "https://api.groq.com/openai/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "Assess evidence"}]},
    )
    response = asyncio.run(transport.handle_async_request(request))
    assert response.status_code == 200 and complete.call_count == 2 and pauses
    with session() as db:
        row = db.get(live_eval.Run, response.json()["id"])
        assert db.get(live_eval.Run, row.parent_run_id).status == "quota_exhausted"
        assert row.answer == '{"verdict":1}' and row.provider == "groq" and not row.paid_consent
    response = asyncio.run(transport.handle_async_request(request))
    assert response.status_code == 200 and complete.call_count == 2 and transport.cache_hits == 1


def test_campaign_waits_for_daily_reset_and_never_changes_provider():
    now = datetime(2026, 10, 23, 23, 59, tzinfo=UTC)
    assert live_eval.quota_wait_seconds({"scope": "workspace"}, now) == 120
    assert live_eval.quota_wait_seconds({"scope": "deployment"}, now) == 120
    assert live_eval.quota_wait_seconds({"scope": "provider", "retry_after": 1}, now) == 60
    assert live_eval.quota_wait_seconds({"scope": "provider", "retry_after": 999999}, now) == 86400


def test_campaign_resumes_only_quota_failures(monkeypatch, tmp_path):
    (tmp_path / "results").mkdir()
    monkeypatch.setattr(live_eval, "ROOT", tmp_path)
    save = Mock()
    monkeypatch.setattr(live_eval, "save", save)
    monkeypatch.setattr(live_eval, "quota_wait_seconds", lambda *_: 0)
    run = Mock(
        side_effect=[
            {"status": "partial", "quota": {"scope": "workspace"}},
            {"status": "completed"},
        ]
    )
    monkeypatch.setattr(live_eval, "_run_live_locked", run)
    assert live_eval.run_live(until_complete=True)["status"] == "completed"
    assert run.call_count == 2 and save.call_args.args[0]["status"] == "quota_wait"
    run = Mock(return_value={"status": "partial", "stopped_reason": "InvalidJudgeSchema"})
    monkeypatch.setattr(live_eval, "_run_live_locked", run)
    assert live_eval.run_live(until_complete=True)["status"] == "partial"
    assert run.call_count == 1


def test_campaign_rejects_mixing_a_changed_model(monkeypatch, tmp_path):
    (tmp_path / "results").mkdir()
    monkeypatch.setattr(live_eval, "ROOT", tmp_path)
    monkeypatch.setattr(settings(), "groq_api_key", "local-test-key")
    monkeypatch.setattr(settings(), "groq_free_plan_confirmed", True)
    monkeypatch.setattr(live_eval, "validate_dataset", lambda: {"sha256": {"cases.json": "frozen"}})
    (tmp_path / "cases.json").write_text("[]")
    (tmp_path / "results/latest.json").write_text("{}")
    (tmp_path / "results/live-ragas.json").write_text(
        json.dumps({"provider": "groq", "model": "different-model"})
    )
    with pytest.raises(SystemExit, match="different provider/model"):
        live_eval._run_live_locked()


def test_orphan_reconciliation_preserves_references_and_other_tenants(client, actors, monkeypatch):
    workspace = actors["owner"].workspace_id
    other_key = actors["other"].workspace_id + "/inert-orphan"
    orphan_key = workspace + "/inert-orphan"
    storage.put(orphan_key, b"unused source", "text/plain")
    storage.put(other_key, b"other workspace", "text/plain")
    response = client.post(
        "/v1/documents", files={"file": ("kept.txt", b"A referenced source", "text/plain")}
    )
    with session() as db:
        referenced_key = db.get(Document, response.json()["id"]).object_key
    try:
        assert admin.reconcile_storage(workspace)["unreferenced_objects"] == []
        now = time.time()
        monkeypatch.setattr(admin.time, "time", lambda: now + 2 * 86400)
        report = admin.reconcile_storage(workspace)
        assert [item["key"] for item in report["unreferenced_objects"]] == [orphan_key]
        assert storage.get(orphan_key) == b"unused source"
        admin.reconcile_storage(workspace, apply=True)
        assert storage.get(referenced_key) == b"A referenced source"
        assert storage.get(other_key) == b"other workspace"
        assert admin.reconcile_storage(workspace)["unreferenced_objects"] == []
        with pytest.raises(ValueError, match="Specify"):
            admin.reconcile_storage(None, apply=True)
        with pytest.raises(ValueError, match="does not exist"):
            admin.reconcile_storage("missing-workspace", apply=True)
    finally:
        storage.remove(orphan_key)
        storage.remove(other_key)


def test_real_networkless_parser_service(monkeypatch):
    monkeypatch.setattr(settings(), "parser_socket", "/parser/parse.sock")
    assert (
        ingest.isolated_extract(b"A technical source.", "text/plain", "source.txt")
        == "A technical source."
    )
    with pytest.raises(ValueError, match="UTF-8"):
        ingest.isolated_extract(b"\xff", "text/plain", "source.txt")
    monkeypatch.setattr(settings(), "parser_socket", "/parser/missing.sock")
    with pytest.raises(ingest.ParserUnavailable, match="unavailable"):
        ingest.isolated_extract(b"source", "text/plain", "source.txt")


def test_parser_overload_retries_without_discarding_source(client, monkeypatch):
    response = client.post(
        "/v1/documents", files={"file": ("retry.txt", b"Valid technical source.", "text/plain")}
    )
    assert response.status_code == 202
    doc_id = response.json()["id"]
    job = claim()
    with monkeypatch.context() as context:
        context.setattr(
            worker, "isolated_extract", Mock(side_effect=ingest.ParserUnavailable("busy"))
        )
        worker.process(job)
    with session() as db, db.begin():
        current = db.get(Job, job.id)
        assert current.status == "pending" and db.get(Document, doc_id).status == "pending"
        assert db.get(Document, doc_id).object_key
        current.available_at = 0
    retry = claim()
    assert retry.id == job.id and retry.attempt == 2
    worker.process(retry)
    with session() as db:
        assert db.get(Document, doc_id).status == "ready"


def test_judge_cache_binds_actual_prompt_and_model(monkeypatch):
    payload = {"messages": [{"role": "user", "content": "Assess this evidence"}]}
    first = FreeJudgeTransport.cache_key(payload)
    assert first == FreeJudgeTransport.cache_key({**payload, "sdk_ignored": "value"})
    assert first != FreeJudgeTransport.cache_key(
        {"messages": [{"role": "user", "content": "Other evidence"}]}
    )
    monkeypatch.setattr(settings(), "groq_model", "other-free-model")
    assert first != FreeJudgeTransport.cache_key(payload)


@pytest.mark.parametrize("answer", ["not JSON", "[]", '{"verdict":1}'])
def test_judge_cache_requires_marked_object_output(make_run, actors, monkeypatch, answer):
    monkeypatch.setattr(live_eval, "EVAL_WORKSPACE", actors["owner"].workspace_id)
    run = make_run(provider="groq", question="Ragas judge request")
    with session() as db, db.begin():
        row = db.get(live_eval.Run, run.id)
        row.request_hash, row.status, row.answer = "inert-cache-key", "completed", answer
    transport = FreeJudgeTransport(run.conversation_id)
    assert transport.cached("inert-cache-key") is None
    with session() as db, db.begin():
        db.get(live_eval.Run, run.id).diagnostics = {"judge_cache_version": 1}
    expected = (run.id, answer) if answer.startswith("{") else None
    assert transport.cached("inert-cache-key") == expected


@pytest.mark.parametrize("max_attempts", [1, 3])
def test_interrupted_judge_cannot_run_research_or_publish_stale_cache(
    actors, monkeypatch, max_attempts
):
    monkeypatch.setattr(live_eval, "EVAL_WORKSPACE", actors["owner"].workspace_id)
    monkeypatch.setattr(settings(), "max_attempts", max_attempts)
    with session() as db, db.begin():
        conversation = Conversation(workspace_id=actors["owner"].workspace_id, title="Judge crash")
        db.add(conversation)
        db.flush()
        conversation_id = conversation.id
    graph = Mock(side_effect=AssertionError("Judge must never run the research graph"))
    monkeypatch.setattr(worker.agent, "execute_run", graph)
    seen = []

    def interrupted(job, *_args, **_kwargs):
        assert job.kind == "evaluation_judge"
        providers.reserve(job)
        with session() as db, db.begin():
            db.get(Job, job.id).lease_until = time.time() - 1
        recovered = claim()
        if recovered:
            assert recovered.id == job.id and recovered.fence != job.fence
            worker.process(recovered)
        seen.append(job)
        return '{"verdict":1}'

    monkeypatch.setattr(providers, "complete", interrupted)
    transport = FreeJudgeTransport(conversation_id)
    payload = {"messages": [{"role": "user", "content": "Judge inert evidence"}]}
    key = transport.cache_key(payload)
    request = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    response = transport._generate(request, payload, key)
    assert response.status_code == 503 and len(seen) == 1
    graph.assert_not_called()
    assert transport.cached(key) is None
    with session() as db:
        row = db.get(live_eval.Run, seen[0].target_id)
        assert row.status == "failed" and not row.reserved_tokens
        assert row.billed_tokens == providers.RESERVATION
        assert not row.answer and not row.diagnostics.get("judge_cache_version")
        assert db.get(Job, seen[0].id).status == "dead"


def test_judge_reuses_completed_request_without_call_or_wait(monkeypatch):
    transport = FreeJudgeTransport("inert-conversation")
    monkeypatch.setattr(transport, "cached", lambda _: ("cached-run", '{"verdict":1}'))
    generate = Mock(side_effect=AssertionError("Must not call provider"))
    monkeypatch.setattr(transport, "_generate", generate)
    request = httpx.Request(
        "POST",
        "https://api.groq.com/openai/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "Assess"}]},
    )
    response = asyncio.run(transport.handle_async_request(request))
    assert response.status_code == 200 and response.json()["id"] == "cached-run"
    assert json.loads(response.json()["choices"][0]["message"]["content"])["verdict"] == 1
    assert transport.cache_hits == 1 and transport.requests == 0


def test_judge_stops_at_local_budget_without_retry(monkeypatch):
    transport = FreeJudgeTransport("inert-conversation")
    monkeypatch.setattr(transport, "cached", lambda _: None)
    generate = Mock(
        side_effect=lambda request, *_: httpx.Response(
            429,
            request=request,
            json={"error": {"scope": "workspace", "retry_after": 3600, "run_id": "quota-run"}},
        )
    )
    monkeypatch.setattr(transport, "_generate", generate)
    request = httpx.Request(
        "POST", "https://api.groq.com/openai/v1/chat/completions", json={"messages": []}
    )
    assert asyncio.run(transport.handle_async_request(request)).status_code == 429
    assert generate.call_count == 1 and transport.last_quota["scope"] == "workspace"
