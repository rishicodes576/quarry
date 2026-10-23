"""Opaque, revocable sessions and bounded password verification. No browser JWTs."""

import base64
import hashlib
import hmac
import ipaddress
import secrets
import threading
import time

import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from fastapi import Depends, HTTPException, Request
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from quarry.config import settings
from quarry.db import ApiKey, AuthAudit, LoginSession, RateBucket, User, session

COOKIE = "quarry_session"
DEMO_EMAILS = {"demo@quarry.local", "viewer@quarry.local"}
PASSWORDS = PasswordHasher(time_cost=3, memory_cost=19456, parallelism=1)
PASSWORD_SLOTS = threading.BoundedSemaphore(4)


def remote_address(request):
    secret = settings().proxy_secret
    if secret and hmac.compare_digest(request.headers.get("x-quarry-proxy-secret", ""), secret):
        try:
            return str(ipaddress.ip_address(request.headers.get("x-quarry-client-ip", "")))
        except ValueError:
            pass
    return request.client.host if request.client else "unknown"


def hash_password(password: str) -> str:
    with PASSWORD_SLOTS:
        return PASSWORDS.hash(password)


def verify_password(password: str, encoded: str) -> bool:
    try:
        with PASSWORD_SLOTS:
            if encoded.startswith("pbkdf2_sha256$"):
                _, iterations, salt, expected = encoded.split("$")
                rounds = int(iterations)
                if not 310_000 <= rounds <= 1_000_000:
                    return False
                actual = hashlib.pbkdf2_hmac(
                    "sha256", password.encode(), bytes.fromhex(salt), rounds
                ).hex()
                return hmac.compare_digest(actual, expected)
            return PASSWORDS.verify(encoded, password)
    except (ValueError, TypeError, VerificationError, InvalidHashError):
        return False


DUMMY_PASSWORD_HASH = hash_password(secrets.token_urlsafe(32))


def account_active(user: User | None) -> bool:
    return bool(
        user
        and not user.disabled
        and not (settings().env == "production" and user.email.lower() in DEMO_EMAILS)
    )


def validate_password(password: str) -> None:
    if not 15 <= len(password) <= 128 or len(set(password)) < 5:
        raise HTTPException(422, "Use a unique password or passphrase of 15–128 characters")
    if password.casefold() in {"passwordpassword", "123456789012345", "quarry-demo-local"}:
        raise HTTPException(422, "Choose a password that is not commonly used")


def digest(value: str) -> str:
    return hmac.new(settings().session_secret.encode(), value.encode(), hashlib.sha256).hexdigest()


def cipher() -> Fernet:
    key = HKDF(
        algorithm=hashes.SHA256(), length=32, salt=b"quarry-accounts-v1", info=b"mfa-and-mail"
    ).derive(settings().session_secret.encode())
    return Fernet(base64.urlsafe_b64encode(key))


def audit(db, action: str, user: User | None = None):
    db.add(
        AuthAudit(
            action=action,
            user_id=user.id if user else "",
            workspace_id=user.workspace_id if user else "",
        )
    )


def rate_limit(key: str, limit: int, window: int = 60, *, db=None) -> None:
    now = time.time()
    bucket = f"{digest(key)}:{int(now // window)}"

    def increment(connection):
        statement = pg_insert(RateBucket).values(id=bucket, count=1, expires_at=now + window * 2)
        statement = statement.on_conflict_do_update(
            index_elements=[RateBucket.id], set_={"count": RateBucket.count + 1}
        ).returning(RateBucket.count)
        count = connection.execute(statement).scalar_one()
        connection.execute(delete(RateBucket).where(RateBucket.expires_at < now))
        return count

    if db is None:
        with session() as connection, connection.begin():
            count = increment(connection)
    else:
        # Admission already holds a transaction. Opening a nested connection can
        # deadlock a saturated pool behind the global admission row lock.
        count = increment(db)
    if count > limit:
        raise HTTPException(
            429,
            "Too many requests; wait before retrying",
            headers={"Retry-After": str(window - int(now % window))},
        )


