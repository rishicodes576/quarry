"""Single-use account lifecycle operations; roles always originate on the server."""

import hashlib
import json
import secrets
import smtplib
import ssl
import time
from email.message import EmailMessage

import pyotp
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy import delete, func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError

from quarry.config import settings
from quarry.db import (
    AccountMail,
    AccountToken,
    ApiKey,
    AuthAudit,
    LoginSession,
    User,
    Workspace,
    session,
)
from quarry.queue import admit, enqueue, fenced, scheduler_lock
from quarry.security import (
    COOKIE,
    audit,
    authenticate,
    cipher,
    current_user,
    digest,
    hash_password,
    owner,
    rate_limit,
    remote_address,
    validate_password,
    verify_password,
)

router = APIRouter(prefix="/v1")
MAIL_WORKSPACE = "00000000000000000000000000000001"
GENERIC = {
    "message": "If this address is eligible, an email with the next step will arrive shortly."
}


class StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EmailInput(StrictInput):
    email: EmailStr = Field(max_length=254)


class InviteInput(EmailInput):
    role: str = Field(pattern="^(editor|viewer)$", default="editor")


class RedeemInput(StrictInput):
    token: str = Field(min_length=32, max_length=128)
    password: str = Field(min_length=15, max_length=128)
    workspace: str = Field(default="Research workspace", min_length=1, max_length=120)


class CredentialInput(StrictInput):
    password: str = Field(min_length=1, max_length=256)
    code: str = Field(default="", max_length=64)


class PasswordInput(CredentialInput):
    new_password: str = Field(min_length=15, max_length=128)


class KeyInput(CredentialInput):
    label: str = Field(min_length=1, max_length=100)
    scope: str = Field(default="read", pattern="^(read|write)$")
    days: int = Field(default=30, ge=1, le=90)


class MemberChange(StrictInput):
    role: str = Field(pattern="^(editor|viewer)$")
    disabled: bool = False


def sensitive(request: Request, name: str, email: str = ""):
    remote = remote_address(request)
    rate_limit(f"account:{name}:{remote}", 20, 900)
    if email:
        rate_limit(f"account:{name}:{email.lower()}", 3, 3600)


def issue(db, purpose, email, workspace_id=None, role="editor"):
    # Issuing a replacement invalidates older links for this purpose and address.
    criteria = [AccountToken.email == email, AccountToken.purpose == purpose]
    if purpose == "invite":
        criteria.append(AccountToken.workspace_id == workspace_id)
    db.execute(delete(AccountToken).where(*criteria))
    raw = secrets.token_urlsafe(32)
    expires = time.time() + (86400 if purpose == "invite" else 1800)
    db.add(
        AccountToken(
            digest=digest(raw),
            email=email,
            purpose=purpose,
            workspace_id=workspace_id,
            role=role,
            expires_at=expires,
        )
    )
    return raw, expires


def queue_mail(db, email: str, purpose: str, raw: str, expires: float):
    if not settings().smtp_host:
        raise HTTPException(503, "Account email is not configured; contact the deployment owner")
    admit(db)
    db.execute(
        pg_insert(Workspace)
        .values(id=MAIL_WORKSPACE, name="Account delivery", created_at=time.time())
        .on_conflict_do_nothing()
    )
    # Fragments keep bearer links out of HTTP request paths, referrers and access logs.
    link = f"{settings().app_origin}/#{purpose}={raw}"
    sealed = (
        cipher()
        .encrypt(json.dumps({"email": email, "purpose": purpose, "link": link}).encode())
        .decode()
    )
    mail = AccountMail(sealed=sealed, expires_at=expires)
    db.add(mail)
    db.flush()
    enqueue(db, MAIL_WORKSPACE, "mail", mail.id)


def deliver(job):
    with fenced(job) as (db, _):
        row = db.get(AccountMail, job.target_id)
        if not row or row.sent or row.expires_at <= time.time():
            return
        value = json.loads(cipher().decrypt(row.sealed.encode()))
    cfg = settings()
    message = EmailMessage()
    message["From"], message["To"] = cfg.mail_from, value["email"]
    message["Subject"] = "Quarry account: " + value["purpose"]
    message["Message-ID"] = f"<{job.target_id}@quarry.local>"
    message.set_content(
        f"Continue your Quarry {value['purpose']} request:\n\n{value['link']}\n\nThis link expires and can be used once. If you did not request it, ignore this email."
    )
    with smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=10) as smtp:
        if cfg.smtp_starttls:
            smtp.starttls(context=ssl.create_default_context())
        if cfg.smtp_user:
            smtp.login(cfg.smtp_user, cfg.smtp_password)
        smtp.send_message(message)
    # SMTP is at-least-once across a crash after send. Repeated mail retains one single-use token.
    with fenced(job) as (db, _):
        row = db.get(AccountMail, job.target_id)
        row.sent, row.sealed = True, ""


