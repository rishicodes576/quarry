import asyncio
import json
import signal
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
from botocore.exceptions import ClientError
from fastapi import HTTPException, Request
from sqlalchemy import select

from quarry import (
    accounts,
    agent,
    api,
    model_assets,
    network,
    providers,
    retrieval,
    security,
    storage,
    worker,
)
from quarry.config import settings
from quarry.db import (
    AccountMail,
    Document,
    Job,
    LoginSession,
    Run,
    User,
    session,
    uid,
)
from quarry.queue import claim, fenced
from quarry.security import COOKIE, digest
from tests.conftest import finish_document


def token_link(client):
    return (
        client.post("/v1/invitations", json={"email": "edge@example.com"})
        .json()["link"]
        .split("=", 1)[1]
    )


def test_invitations_can_be_revoked_and_existing_accounts_cannot_be_recreated(client):
    token = token_link(client)
    values = client.get("/v1/invitations").json()
    assert any(row["id"] == digest(token) for row in values)
    assert client.delete("/v1/invitations/" + digest(token)).status_code == 204
    assert (
        client.post(
            "/v1/auth/redeem", json={"token": token, "password": "a secure replacement password"}
        ).status_code
        == 400
    )
    assert client.post("/v1/invitations", json={"email": "owner@example.com"}).status_code == 409


@pytest.mark.parametrize(
    "mode,purpose,disabled",
    [
        ("disabled", "invite", False),
        ("invite", "signup", False),
        ("public", "invalid", False),
        ("public", "reset", True),
    ],
)
def test_stale_or_disabled_account_links_fail_closed(
    client, actors, monkeypatch, mode, purpose, disabled
):
    monkeypatch.setattr(settings(), "signup_mode", mode)
    with session() as db, db.begin():
        db.get(User, actors["owner"].id).disabled = disabled
        raw, _ = accounts.issue(db, purpose, "owner@example.com", actors["owner"].workspace_id)
    assert (
        client.post(
            "/v1/auth/redeem", json={"token": raw, "password": "a secure replacement password"}
        ).status_code
        == 400
    )


def test_mfa_pending_expiry_and_common_passwords(client, actors):
    assert (
        client.post(
            "/v1/auth/mfa/confirm", json={"password": "a-long-test-password", "code": "123456"}
        ).status_code
        == 400
    )
    assert (
        client.post("/v1/auth/mfa/setup", json={"password": "a-long-test-password"}).status_code
        == 200
    )
    with session() as db, db.begin():
        db.get(User, actors["owner"].id).mfa_pending_until = 1
    assert (
        client.post(
            "/v1/auth/mfa/confirm", json={"password": "a-long-test-password", "code": "123456"}
        ).status_code
        == 400
    )
    with pytest.raises(HTTPException):
        security.validate_password("passwordpassword")


def test_mail_worker_does_not_send_expired_or_already_sent_payload(client, actors, monkeypatch):
    monkeypatch.setattr(settings(), "smtp_host", "mailpit")
    response = client.post("/v1/invitations", json={"email": "expired@example.com"})
    assert response.status_code == 201
    job = claim()
    with session() as db, db.begin():
        db.get(AccountMail, job.target_id).expires_at = 1
    smtp = Mock()
    monkeypatch.setattr(accounts.smtplib, "SMTP", smtp)
    worker.process(job)
    smtp.assert_not_called()


def test_session_cap_idle_timestamp_and_self_revocation(client, actors):
    with session() as db, db.begin():
        for i in range(10):
            db.add(
                LoginSession(
                    digest=digest(f"seed-session-{i}"),
                    user_id=actors["owner"].id,
                    created_at=time.time() - 100 + i,
                    last_seen_at=time.time() - 90,
                    expires_at=time.time() + 600,
                )
            )
    assert (
        client.post(
            "/v1/auth/login",
            json={"email": "owner@example.com", "password": "a-long-test-password"},
        ).status_code
        == 200
    )
    with session() as db, db.begin():
        rows = db.scalars(
            select(LoginSession).where(LoginSession.user_id == actors["owner"].id)
        ).all()
        assert len(rows) == 10
        row = db.get(LoginSession, digest(client.cookies.get(COOKIE)))
        row.last_seen_at = time.time() - 90
    assert client.get("/v1/auth/me").status_code == 200
    with session() as db:
        assert (
            db.get(LoginSession, digest(client.cookies.get(COOKIE))).last_seen_at > time.time() - 5
        )
    current = digest(client.cookies.get(COOKIE))
    assert client.delete("/v1/auth/sessions/" + current).status_code == 204
    assert client.get("/v1/auth/me").status_code == 401


