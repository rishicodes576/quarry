import io
import json
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
from sqlalchemy import select

from quarry import ingest, storage
from quarry.api import app
from quarry.config import settings
from quarry.db import ApiKey, Document, User, session
from quarry.queue import claim
from quarry.security import digest
from quarry.worker import process


def key(client, scope="read"):
    response = client.post(
        "/v1/auth/keys",
        json={"password": "a-long-test-password", "label": "Test server", "scope": scope},
    )
    assert response.status_code == 201, response.text
    return response.json()["key"]


def test_machine_keys_scopes_cannot_administer_or_fall_back_to_browser_session(client, actors):
    secret = key(client)
    headers = {"Authorization": "Bearer " + secret}
    assert client.get("/v1/documents", headers=headers).status_code == 200
    assert (
        client.post("/v1/conversations", headers=headers, json={"title": "Denied"}).status_code
        == 403
    )
    assert client.get("/v1/auth/security", headers=headers).status_code == 403
    assert client.get("/v1/members", headers=headers).status_code == 403
    assert (
        client.get("/v1/documents", headers={"Authorization": "Bearer invalid"}).status_code == 401
    )
    assert secret not in client.get("/v1/auth/keys").text
    with session() as db:
        assert db.get(User, actors["owner"].id).role == "owner"
        assert db.get(ApiKey, digest(secret)).scope == "read"
    assert client.delete("/v1/auth/keys/" + digest(secret)).status_code == 204
    assert client.get("/v1/documents", headers=headers).status_code == 401


def test_machine_key_write_expiry_and_cross_workspace_filter(client, actors):
    secret = key(client, "write")
    headers = {"Authorization": "Bearer " + secret}
    assert (
        client.post(
            "/v1/conversations", headers=headers, json={"title": "Server request"}
        ).status_code
        == 201
    )
    with TestClient(app) as other:
        assert (
            other.post(
                "/v1/auth/login",
                json={"email": "other@example.com", "password": "a-long-test-password"},
            ).status_code
            == 200
        )
        doc = other.post(
            "/v1/documents",
            files={"file": ("private.txt", b"A secret other workspace source", "text/plain")},
        ).json()
    assert client.get(f"/v1/documents/{doc['id']}/source", headers=headers).status_code == 404
    with session() as db, db.begin():
        db.get(ApiKey, digest(secret)).expires_at = time.time() - 1
    assert client.get("/v1/documents", headers=headers).status_code == 401


def test_password_rotation_revokes_machine_keys(client):
    secret = key(client)
    assert (
        client.post(
            "/v1/auth/password",
            json={
                "password": "a-long-test-password",
                "new_password": "a replacement long passphrase",
            },
        ).status_code
        == 204
    )
    assert (
        client.get("/v1/documents", headers={"Authorization": "Bearer " + secret}).status_code
        == 401
    )


def test_concurrent_storage_admission_is_atomic_and_rejected_object_is_removed(
    client, actors, monkeypatch
):
    monkeypatch.setattr(settings(), "max_workspace_storage_bytes", 7)
    token = client.cookies.get("quarry_session")

    def upload(number):
        with TestClient(app) as peer:
            peer.cookies.set("quarry_session", token)
            return peer.post(
                "/v1/documents",
                files={
                    "file": (
                        f"{number}.txt",
                        ("abcde" if number else "fghij").encode(),
                        "text/plain",
                    )
                },
            ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(upload, range(2))) == [202, 413]
    with session() as db:
        docs = db.scalars(
            select(Document).where(Document.workspace_id == actors["owner"].workspace_id)
        ).all()
        assert len(docs) == 1 and docs[0].byte_size == 5
    values = storage.client().list_objects_v2(
        Bucket=settings().s3_bucket, Prefix=actors["owner"].workspace_id + "/"
    )
    assert values["KeyCount"] == 1


def test_shared_storage_allowance_spans_workspaces(client, monkeypatch):
    monkeypatch.setattr(settings(), "max_global_storage_bytes", 7)
    assert (
        client.post("/v1/documents", files={"file": ("a.txt", b"abcde", "text/plain")}).status_code
        == 202
    )
    with TestClient(app) as other:
        other.post(
            "/v1/auth/login",
            json={"email": "other@example.com", "password": "a-long-test-password"},
        )
        response = other.post("/v1/documents", files={"file": ("b.txt", b"fghij", "text/plain")})
        assert response.status_code == 503 and response.headers["Retry-After"] == "300"


