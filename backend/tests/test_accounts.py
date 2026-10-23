import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock

import pyotp
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from quarry import accounts
from quarry.api import app
from quarry.config import settings
from quarry.db import AccountMail, AccountToken, LoginSession, User, session
from quarry.queue import claim
from quarry.security import COOKIE, cipher, digest, verify_password
from quarry.worker import process

PASSWORD = "an unusually long new passphrase"


def invitation(client, email="new@example.com", role="viewer"):
    response = client.post("/v1/invitations", json={"email": email, "role": role})
    assert response.status_code == 201, response.text
    return response.json()["link"].split("=", 1)[1]


def test_invite_signup_atomic_single_use_and_server_roles(client, actors):
    token = invitation(client)
    with session() as db:
        assert db.get(AccountToken, digest(token)).role == "viewer"
    response = client.post(
        "/v1/auth/redeem", json={"token": token, "password": PASSWORD, "role": "owner"}
    )
    assert response.status_code == 422

    def redeem(_):
        with TestClient(app) as peer:
            return peer.post(
                "/v1/auth/redeem", json={"token": token, "password": PASSWORD}
            ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(redeem, range(2))) == [204, 400]
    with TestClient(app) as peer:
        response = peer.post(
            "/v1/auth/login", json={"email": "new@example.com", "password": PASSWORD}
        )
        assert response.status_code == 200
        assert response.json()["role"] == "viewer"
        assert response.json()["workspace_id"] == actors["owner"].workspace_id
        assert peer.post("/v1/conversations", json={"title": "forbidden"}).status_code == 403
        assert peer.post("/v1/invitations", json={"email": "bad@example.com"}).status_code == 403


def test_signup_closed_expired_replaced_invitation_and_password_policy(client):
    assert client.post("/v1/auth/register", json={"email": "new@example.com"}).status_code == 403
    assert (
        client.post(
            "/v1/invitations", json={"email": "new@example.com", "role": "owner"}
        ).status_code
        == 422
    )
    old = invitation(client)
    fresh = invitation(client)
    assert (
        client.post("/v1/auth/redeem", json={"token": old, "password": PASSWORD}).status_code == 400
    )
    assert (
        client.post(
            "/v1/auth/redeem", json={"token": fresh, "password": "111111111111111"}
        ).status_code
        == 422
    )
    with session() as db, db.begin():
        db.get(AccountToken, digest(fresh)).expires_at = 1
    assert (
        client.post("/v1/auth/redeem", json={"token": fresh, "password": PASSWORD}).status_code
        == 400
    )


def test_public_signup_email_and_reset_do_not_expose_tokens(client, monkeypatch):
    monkeypatch.setattr(settings(), "signup_mode", "public")
    monkeypatch.setattr(settings(), "smtp_host", "mailpit")
    response = client.post("/v1/auth/register", json={"email": "registered@example.com"})
    assert response.status_code == 202
    assert "token" not in response.text and "link" not in response.text
    with session() as db:
        mail = db.scalar(select(AccountMail))
        assert "registered@example.com" not in mail.sealed
        raw = json.loads(cipher().decrypt(mail.sealed.encode()))["link"].split("=", 1)[1]
    assert (
        client.post(
            "/v1/auth/redeem",
            json={"token": raw, "password": PASSWORD, "workspace": "Verified team"},
        ).status_code
        == 204
    )
    with TestClient(app) as peer:
        assert (
            peer.post(
                "/v1/auth/login", json={"email": "registered@example.com", "password": PASSWORD}
            ).json()["role"]
            == "owner"
        )
    existing = client.post("/v1/auth/register", json={"email": "registered@example.com"})
    unknown = client.post("/v1/auth/forgot-password", json={"email": "unknown@example.com"})
    known = client.post("/v1/auth/forgot-password", json={"email": "owner@example.com"})
    assert existing.json() == unknown.json() == known.json()
    with session() as db:
        messages = [
            json.loads(cipher().decrypt(mail.sealed.encode()))
            for mail in db.scalars(select(AccountMail)).all()
        ]
        value = next(
            message
            for message in messages
            if message["purpose"] == "reset" and message["email"] == "owner@example.com"
        )
        reset = value["link"].split("=", 1)[1]
    assert (
        client.post("/v1/auth/redeem", json={"token": reset, "password": PASSWORD}).status_code
        == 204
    )
    assert client.get("/v1/auth/me").status_code == 401
    assert (
        client.post("/v1/auth/redeem", json={"token": reset, "password": PASSWORD}).status_code
        == 400
    )


def test_email_outbox_delivery_uses_stable_single_use_link_and_erases_payload(client, monkeypatch):
    monkeypatch.setattr(settings(), "smtp_host", "mailpit")
    monkeypatch.setattr(settings(), "smtp_starttls", True)
    monkeypatch.setattr(settings(), "smtp_user", "local-test")
    monkeypatch.setattr(settings(), "smtp_password", "local-test")
    smtp = MagicMock()
    monkeypatch.setattr(accounts.smtplib, "SMTP", smtp)
    invitation(client)
    job = claim()
    assert job.kind == "mail"
    process(job)
    smtp.return_value.__enter__.return_value.starttls.assert_called_once()
    smtp.return_value.__enter__.return_value.send_message.assert_called_once()
    with session() as db:
        row = db.get(AccountMail, job.target_id)
        assert row.sent and not row.sealed