def test_proxy_address_requires_authenticated_hop(monkeypatch):
    monkeypatch.setattr(settings(), "proxy_secret", "private-proxy-secret" * 3)

    def request(headers):
        return Request(
            {
                "type": "http",
                "headers": [(k.encode(), v.encode()) for k, v in headers.items()],
                "client": ("direct-peer", 123),
            }
        )

    assert (
        security.remote_address(
            request({"x-forwarded-for": "8.8.8.8", "x-quarry-client-ip": "8.8.8.8"})
        )
        == "direct-peer"
    )
    trusted = {
        "x-quarry-proxy-secret": settings().proxy_secret,
        "x-quarry-client-ip": "2001:db8::1",
    }
    assert security.remote_address(request(trusted)) == "2001:db8::1"
    assert (
        security.remote_address(request({**trusted, "x-quarry-client-ip": "invalid"}))
        == "direct-peer"
    )


def test_body_backpressure_rejects_before_buffering_and_recovers(client, monkeypatch):
    slots = threading.BoundedSemaphore(1)
    monkeypatch.setattr(api, "BODY_SLOTS", slots)
    slots.acquire()
    response = client.post("/v1/conversations", json={"title": "Capacity probe"})
    assert response.status_code == 503 and response.headers["retry-after"] == "1"
    assert client.get("/v1/auth/me").status_code == 200
    slots.release()
    assert client.post("/v1/conversations", json={"title": "Recovered capacity"}).status_code == 201


@pytest.mark.parametrize("email", ["demo@quarry.local", "viewer@quarry.local"])
def test_production_rejects_preexisting_demo_sessions_passwords_and_machine_keys(
    client, actors, monkeypatch, email
):
    with session() as db, db.begin():
        db.get(User, actors["owner"].id).email = email
    credential = client.post(
        "/v1/auth/keys", json={"password": "a-long-test-password", "label": "Development key"}
    ).json()["key"]
    assert client.get("/v1/auth/me").status_code == 200
    monkeypatch.setattr(settings(), "env", "production")
    assert client.get("/v1/auth/me").status_code == 401
    assert (
        client.get("/v1/documents", headers={"Authorization": "Bearer " + credential}).status_code
        == 401
    )
    assert (
        client.post(
            "/v1/auth/login", json={"email": email, "password": "a-long-test-password"}
        ).status_code
        == 401
    )
    monkeypatch.setattr(settings(), "env", "development")
    assert client.get("/v1/auth/me").status_code == 200


def test_machine_key_concurrent_requests_do_not_exhaust_nested_connection_pool(client):
    response = client.post(
        "/v1/auth/keys", json={"password": "a-long-test-password", "label": "Concurrency probe"}
    )
    headers = {"Authorization": "Bearer " + response.json()["key"]}
    with ThreadPoolExecutor(max_workers=15) as pool:
        results = list(
            pool.map(lambda _: client.get("/v1/documents", headers=headers).status_code, range(30))
        )
    assert results == [200] * 30


def test_concurrent_admissions_do_not_open_nested_rate_limiter_connections(client):
    conversation = client.post("/v1/conversations", json={"title": "Concurrent admission"}).json()

    def submit(_):
        return client.post(
            "/v1/runs",
            headers={"Idempotency-Key": uid()},
            json={"conversation_id": conversation["id"], "question": "How do fencing tokens work?"},
        ).status_code

    with ThreadPoolExecutor(max_workers=15) as pool:
        assert list(pool.map(submit, range(20))) == [202] * 20


def test_boundary_size_length_origin_and_error_redaction(client, monkeypatch):
    assert (
        client.post(
            "/v1/auth/login",
            content=b"",
            headers={"Content-Length": str(settings().max_upload_bytes + 64001)},
        ).status_code
        == 413
    )
    assert (
        client.post(
            "/v1/auth/login", content=b"", headers={"Content-Length": "invalid"}
        ).status_code
        == 400
    )
    monkeypatch.setattr(settings(), "max_upload_bytes", 1)
    response = client.post("/v1/auth/login", content=iter([b"x" * 65000]))
    assert response.status_code == 413
    monkeypatch.setattr(
        api.providers,
        "provider_status",
        Mock(side_effect=RuntimeError("private exception content")),
    )
    response = client.get("/v1/providers")
    assert response.status_code == 500 and "private exception content" not in response.text


