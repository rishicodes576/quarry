import json
import socket
import time
from unittest.mock import Mock

import httpx
import pytest
from fastapi import HTTPException

from quarry import network, providers, tools
from quarry.config import Settings, settings
from quarry.db import Job, LoginSession, Run, session
from quarry.queue import Cancelled, Heartbeat, check_run, claim
from quarry.security import COOKIE, digest, rate_limit
from quarry.worker import process
from tests.conftest import finish_document


def fake_connection(monkeypatch, status=200, headers=None, body=b"Public source", error=None):
    monkeypatch.setattr(network, "public_addresses", lambda *_: ["8.8.8.8"])
    response = Mock(status=status)
    values = {"Content-Type": "text/plain", **(headers or {})}
    response.getheader.side_effect = lambda name, default=None: values.get(name, default)
    response.read.return_value = body
    connection = Mock()
    connection.getresponse.return_value = response
    if error:
        connection.request.side_effect = error
    monkeypatch.setattr(network, "PinnedHTTP", Mock(return_value=connection))
    return connection


def test_public_fetch_success_and_socket_dns_failures(monkeypatch):
    real_addresses = network.public_addresses
    connection = fake_connection(monkeypatch)
    assert network.fetch_public("https://public.example/a path")[0] == b"Public source"
    assert "%20" in connection.request.call_args.args[1]
    monkeypatch.setattr(socket, "getaddrinfo", Mock(side_effect=OSError()))
    with pytest.raises(network.FetchError):
        real_addresses("missing.example", 443)


@pytest.mark.parametrize(
    "status,headers,body,error",
    [
        (301, {}, b"", None),
        (503, {}, b"", None),
        (200, {"Content-Length": "1000"}, b"", None),
        (200, {}, b"x" * 21, None),
        (200, {"Content-Length": "invalid"}, b"", None),
        (200, {}, b"", OSError()),
        (302, {"Location": "https://public.example/repeat"}, b"", None),
    ],
)
def test_fetch_failures_are_bounded(monkeypatch, status, headers, body, error):
    fake_connection(monkeypatch, status, headers, body, error)
    with pytest.raises(network.FetchError):
        network.fetch_public("https://public.example", max_bytes=20)


def test_tls_pinning_keeps_original_server_name(monkeypatch):
    sock = Mock()
    monkeypatch.setattr(socket, "create_connection", Mock(return_value=sock))
    context = Mock()
    monkeypatch.setattr(network.ssl, "create_default_context", Mock(return_value=context))
    connection = network.PinnedHTTP("example.com", "8.8.8.8", 443, True)
    connection.connect()
    context.wrap_socket.assert_called_once_with(sock, server_hostname="example.com")


def test_tool_policies_and_external_response_parsing(monkeypatch):
    assert tools.execute("calculate", "3+4", False)[0]["text"].endswith("7")
    with pytest.raises(ValueError):
        tools.execute("wikipedia", "x", False)
    monkeypatch.setattr(
        tools,
        "fetch_public",
        lambda *_: (
            b"<h1>Design</h1><p>Safe source.</p>",
            "text/html",
            "https://example.com/design",
        ),
    )
    assert (
        tools.execute("fetch_url", "https://example.com", True)[0]["text"] == "Design\nSafe source."
    )
    value = {
        "query": {
            "pages": {
                "1": {
                    "title": "Topic",
                    "extract": "A public summary",
                    "fullurl": "https://en.wikipedia.org/wiki/Topic",
                }
            }
        }
    }
    monkeypatch.setattr(
        tools, "fetch_public", lambda *_: (json.dumps(value).encode(), "application/json", "")
    )
    assert tools.execute("wikipedia", "Topic", True)[0]["kind"] == "wikipedia"

    class SearchClient:
        def __init__(self, **_):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def get(self, *_, **__):
            return httpx.Response(
                200,
                request=httpx.Request("GET", "http://search"),
                json={
                    "results": [
                        {"url": "file:///private", "title": "Rejected"},
                        {"url": "https://example.com", "title": "Valid", "content": "Snippet"},
                    ]
                },
            )

    monkeypatch.setattr(tools.httpx, "Client", SearchClient)
    assert len(tools.execute("web_search", "query", True)) == 1
    monkeypatch.setattr(settings(), "searxng_url", "")
    with pytest.raises(network.FetchError):
        tools.execute("web_search", "query", True)
    with pytest.raises(ValueError):
        tools.execute("shell", "command", True)


@pytest.mark.parametrize(
    "changes",
    [
        {"embedding_mode": "lexical"},
        {"cookie_secure": False},
        {"session_secret": "development-" + "x" * 50},
        {"qdrant_url": ""},
        {"app_origin": "http://example.com"},
    ],
)
def test_production_configuration_fails_closed(changes):
    defaults = {
        "env": "production",
        "demo_seed": False,
        "cookie_secure": True,
        "session_secret": "a" * 64,
        "qdrant_url": "https://vectors.example",
        "app_origin": "https://app.example",
        "signup_mode": "invite",
        "proxy_secret": "test" * 16,
        "smtp_host": "",
        "qdrant_api_key": "test" * 16,
        "s3_secret_key": "test" * 16,
    }
    with pytest.raises(ValueError):
        Settings(**{**defaults, **changes})


def test_valid_production_configuration():
    assert (
        Settings(
            env="production",
            demo_seed=False,
            cookie_secure=True,
            session_secret="a" * 64,
            app_origin="https://app.example",
            signup_mode="invite",
            proxy_secret="test" * 16,
            smtp_host="",
            qdrant_api_key="test" * 16,
            s3_secret_key="test" * 16,
        ).env
        == "production"
    )