def test_storage_allowance_is_released_only_after_cleanup(client, monkeypatch):
    monkeypatch.setattr(settings(), "max_workspace_storage_bytes", 7)
    doc = client.post("/v1/documents", files={"file": ("a.txt", b"abcde", "text/plain")}).json()
    process(claim())
    assert client.delete("/v1/documents/" + doc["id"]).status_code == 204
    assert (
        client.post("/v1/documents", files={"file": ("b.txt", b"fghij", "text/plain")}).status_code
        == 413
    )
    process(claim())
    assert (
        client.post("/v1/documents", files={"file": ("b.txt", b"fghij", "text/plain")}).status_code
        == 202
    )


def pdf(text=None, encrypted=False, pages=1):
    writer = PdfWriter()
    for _ in range(pages):
        page = writer.add_blank_page(width=612, height=792)
        if text:
            font = DictionaryObject(
                {
                    NameObject("/Type"): NameObject("/Font"),
                    NameObject("/Subtype"): NameObject("/Type1"),
                    NameObject("/BaseFont"): NameObject("/Helvetica"),
                }
            )
            page[NameObject("/Resources")] = DictionaryObject(
                {
                    NameObject("/Font"): DictionaryObject(
                        {NameObject("/F1"): writer._add_object(font)}
                    )
                }
            )
            stream = DecodedStreamObject()
            stream.set_data(f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode())
            page[NameObject("/Contents")] = writer._add_object(stream)
    if encrypted:
        writer.encrypt("private")
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def test_actual_isolated_pdf_parser_and_provenance():
    body = pdf(
        "Quarry workers use leases and fencing tokens for recoverable background processing."
    )
    text = ingest.isolated_extract(body, "application/pdf", "source.pdf")
    assert "fencing tokens" in text
    chunks = ingest.chunk_text("source", "# One\n\n" + "word " * 300 + "\f# Two\n\nSecond page.")
    assert len(chunks) >= 4 and chunks[-1]["page"] == 2 and chunks[-1]["section"] == "Two"


@pytest.mark.parametrize(
    "body,message",
    [(pdf(encrypted=True), "Password-protected"), (pdf(pages=251), "250-page"), (pdf(), "OCR")],
)
def test_pdf_limits_are_explicit(body, message):
    with pytest.raises(ValueError, match=message):
        ingest.extract(body, "application/pdf", "source.pdf")


def test_isolated_parser_timeout_crash_and_redacted_error(monkeypatch):
    monkeypatch.setattr(
        ingest.subprocess, "run", Mock(side_effect=subprocess.TimeoutExpired("parser", 25))
    )
    with pytest.raises(ValueError, match="25 seconds"):
        ingest.isolated_extract(b"x", "text/plain", "source.txt")
    monkeypatch.setattr(ingest.subprocess, "run", Mock(return_value=Mock(returncode=-9)))
    with pytest.raises(ValueError, match="resource limit"):
        ingest.isolated_extract(b"x", "text/plain", "source.txt")
    monkeypatch.setattr(
        ingest.subprocess,
        "run",
        Mock(
            return_value=Mock(
                returncode=0, stdout=json.dumps({"error": "No readable text"}).encode()
            )
        ),
    )
    with pytest.raises(ValueError, match="No readable text"):
        ingest.isolated_extract(b"x", "text/plain", "source.txt")


@pytest.mark.parametrize(
    "body,media", [(b"\xff", "text/plain"), (b"", "text/plain"), (b"binary", "image/jpeg")]
)
def test_invalid_encodings_and_formats(body, media):
    with pytest.raises(ValueError):
        ingest.extract(body, media)


def test_parser_upload_and_extracted_character_caps(monkeypatch):
    monkeypatch.setattr(settings(), "max_upload_bytes", 3)
    with pytest.raises(ValueError, match="upload limit"):
        ingest.extract(b"abcd", "text/plain")
    monkeypatch.setattr(settings(), "max_document_chars", 1)
    with pytest.raises(ValueError, match="characters"):
        ingest.extract(b"abc", "text/plain")
