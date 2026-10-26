import io
import socket
from unittest.mock import Mock

import pytest
from pypdf import PdfWriter

from quarry.agent import excerpt_answer, validate_citations
from quarry.benchmark import percentile, score_sources, validate_dataset
from quarry.config import Settings
from quarry.ingest import chunk_text, extract
from quarry.network import FetchError, PinnedHTTP, fetch_public, public_addresses, validate_url
from quarry.providers import ProviderFailure, parse_plan, require_provider
from quarry.security import hash_password, verify_password
from quarry.tools import calculate


@pytest.mark.parametrize(
    "expression,expected",
    [
        ("2+2", "4"),
        ("250 * 0.05", "12.5"),
        ("-2**3", "-8"),
        ("(9+3)/4", "3"),
        ("5%2", "1"),
        ("+3.5", "3.5"),
    ],
)
def test_calculator(expression, expected):
    assert calculate(expression).endswith("= " + expected)


@pytest.mark.parametrize(
    "expression",
    [
        "__import__('os').system('id')",
        "open('/etc/passwd')",
        "2**999999",
        "1/0",
        "[x for x in range(5)]",
        "True+1",
        "'abc'",
        "2<<5",
        "9" * 200,
        "1e999",
        "10**12*10**12",
    ],
)
def test_calculator_rejects_unsafe_or_unbounded_inputs(expression):
    with pytest.raises((ValueError, SyntaxError)):
        calculate(expression)


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "http://user:secret@example.com",
        "http://localhost",
        "https://example.com:8443",
        "ftp://example.com",
        "http://example.com\nHost:x",
        "https://",
    ],
)
def test_url_validation(url):
    with pytest.raises(FetchError):
        validate_url(url)


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.0.0.1",
        "169.254.169.254",
        "::1",
        "::ffff:127.0.0.1",
        "192.168.1.2",
        "0.0.0.0",
    ],
)
def test_private_resolution_is_rejected(monkeypatch, address):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_a, **_kw: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443))],
    )
    with pytest.raises(FetchError):
        public_addresses("public.example", 443)


def test_mixed_public_private_dns_is_rejected(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_a, **_kw: [(2, 1, 6, "", (ip, 443)) for ip in ["8.8.8.8", "127.0.0.1"]],
    )
    with pytest.raises(FetchError):
        public_addresses("mixed.example", 443)


def test_ip_connection_is_pinned_without_resolving_hostname_again(monkeypatch):
    create = Mock(return_value=Mock())
    monkeypatch.setattr(socket, "create_connection", create)
    connection = PinnedHTTP("public.example", "8.8.8.8", 80, False)
    connection.connect()
    assert create.call_args.args[0] == ("8.8.8.8", 80)


def test_redirect_is_revalidated(monkeypatch):
    import quarry.network as network

    addresses = Mock(side_effect=[["8.8.8.8"], FetchError("private redirect")])
    monkeypatch.setattr(network, "public_addresses", addresses)
    response = Mock(status=302)
    response.getheader.return_value = "http://169.254.169.254/latest/meta-data"
    connection = Mock()
    connection.getresponse.return_value = response
    monkeypatch.setattr(network, "PinnedHTTP", Mock(return_value=connection))
    with pytest.raises(FetchError):
        fetch_public("https://public.example")
    assert addresses.call_count == 2


def test_parser_sanitizes_html_and_preserves_pdf_page_numbers():
    assert (
        extract(b"<h1>Title</h1><script>steal()</script><p>Evidence</p>", "text/html")
        == "Title\nEvidence"
    )
    chunks = chunk_text(
        "a" * 32,
        "# Design\n\nLease tokens protect writes.\f# Storage\n\nA private bucket stores source uploads.",
    )
    assert [c["page"] for c in chunks] == [1, 1, 2, 2]
    assert chunks == chunk_text(
        "a" * 32,
        "# Design\n\nLease tokens protect writes.\f# Storage\n\nA private bucket stores source uploads.",
    )


def test_scanned_empty_and_invalid_documents_are_rejected():
    writer = PdfWriter()
    writer.add_blank_page(200, 200)
    stream = io.BytesIO()
    writer.write(stream)
    with pytest.raises(ValueError, match="OCR"):
        extract(stream.getvalue(), "application/pdf")
    for body, media in [
        (b"", "text/plain"),
        (b"\xff", "text/plain"),
        (b"broken", "application/pdf"),
        (b"data", "application/octet-stream"),
    ]:
        with pytest.raises(ValueError):
            extract(body, media)


def test_password_hashing_and_validation():
    value = hash_password("a-long-password")
    assert value != hash_password("a-long-password")
    assert verify_password("a-long-password", value)
    assert not verify_password("wrong", value)
    assert not verify_password("x", "broken")


def test_configuration_rejects_sqlite_and_unsafe_production():
    with pytest.raises(ValueError):
        Settings(database_url="sqlite:///x")
    with pytest.raises(ValueError):
        Settings(env="production", demo_seed=True)


def test_plan_validation_and_paid_default():
    assert parse_plan(
        '{"tools":[{"name":"shell","argument":"rm"},{"name":"calculate","argument":"2+2"}]}'
    )["tools"] == [{"name": "calculate", "argument": "2+2"}]
    for value in ["bad JSON", "[]", '{"tools":1}']:
        with pytest.raises(ProviderFailure):
            parse_plan(value)
    with pytest.raises(ValueError):
        require_provider("openai", True)


def test_citation_validation_does_not_claim_truth():
    evidence = [{"citation": "E1", "title": "Note", "text": "A source."}]
    assert validate_citations("Supported reference [E1]", evidence)["references_valid"]
    assert not validate_citations("Unknown [E9]", evidence)["references_valid"]
    assert "not independently" in validate_citations("[E1]", evidence)["factual_support"]
    assert "could not find" in excerpt_answer([])


def test_metric_definitions_and_frozen_dataset():
    assert score_sources(["a", "a", "b"], ["a", "b"])["recall_at_5"] == 1
    assert score_sources(["x", "a"], ["a"])["mrr"] == 0.5
    assert score_sources([], ["a"])["recall_at_5"] == 0
    assert score_sources(["a"], []) is None
    assert percentile([1, 3], 0.5) == 2
    assert percentile([], 0.5) == 0
    assert validate_dataset()["case_count"] == 120


def test_rank_metrics_match_hand_calculation_and_deduplicate_sources():
    # Unique ranks are x,a,b. A duplicate passage must not occupy a source rank.
    result = score_sources(["x", "a", "a", "b"], ["a", "b"])
    assert result["recall_at_5"] == 1
    assert result["mrr"] == 0.5
    assert result["precision_at_5"] == pytest.approx(2 / 3)
    assert result["ndcg_at_5"] == pytest.approx(0.6934264036172708)
    # A relevant source beyond unique rank five must not contribute.
    assert score_sources(["x", "y", "z", "u", "v", "a"], ["a"])["ndcg_at_5"] == 0
    assert percentile([10, 20, 30, 40], 0.95) == pytest.approx(38.5)