@router.get("/auth/options")
def options():
    return {"signup": settings().signup_mode, "email_recovery": bool(settings().smtp_host)}


@router.post("/auth/register", status_code=202)
def register(body: EmailInput, request: Request):
    if settings().signup_mode != "public":
        raise HTTPException(403, "Registration requires a workspace invitation")
    sensitive(request, "register", body.email)
    if not settings().smtp_host:
        raise HTTPException(503, "Verification email is not configured")
    with session() as db, db.begin():
        if not db.scalar(select(User.id).where(User.email == body.email.lower())):
            raw, expires = issue(db, "signup", body.email.lower())
            queue_mail(db, body.email.lower(), "signup", raw, expires)
    return GENERIC


@router.post("/auth/forgot-password", status_code=202)
def forgot(body: EmailInput, request: Request):
    sensitive(request, "reset", body.email)
    if not settings().smtp_host:
        raise HTTPException(503, "Account email is not configured; contact the deployment owner")
    with session() as db, db.begin():
        user = db.scalar(
            select(User).where(User.email == body.email.lower(), User.disabled.is_(False))
        )
        if user:
            raw, expires = issue(db, "reset", user.email, user.workspace_id)
            queue_mail(db, user.email, "reset", raw, expires)
    return GENERIC


@router.post("/invitations", status_code=201)
def invite(body: InviteInput, request: Request, user: User = Depends(owner)):
    sensitive(request, "invite", body.email)
    with session() as db, db.begin():
        lock_key = int.from_bytes(
            hashlib.sha256(("invitations:" + user.workspace_id).encode()).digest()[:8],
            "big",
            signed=True,
        )
        db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_key})
        pending = db.scalar(
            select(func.count())
            .select_from(AccountToken)
            .where(
                AccountToken.workspace_id == user.workspace_id,
                AccountToken.purpose == "invite",
                AccountToken.consumed_at.is_(None),
                AccountToken.expires_at > time.time(),
                AccountToken.email != body.email.lower(),
            )
        )
        if pending >= settings().max_workspace_members:
            raise HTTPException(429, "Pending invitation limit reached; revoke unused invitations")
        if db.scalar(select(User.id).where(User.email == body.email.lower())):
            raise HTTPException(409, "This address cannot accept a new account invitation")
        raw, expires = issue(db, "invite", body.email.lower(), user.workspace_id, body.role)
        if settings().smtp_host:
            queue_mail(db, body.email.lower(), "invite", raw, expires)
        audit(db, "invitation_created", user)
    return {
        "link": f"{settings().app_origin}/#invite={raw}",
        "expires_at": expires,
        "email_sent": False,
        "delivery": "queued" if settings().smtp_host else "share_privately",
    }


@router.post("/auth/redeem", status_code=204)
def redeem(body: RedeemInput, request: Request):
    sensitive(request, "redeem")
    validate_password(body.password)
    encoded = hash_password(body.password)
    with session() as db, db.begin():
        token = db.get(AccountToken, digest(body.token), with_for_update=True)
        if not token or token.consumed_at or token.expires_at <= time.time():
            raise HTTPException(400, "This account link is invalid, expired, or already used")
        if token.purpose not in {"reset", "signup", "invite"}:
            raise HTTPException(400, "Invalid account link")
        user = db.scalar(select(User).where(User.email == token.email).with_for_update())
        if token.purpose == "reset":
            if not user or user.disabled:
                raise HTTPException(400, "Invalid account link")
            user.password_hash = encoded
            db.execute(delete(LoginSession).where(LoginSession.user_id == user.id))
            db.execute(delete(ApiKey).where(ApiKey.user_id == user.id))
            audit(db, "password_reset", user)
        else:
            if (
                user
                or settings().signup_mode == "disabled"
                or (token.purpose == "signup" and settings().signup_mode != "public")
            ):
                raise HTTPException(400, "This account link can no longer create an account")
            if token.purpose == "signup":
                scheduler_lock(db, "registration")
                if (
                    db.scalar(select(func.count()).select_from(Workspace))
                    >= settings().max_workspaces
                ):
                    raise HTTPException(
                        503,
                        "New workspace capacity is temporarily exhausted",
                        headers={"Retry-After": "300"},
                    )
                workspace = Workspace(name=body.workspace)
                db.add(workspace)
                db.flush()
                workspace_id, role = workspace.id, "owner"
            else:
                workspace_id, role = token.workspace_id, token.role
                db.get(Workspace, workspace_id, with_for_update=True)
                members = db.scalar(
                    select(func.count()).select_from(User).where(User.workspace_id == workspace_id)
                )
                if members >= settings().max_workspace_members:
                    raise HTTPException(429, "Workspace member limit reached; contact its owner")
            user = User(
                email=token.email, password_hash=encoded, workspace_id=workspace_id, role=role
            )
            db.add(user)
            try:
                db.flush()
            except IntegrityError:
                raise HTTPException(
                    400, "This account link can no longer create an account"
                ) from None
            audit(db, "account_created", user)
        token.consumed_at = time.time()