def test_production_refuses_privileged_database_and_legacy_member_provisioning(client, monkeypatch):
    monkeypatch.setattr(settings(), "env", "production")
    assert client.get("/health/ready").status_code == 503
    assert (
        client.post(
            "/v1/members",
            json={"email": "member@example.com", "password": "a strong owner created password"},
        ).status_code
        == 404
    )


def test_upload_retry_and_continuation_contracts(client):
    assert (
        client.post("/v1/documents", files={"file": ("empty.txt", b"", "text/plain")}).status_code
        == 422
    )
    assert (
        client.post(
            "/v1/documents", files={"file": ("image.bin", b"binary", "image/jpeg")}
        ).status_code
        == 422
    )
    doc = finish_document(client)
    assert client.post(f"/v1/documents/{doc.id}/retry").status_code == 409
    first = client.post("/v1/conversations", json={"title": "One"}).json()
    second = client.post("/v1/conversations", json={"title": "Two"}).json()
    body = {"conversation_id": first["id"], "question": "How do leases work?"}
    assert (
        client.post("/v1/runs", headers={"Idempotency-Key": "short"}, json=body).status_code == 422
    )
    assert (
        client.post(
            "/v1/runs", headers={"Idempotency-Key": uid()}, json={**body, "provider": "groq"}
        ).status_code
        == 422
    )
    run = client.post("/v1/runs", headers={"Idempotency-Key": uid()}, json=body).json()
    assert (
        client.post(
            "/v1/runs",
            headers={"Idempotency-Key": uid()},
            json={**body, "conversation_id": second["id"], "parent_run_id": run["id"]},
        ).status_code
        == 422
    )
    assert client.get("/v1/runs?conversation_id=" + first["id"]).status_code == 200
    assert (
        client.get(f"/v1/runs/{run['id']}/stream", headers={"Last-Event-ID": "invalid"}).status_code
        == 422
    )
    assert client.get(f"/v1/runs/{run['id']}/export").status_code == 409
    worker.process(claim())
    assert client.post(f"/v1/runs/{run['id']}/cancel").status_code == 409


def test_dead_ingestion_and_orphan_recovery_are_visible(client):
    doc = client.post("/v1/documents", files={"file": ("dead.txt", b"source", "text/plain")}).json()
    with session() as db, db.begin():
        row = db.scalar(select(Job).where(Job.target_id == doc["id"]))
        row.attempt, row.status, row.lease_until = settings().max_attempts, "running", 1
    assert claim() is None
    with session() as db:
        assert db.get(Document, doc["id"]).status == "failed"
    assert client.post(f"/v1/documents/{doc['id']}/retry").status_code == 200


def test_ingestion_deletion_races_and_stale_publication_fail_closed(client, actors, monkeypatch):
    response = client.post(
        "/v1/documents", files={"file": ("race.txt", b"Leases prevent stale results", "text/plain")}
    )
    doc_id = response.json()["id"]
    job = claim()
    original = retrieval.index_chunks

    def delete_after_index(*args):
        original(*args)
        assert client.delete("/v1/documents/" + doc_id).status_code == 204

    monkeypatch.setattr(retrieval, "index_chunks", delete_after_index)
    worker.process(job)
    assert retrieval.search(actors["owner"].workspace_id, "leases")["hits"] == []
    worker.process(claim())


def test_worker_loses_lease_during_indexing_without_publishing(client, monkeypatch):
    response = client.post(
        "/v1/documents", files={"file": ("lease.txt", b"Leased source content", "text/plain")}
    )
    job = claim()
    original = retrieval.index_chunks

    def lose_lease(*args):
        original(*args)
        with session() as db, db.begin():
            db.get(Job, job.id).fence = uid()

    monkeypatch.setattr(retrieval, "index_chunks", lose_lease)
    worker.process(job)
    with session() as db:
        assert db.get(Document, response.json()["id"]).status == "indexing"


def test_worker_retries_transient_ingestion_errors_then_marks_dead(client, monkeypatch):
    response = client.post(
        "/v1/documents", files={"file": ("retry.txt", b"Retryable content", "text/plain")}
    )
    monkeypatch.setattr(
        retrieval, "index_chunks", Mock(side_effect=RuntimeError("private upstream error"))
    )
    for _ in range(settings().max_attempts):
        job = claim()
        assert job
        worker.process(job)
        with session() as db, db.begin():
            db.get(Job, job.id).available_at = 0
    with session() as db:
        row = db.get(Document, response.json()["id"])
        assert row.status == "failed" and "private" not in row.error
        assert db.get(Job, job.id).status == "dead"