def test_shared_rate_limits_and_expired_sessions(client):
    rate_limit("one-operation", 1)
    with pytest.raises(HTTPException) as error:
        rate_limit("one-operation", 1)
    assert error.value.status_code == 429
    with session() as db, db.begin():
        token = client.cookies.get(COOKIE)
        db.get(LoginSession, digest(token)).expires_at = time.time() - 1
    assert client.get("/v1/auth/me").status_code == 401


@pytest.mark.parametrize(
    "status,body,expected",
    [
        (401, {}, providers.ProviderFailure),
        (200, {"choices": [{"message": {"content": ""}}]}, providers.ProviderFailure),
        (200, {"choices": []}, providers.ProviderFailure),
    ],
)
def test_provider_response_failures_never_select_an_alternative(
    make_run, monkeypatch, status, body, expected
):
    monkeypatch.setattr(settings(), "groq_api_key", "gsk_test_key")
    monkeypatch.setattr(settings(), "groq_free_plan_confirmed", True)
    make_run("groq")
    job = claim()
    with pytest.raises(expected):
        providers.complete(
            job,
            [{"role": "user", "content": "test"}],
            transport=httpx.MockTransport(lambda _: httpx.Response(status, json=body)),
        )
    with session() as db:
        assert db.get(Run, job.target_id).reserved_tokens == 0


def test_provider_timeouts_and_call_limits(make_run, monkeypatch):
    monkeypatch.setattr(settings(), "groq_api_key", "gsk_test_key")
    monkeypatch.setattr(settings(), "groq_free_plan_confirmed", True)
    make_run("groq")
    job = claim()

    def timeout(request):
        raise httpx.ReadTimeout("simulated", request=request)

    with pytest.raises(providers.ProviderFailure):
        providers.complete(
            job, [{"role": "user", "content": "test"}], transport=httpx.MockTransport(timeout)
        )
    with session() as db, db.begin():
        row = db.get(Run, job.target_id)
        assert row.diagnostics["usage_unknown"]
        row.model_calls = settings().max_model_calls
    with pytest.raises(providers.ProviderFailure):
        providers.reserve(job)
    with pytest.raises(providers.ProviderFailure):
        providers.complete(
            job, [{"role": "user", "content": "x" * 15000}], transport=httpx.MockTransport(timeout)
        )


def test_worker_retry_exhaustion_and_cancel_time_limit(make_run, monkeypatch):
    run = make_run()
    job = claim()
    with session() as db, db.begin():
        db.get(Job, job.id).attempt = settings().max_attempts
        db.get(Job, job.id).lease_until = time.time() - 1
    assert claim() is None
    with session() as db:
        assert db.get(Run, run.id).status == "failed"
    other = make_run()
    current = claim()
    with session() as db, db.begin():
        db.get(Run, other.id).started_at = time.time() - 1000
    with pytest.raises(TimeoutError):
        check_run(current)
    with session() as db, db.begin():
        db.get(Run, other.id).cancel_requested = True
    with pytest.raises(Cancelled):
        check_run(current)


def test_heartbeat_extends_a_valid_lease(make_run, monkeypatch):
    monkeypatch.setattr(settings(), "lease_seconds", 3)
    make_run()
    job = claim()
    before = job.lease_until
    with Heartbeat(job):
        time.sleep(1.1)
    with session() as db:
        assert db.get(Job, job.id).lease_until > before


def test_generated_answer_branch_and_rejection_of_invalid_citations(client, monkeypatch):
    from tests.test_application import conversation, submission

    finish_document(client)
    monkeypatch.setattr(settings(), "groq_api_key", "gsk_test_key")
    monkeypatch.setattr(settings(), "groq_free_plan_confirmed", True)
    replies = iter(['{"tools":[],"summary":"Use evidence"}', "Unsupported statement [E999]"])
    monkeypatch.setattr(providers, "complete", lambda *_a, **_kw: next(replies))
    result = submission(client, conversation(client), provider="groq").json()
    process(claim())
    value = client.get("/v1/runs/" + result["id"]).json()
    assert value["status"] == "completed" and "Extractive mode" in value["answer"]
    assert value["diagnostics"]["citations"]["generation_rejected"]


def test_schema_validation_members_and_backpressure(client, monkeypatch):
    from tests.test_application import conversation, submission

    assert (
        client.post(
            "/v1/members",
            json={
                "email": "editor@example.com",
                "password": "a-long-new-password",
                "role": "editor",
            },
        ).status_code
        == 201
    )
    assert (
        client.post(
            "/v1/members",
            json={
                "email": "editor@example.com",
                "password": "a-long-new-password",
                "role": "viewer",
            },
        ).status_code
        == 409
    )
    cid = conversation(client)
    assert submission(client, cid, key="bad").status_code == 422
    monkeypatch.setattr(settings(), "max_pending_jobs", 0)
    assert submission(client, cid).status_code == 429
    assert (
        client.post(
            "/v1/documents", files={"file": ("new.txt", b"original data", "text/plain")}
        ).status_code
        == 429
    )


def test_url_import_and_invalid_url(client, monkeypatch):
    import quarry.api as api_module

    monkeypatch.setattr(
        api_module,
        "fetch_public",
        lambda *_: (
            b"Original imported public evidence.",
            "text/plain",
            "https://example.com/note",
        ),
    )
    assert (
        client.post("/v1/documents/url", json={"url": "https://example.com/note"}).status_code
        == 202
    )

    def denied(*_):
        raise network.FetchError("Private address denied")

    monkeypatch.setattr(api_module, "fetch_public", denied)
    assert (
        client.post("/v1/documents/url", json={"url": "https://example.com/private"}).status_code
        == 422
    )