@router.get("/invitations")
def invitations(user: User = Depends(owner)):
    with session() as db:
        return [
            {"id": row.digest, "email": row.email, "role": row.role, "expires_at": row.expires_at}
            for row in db.scalars(
                select(AccountToken).where(
                    AccountToken.workspace_id == user.workspace_id,
                    AccountToken.purpose == "invite",
                    AccountToken.consumed_at.is_(None),
                    AccountToken.expires_at > time.time(),
                )
            ).all()
        ]


@router.delete("/invitations/{invitation_id}", status_code=204)
def revoke_invitation(invitation_id: str, user: User = Depends(owner)):
    with session() as db, db.begin():
        db.execute(
            delete(AccountToken).where(
                AccountToken.digest == invitation_id,
                AccountToken.workspace_id == user.workspace_id,
                AccountToken.purpose == "invite",
            )
        )
        audit(db, "invitation_revoked", user)


@router.get("/auth/security")
def security_status(request: Request, user: User = Depends(current_user)):
    now = time.time()
    with session() as db:
        rows = db.scalars(
            select(LoginSession)
            .where(
                LoginSession.user_id == user.id,
                LoginSession.expires_at > now,
                LoginSession.last_seen_at > now - settings().session_idle_seconds,
            )
            .order_by(LoginSession.created_at.desc())
        ).all()
        return {
            "mfa_enabled": bool(user.mfa_secret),
            "sessions": [
                {
                    "id": row.digest,
                    "created_at": row.created_at,
                    "last_seen_at": row.last_seen_at,
                    "expires_at": row.expires_at,
                    "current": row.digest == digest(request.cookies.get(COOKIE, "")),
                }
                for row in rows
            ],
        }


@router.delete("/auth/sessions/{session_id}", status_code=204)
def revoke(
    session_id: str, request: Request, response: Response, user: User = Depends(current_user)
):
    with session() as db, db.begin():
        db.execute(
            delete(LoginSession).where(
                LoginSession.user_id == user.id, LoginSession.digest == session_id
            )
        )
        audit(db, "session_revoked", user)
    if session_id == digest(request.cookies.get(COOKIE, "")):
        response.delete_cookie(COOKIE, path="/")


@router.post("/auth/password", status_code=204)
def password_change(
    body: PasswordInput, request: Request, response: Response, user: User = Depends(current_user)
):
    sensitive(request, "password")
    validate_password(body.new_password)
    encoded = hash_password(body.new_password)
    with session() as db, db.begin():
        row = db.get(User, user.id, with_for_update=True)
        authenticate(row, body.password, body.code)
        row.password_hash = encoded
        db.execute(delete(LoginSession).where(LoginSession.user_id == row.id))
        db.execute(delete(ApiKey).where(ApiKey.user_id == row.id))
        audit(db, "password_changed", row)
    response.delete_cookie(COOKIE, path="/")


@router.post("/auth/mfa/setup")
def mfa_setup(body: CredentialInput, request: Request, user: User = Depends(current_user)):
    sensitive(request, "mfa")
    with session() as db, db.begin():
        row = db.get(User, user.id, with_for_update=True)
        if row.mfa_secret or not verify_password(body.password, row.password_hash):
            raise HTTPException(400, "Check your password and current MFA status")
        raw = pyotp.random_base32()
        row.mfa_pending, row.mfa_pending_until = (
            cipher().encrypt(raw.encode()).decode(),
            time.time() + 600,
        )
    return {
        "secret": raw,
        "uri": pyotp.TOTP(raw).provisioning_uri(user.email, issuer_name="Quarry"),
    }