def test_worker_loop_handles_dispatch_outage_and_graceful_stop(client, monkeypatch):
    client.post("/v1/documents", files={"file": ("loop.txt", b"Worker loop source", "text/plain")})
    handlers, calls = {}, []
    monkeypatch.setattr(
        worker.signal, "signal", lambda name, handler: handlers.__setitem__(name, handler)
    )

    def dispatch():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("temporary database failure")
        if len(calls) == 2:
            return None
        return claim()

    original = worker.process

    def process_and_stop(job):
        original(job)
        handlers[signal.SIGTERM](None, None)

    monkeypatch.setattr(worker, "claim", dispatch)
    monkeypatch.setattr(worker, "process", process_and_stop)
    worker.stop.clear()
    try:
        worker.main()
    finally:
        worker.stop.clear()
    assert len(calls) == 3


def test_generator_tools_and_cancel_at_publication_boundaries(client, make_run, monkeypatch):
    doc = finish_document(client)
    run = make_run(question="Calculate 12 * 9")
    worker.process(claim())
    assert "108" in client.get("/v1/runs/" + run.id).json()["answer"]
    run = make_run(allow_web=True, question="https://public.example/source")
    monkeypatch.setattr(
        agent.tools,
        "execute",
        lambda *_: [
            {
                "title": "Fetched source",
                "text": "Public source evidence",
                "kind": "web",
                "source_url": "https://public.example/source",
            }
        ],
    )
    worker.process(claim())
    assert len(client.get("/v1/runs/" + run.id).json()["evidence"]) > 0
    run = make_run()

    def cancel_before_publish(job):
        with session() as db, db.begin():
            db.get(Run, run.id).cancel_requested = True
        return {"answer": "unused", "evidence": [], "diagnostics": {}}

    monkeypatch.setattr(agent, "execute_run", cancel_before_publish)
    worker.process(claim())
    assert client.get("/v1/runs/" + run.id).json()["status"] == "cancelled"
    # A document deleted while queued never enters retrieval.
    response = client.post(
        "/v1/documents", files={"file": ("queued.txt", b"Queued deletion", "text/plain")}
    )
    client.delete("/v1/documents/" + response.json()["id"])
    worker.process(claim())
    assert client.get("/v1/documents/" + doc.id + "/passages").status_code == 200


def test_duplicate_model_reservations_and_oversized_envelopes_are_rejected(make_run, monkeypatch):
    monkeypatch.setattr(settings(), "max_daily_tokens", 100000)
    make_run()
    job = claim()
    providers.reserve(job)
    with pytest.raises(providers.ProviderFailure):
        providers.reserve(job)
    providers.settle(job, 0)
    with pytest.raises(providers.ProviderFailure):
        providers.complete(job, [{"role": "user", "content": "test"}])
    with session() as db, db.begin():
        db.get(Run, job.target_id).provider = "groq"
    monkeypatch.setattr(settings(), "groq_api_key", "gsk_test_key")
    monkeypatch.setattr(settings(), "groq_free_plan_confirmed", True)
    for messages in [
        [],
        [{"role": "tool", "content": "bad"}],
        [{"role": "user", "content": "x" * 14001}],
    ]:
        with pytest.raises(providers.ProviderFailure):
            providers.complete(job, messages)
    with pytest.raises(providers.ProviderQuota) as error:
        providers.complete(
            job,
            [{"role": "user", "content": "test"}],
            transport=httpx.MockTransport(
                lambda _: httpx.Response(429, headers={"Retry-After": "invalid"})
            ),
        )
    assert error.value.retry_after == 60


def test_local_model_cache_survives_hub_outage_and_dns_empty_answers_fail_closed(monkeypatch):
    monkeypatch.setattr(
        model_assets, "snapshot_download", Mock(side_effect=OSError("Hub unavailable"))
    )
    assert model_assets.prepare()["dense"]["revision"] == model_assets.MODELS["dense"]["revision"]
    monkeypatch.setattr(network.socket, "getaddrinfo", lambda *_args, **_kwargs: [])
    with pytest.raises(network.FetchError):
        network.public_addresses("empty.example", 443)