def test_password_change_requires_old_password_and_revokes_every_session(client):
    with TestClient(app) as second:
        assert (
            second.post(
                "/v1/auth/login",
                json={"email": "owner@example.com", "password": "a-long-test-password"},
            ).status_code
            == 200
        )
        assert len(client.get("/v1/auth/security").json()["sessions"]) == 2
        body = {"password": "wrong", "new_password": PASSWORD}
        assert client.post("/v1/auth/password", json=body).status_code == 401
        body["password"] = "a-long-test-password"
        assert client.post("/v1/auth/password", json=body).status_code == 204
        assert second.get("/v1/auth/me").status_code == 401
        assert client.get("/v1/auth/me").status_code == 401
        assert (
            second.post(
                "/v1/auth/login", json={"email": "owner@example.com", "password": PASSWORD}
            ).status_code
            == 200
        )


def test_mfa_enrollment_replay_recovery_and_disable(client, actors):
    credential = {"password": "a-long-test-password"}
    assert client.post("/v1/auth/mfa/setup", json={"password": "wrong"}).status_code == 400
    setup = client.post("/v1/auth/mfa/setup", json=credential).json()
    assert setup["uri"].startswith("otpauth://totp/")
    assert (
        client.post("/v1/auth/mfa/confirm", json={**credential, "code": "bad"}).status_code == 400
    )
    result = client.post(
        "/v1/auth/mfa/confirm", json={**credential, "code": pyotp.TOTP(setup["secret"]).now()}
    )
    assert result.status_code == 200, result.text
    recovery = result.json()["recovery_codes"]
    assert len(set(recovery)) == 8
    with session() as db:
        row = db.get(User, actors["owner"].id)
        assert row.mfa_secret != setup["secret"] and recovery[0] not in row.recovery_codes
    with TestClient(app) as peer:
        login = {"email": "owner@example.com", **credential}
        assert peer.post("/v1/auth/login", json=login).status_code == 401
        assert (
            peer.post(
                "/v1/auth/login", json={**login, "code": pyotp.TOTP(setup["secret"]).now()}
            ).status_code
            == 401
        )
        next_code = pyotp.TOTP(setup["secret"]).at((int(time.time() // 30) + 1) * 30)
        assert peer.post("/v1/auth/login", json={**login, "code": next_code}).status_code == 200
        assert peer.post("/v1/auth/login", json={**login, "code": next_code}).status_code == 401
        assert peer.post("/v1/auth/login", json={**login, "code": recovery[0]}).status_code == 200
        assert peer.post("/v1/auth/login", json={**login, "code": recovery[0]}).status_code == 401
        assert (
            client.post(
                "/v1/auth/mfa/disable", json={**credential, "code": recovery[1]}
            ).status_code
            == 204
        )
        assert peer.get("/v1/auth/me").status_code == 401
        assert client.get("/v1/auth/security").json()["mfa_enabled"] is False


def test_owner_permissions_disable_revocation_and_cross_workspace_ids(client, actors):
    assert (
        client.patch(f"/v1/members/{actors['other'].id}", json={"role": "viewer"}).status_code
        == 404
    )
    assert (
        client.patch(f"/v1/members/{actors['owner'].id}", json={"role": "viewer"}).status_code
        == 409
    )
    with TestClient(app) as viewer:
        assert (
            viewer.post(
                "/v1/auth/login",
                json={"email": "viewer@example.com", "password": "a-long-test-password"},
            ).status_code
            == 200
        )
        assert viewer.get("/v1/members").status_code == 403
        assert (
            client.patch(
                f"/v1/members/{actors['viewer'].id}", json={"role": "editor", "disabled": True}
            ).status_code
            == 204
        )
        assert viewer.get("/v1/auth/me").status_code == 401
        assert (
            viewer.post(
                "/v1/auth/login",
                json={"email": "viewer@example.com", "password": "a-long-test-password"},
            ).status_code
            == 401
        )
    assert "password_hash" not in client.get("/v1/members").text


def test_session_scope_idle_revocation_and_cap(client, actors):
    with session() as db, db.begin():
        other_token = "other-session"
        db.add(
            LoginSession(
                digest=digest(other_token), user_id=actors["other"].id, expires_at=time.time() + 900
            )
        )
    assert client.delete(f"/v1/auth/sessions/{digest(other_token)}").status_code == 204
    with session() as db:
        assert db.get(LoginSession, digest(other_token))
    with session() as db, db.begin():
        row = db.get(LoginSession, digest(client.cookies.get(COOKIE)))
        row.last_seen_at = time.time() - settings().session_idle_seconds - 1
    assert client.get("/v1/auth/me").status_code == 401


def test_legacy_hashes_upgrade_on_success_and_invalid_hash_costs_are_rejected(client, actors):
    salt, password = "01" * 16, "a-long-test-password"
    legacy = (
        f"pbkdf2_sha256$310000${salt}$"
        + hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 310000).hex()
    )
    with session() as db, db.begin():
        db.get(User, actors["owner"].id).password_hash = legacy
    assert (
        client.post(
            "/v1/auth/login", json={"email": "owner@example.com", "password": password}
        ).status_code
        == 200
    )
    with session() as db:
        assert db.get(User, actors["owner"].id).password_hash.startswith("$argon2id$")
    assert not verify_password(password, legacy.replace("310000", "999999999"))


@pytest.mark.parametrize("path", ["/v1/auth/register", "/v1/auth/forgot-password"])
def test_email_configuration_fails_closed_without_exposing_accounts(client, monkeypatch, path):
    monkeypatch.setattr(settings(), "signup_mode", "public")
    monkeypatch.setattr(settings(), "smtp_host", "")
    assert client.post(path, json={"email": "new@example.com"}).status_code == 503