@router.post("/auth/mfa/confirm")
def mfa_confirm(body: CredentialInput, request: Request, user: User = Depends(current_user)):
    sensitive(request, "mfa")
    with session() as db, db.begin():
        row = db.get(User, user.id, with_for_update=True)
        if (
            not row.mfa_pending
            or row.mfa_pending_until <= time.time()
            or not verify_password(body.password, row.password_hash)
        ):
            raise HTTPException(400, "MFA setup expired or password is incorrect")
        secret = cipher().decrypt(row.mfa_pending.encode()).decode()
        verified_at = time.time()
        if not pyotp.TOTP(secret).verify(body.code, for_time=verified_at, valid_window=0):
            raise HTTPException(400, "Verification code is incorrect")
        row.mfa_secret, row.mfa_pending, row.mfa_last_step = (
            row.mfa_pending,
            "",
            int(verified_at // 30),
        )
        codes = [secrets.token_hex(10) for _ in range(8)]
        row.recovery_codes = [digest("recovery:" + code) for code in codes]
        db.execute(
            delete(LoginSession).where(
                LoginSession.user_id == row.id,
                LoginSession.digest != digest(request.cookies.get(COOKIE, "")),
            )
        )
        audit(db, "mfa_enabled", row)
        db.execute(delete(ApiKey).where(ApiKey.user_id == row.id))
    return {"recovery_codes": codes}


@router.post("/auth/mfa/disable", status_code=204)
def mfa_disable(body: CredentialInput, request: Request, user: User = Depends(current_user)):
    sensitive(request, "mfa")
    with session() as db, db.begin():
        row = db.get(User, user.id, with_for_update=True)
        authenticate(row, body.password, body.code)
        row.mfa_secret, row.recovery_codes = "", []
        db.execute(
            delete(LoginSession).where(
                LoginSession.user_id == row.id,
                LoginSession.digest != digest(request.cookies.get(COOKIE, "")),
            )
        )
        audit(db, "mfa_disabled", row)
        db.execute(delete(ApiKey).where(ApiKey.user_id == row.id))


@router.get("/members")
def members(user: User = Depends(owner)):
    with session() as db:
        return [
            {"id": row.id, "email": row.email, "role": row.role, "disabled": row.disabled}
            for row in db.scalars(select(User).where(User.workspace_id == user.workspace_id)).all()
        ]


@router.patch("/members/{member_id}", status_code=204)
def member_change(member_id: str, body: MemberChange, user: User = Depends(owner)):
    with session() as db, db.begin():
        db.get(Workspace, user.workspace_id, with_for_update=True)
        row = db.scalar(
            select(User)
            .where(User.id == member_id, User.workspace_id == user.workspace_id)
            .with_for_update()
        )
        if not row:
            raise HTTPException(404, "Member not found")
        if row.role == "owner":
            raise HTTPException(409, "Owner accounts require operator-managed ownership transfer")
        row.role, row.disabled = body.role, body.disabled
        if row.disabled:
            db.execute(delete(LoginSession).where(LoginSession.user_id == row.id))
            db.execute(delete(ApiKey).where(ApiKey.user_id == row.id))
        audit(db, "member_permissions_changed", user)


@router.get("/auth/audit")
def audit_events(user: User = Depends(current_user)):
    with session() as db:
        return [
            {"action": row.action, "created_at": row.created_at}
            for row in db.scalars(
                select(AuthAudit)
                .where(AuthAudit.user_id == user.id)
                .order_by(AuthAudit.created_at.desc())
                .limit(50)
            ).all()
        ]


@router.get("/auth/keys")
def keys(user: User = Depends(owner)):
    with session() as db:
        return [
            {"id": row.digest, "label": row.label, "scope": row.scope, "expires_at": row.expires_at}
            for row in db.scalars(
                select(ApiKey).where(ApiKey.user_id == user.id, ApiKey.expires_at > time.time())
            ).all()
        ]


@router.post("/auth/keys", status_code=201)
def create_key(body: KeyInput, request: Request, user: User = Depends(owner)):
    sensitive(request, "key")
    with session() as db, db.begin():
        row = db.get(User, user.id, with_for_update=True)
        authenticate(row, body.password, body.code)
        if (
            db.scalar(
                select(func.count())
                .select_from(ApiKey)
                .where(ApiKey.user_id == row.id, ApiKey.expires_at > time.time())
            )
            >= 10
        ):
            raise HTTPException(409, "Revoke an existing API key before creating another")
        raw = "qk_" + secrets.token_urlsafe(32)
        expiry = time.time() + body.days * 86400
        db.add(
            ApiKey(
                digest=digest(raw),
                user_id=row.id,
                label=body.label,
                scope=body.scope,
                expires_at=expiry,
            )
        )
        audit(db, "api_key_created", row)
    return {
        "key": raw,
        "expires_at": expiry,
        "scope": body.scope,
        "notice": "Save this server-side secret now; it will not be shown again",
    }


@router.delete("/auth/keys/{key_id}", status_code=204)
def revoke_key(key_id: str, user: User = Depends(owner)):
    with session() as db, db.begin():
        db.execute(delete(ApiKey).where(ApiKey.user_id == user.id, ApiKey.digest == key_id))
        audit(db, "api_key_revoked", user)