def test_storage_initialization_creates_only_missing_buckets(monkeypatch):
    name = "test-storage-" + uid()
    monkeypatch.setattr(settings(), "s3_bucket", name)
    storage.init_storage()
    storage.client().head_bucket(Bucket=name)
    storage.client().delete_bucket(Bucket=name)
    fake = Mock()
    fake.head_bucket.side_effect = ClientError(
        {"Error": {"Code": "403", "Message": "Denied"}}, "HeadBucket"
    )
    monkeypatch.setattr(storage, "client", lambda: fake)
    with pytest.raises(ClientError):
        storage.init_storage()
    fake.create_bucket.assert_not_called()


def test_sse_stops_for_disconnected_or_revoked_session(client, make_run, actors, monkeypatch):
    run = make_run()
    request = SimpleNamespace(
        headers={}, cookies={COOKIE: client.cookies.get(COOKIE)}, is_disconnected=None
    )

    async def disconnected():
        return True

    request.is_disconnected = disconnected
    response = asyncio.run(api.stream(run.id, request, 0, actors["owner"]))

    async def consume():
        return [part async for part in response.body_iterator]

    assert asyncio.run(consume()) == []

    async def connected():
        return False

    request.is_disconnected = connected
    monkeypatch.setattr(api, "current_user", Mock(side_effect=HTTPException(401, "Revoked")))
    response = asyncio.run(api.stream(run.id, request, 0, actors["owner"]))
    assert asyncio.run(consume()) == []


def test_checkpoint_cancellation_guards_put_and_pending_writes(make_run):
    run = make_run()
    job = claim()
    with fenced(job) as (db, _):
        db.get(Run, run.id).cancel_requested = True
    saver = agent.FencedPostgresSaver(Mock(), job)
    for operation in [saver.put, saver.put_writes]:
        with pytest.raises(Exception, match="cancelled"):
            operation()


def test_durable_operational_metrics_cover_queue_failures_and_phase_latency(client, make_run):
    run = make_run()
    assert "quarry_queue_oldest_seconds" in client.get("/metrics").text
    worker.process(claim())
    with session() as db, db.begin():
        row = db.get(Run, run.id)
        row.provider, row.status = "groq", "quota_exhausted"
    metrics = client.get("/metrics").text
    assert 'quarry_provider_failures_5m{provider="groq",status="quota_exhausted"} 1.0' in metrics
    assert 'quarry_phase_mean_seconds_5m{stage="retrieve"}' in metrics


def test_older_version_finishing_after_newer_version_never_replaces_it(client):
    first = client.post(
        "/v1/documents", files={"file": ("version.md", b"Version one original", "text/markdown")}
    ).json()
    old_job = claim()
    second = client.post(
        "/v1/documents", files={"file": ("version.md", b"Version two replacement", "text/markdown")}
    ).json()
    new_job = claim()
    worker.process(new_job)
    worker.process(old_job)
    with session() as db:
        assert db.get(Document, first["id"]).status == "superseded"
        assert db.get(Document, second["id"]).status == "ready"
    worker.process(claim())


def test_calculation_result_is_included_when_document_candidates_fill_the_context(client, make_run):
    for i in range(5):
        finish_document(
            client,
            f"Original engineering note {i}. Worker leases prevent stale writes to a queue.",
            filename=f"calculation-context-{i}.md",
        )
    run = make_run(question="calculate 12 * 9")
    worker.process(claim())
    result = client.get("/v1/runs/" + run.id).json()
    assert len(result["evidence"]) == 6
    assert "12 * 9 = 108" in result["answer"]
    assert "[E6]" in result["answer"]


@pytest.mark.parametrize(
    "error_body",
    [
        {"error": {"code": "json_validate_failed", "message": "private upstream material"}},
        {"error": "private upstream material"},
        "invalid upstream JSON",
    ],
)
def test_provider_validation_errors_are_bounded_redacted_and_keep_the_same_provider(
    make_run, monkeypatch, error_body
):
    monkeypatch.setattr(settings(), "groq_api_key", "gsk_test_key")
    monkeypatch.setattr(settings(), "groq_free_plan_confirmed", True)
    make_run(provider="groq")
    job = claim()
    requests = []

    def reply(request):
        requests.append(json.loads(request.content))
        return httpx.Response(400, json=error_body)

    with pytest.raises(providers.ProviderFailure) as error:
        providers.complete(
            job,
            [{"role": "user", "content": "Return JSON with an answer."}],
            json_mode=True,
            transport=httpx.MockTransport(reply),
        )
    assert "private upstream material" not in str(error.value)
    assert requests[0]["max_completion_tokens"] == 2000
    assert requests[0]["reasoning_format"] == "hidden"
    with session() as db:
        row = db.get(Run, job.target_id)
        assert row.provider == "groq" and row.reserved_tokens == 0