def current_user(request: Request) -> User:
    if request.headers.get("authorization"):
        return api_principal(request)
    token = request.cookies.get(COOKIE, "")
    if not token or len(token) > 128:
        raise HTTPException(401, "Sign in to your workspace")
    now = time.time()
    with session() as db, db.begin():
        row = db.get(LoginSession, digest(token), with_for_update=True)
        if (
            not row
            or row.expires_at <= now
            or row.last_seen_at + settings().session_idle_seconds <= now
        ):
            raise HTTPException(401, "Session expired")
        user = db.get(User, row.user_id)
        if not account_active(user):
            raise HTTPException(401, "Session invalid")
        if now - row.last_seen_at > 60:
            row.last_seen_at = now
        return user


def api_principal(request):
    value = request.headers["authorization"]
    if not value.startswith("Bearer qk_") or len(value) > 128:
        raise HTTPException(401, "Invalid API credential")
    with session() as db:
        key = db.get(ApiKey, digest(value[7:]))
        user = db.get(User, key.user_id) if key and key.expires_at > time.time() else None
        if not account_active(user):
            raise HTTPException(401, "API credential is expired, revoked, or invalid")
        if not request.url.path.startswith(
            (
                "/v1/documents",
                "/v1/conversations",
                "/v1/runs",
                "/v1/search/",
                "/v1/providers",
                "/v1/overview",
                "/v1/usage",
            )
        ):
            raise HTTPException(403, "Machine keys cannot administer accounts or workspace access")
        role = "viewer" if user.role == "viewer" or key.scope == "read" else "editor"
        principal = User(id=user.id, email=user.email, workspace_id=user.workspace_id, role=role)
        key_id = key.digest
    # Release the read connection before the limiter opens its own transaction.
    rate_limit(f"api-key:{key_id}", 120)
    return principal


def writer(user: User = Depends(current_user)) -> User:
    if user.role not in {"owner", "editor"}:
        raise HTTPException(403, "This account has read-only access")
    return user


def owner(user: User = Depends(current_user)) -> User:
    if user.role != "owner":
        raise HTTPException(403, "Workspace owner access required")
    return user


def verify_factor(user: User, code: str) -> bool:
    if not user.mfa_secret:
        return True
    if not code or len(code) > 64:
        return False
    encoded = digest("recovery:" + code)
    for candidate in user.recovery_codes:
        if hmac.compare_digest(encoded, candidate):
            user.recovery_codes = [x for x in user.recovery_codes if x != candidate]
            return True
    otp = pyotp.TOTP(cipher().decrypt(user.mfa_secret.encode()).decode())
    step = int(time.time() // 30)
    for candidate in [step, step - 1, step + 1]:
        if candidate > user.mfa_last_step and hmac.compare_digest(otp.at(candidate * 30), code):
            user.mfa_last_step = candidate
            return True
    return False


def authenticate(user: User, password: str, code: str = "") -> None:
    if not verify_password(password, user.password_hash) or not verify_factor(user, code):
        raise HTTPException(401, "Invalid password or verification code")


def login(email: str, password: str, remote: str, code: str = "") -> tuple[User, str]:
    rate_limit(f"login:{remote}", 40, 300)
    rate_limit(f"login-email:{email.lower()}", 10, 300)
    with session() as db, db.begin():
        user = db.scalar(select(User).where(User.email == email.lower()).with_for_update())
        valid = verify_password(password, user.password_hash if user else DUMMY_PASSWORD_HASH)
        if not valid or not account_active(user):
            raise HTTPException(401, "Invalid email, password, or verification code")
        if not verify_factor(user, code):
            raise HTTPException(401, "A valid verification or recovery code is required")
        if not user.password_hash.startswith("$argon2id$") or PASSWORDS.check_needs_rehash(
            user.password_hash
        ):
            user.password_hash = hash_password(password)
        now, token = time.time(), secrets.token_urlsafe(32)
        existing = db.scalars(
            select(LoginSession)
            .where(LoginSession.user_id == user.id)
            .order_by(LoginSession.created_at.desc())
        ).all()
        for old in existing[9:]:
            db.delete(old)
        db.add(
            LoginSession(
                digest=digest(token),
                user_id=user.id,
                expires_at=now + 86400 * 7,
                created_at=now,
                last_seen_at=now,
            )
        )
        db.execute(delete(LoginSession).where(LoginSession.expires_at < now))
        audit(db, "login", user)
        return user, token
