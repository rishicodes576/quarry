import asyncio
import hashlib
import json
import logging
import re
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, File, Header, HTTPException, Request, Response, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from sqlalchemy import cast, func, select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import load_only

from quarry import providers, retrieval, storage
from quarry.config import settings
from quarry.db import (
    Chunk,
    Conversation,
    Document,
    Event,
    Job,
    LoginSession,
    Run,
    User,
    Workspace,
    session,
    uid,
)
from quarry.network import FetchError, fetch_public
from quarry.queue import admit, enqueue, event
from quarry.schemas import (
    ConversationInput,
    ConversationOut,
    DocumentOut,
    EventOut,
    LoginInput,
    MemberInput,
    RunInput,
    RunOut,
    SearchInput,
    SearchResult,
    URLInput,
    UserOut,
)
from quarry.security import (
    COOKIE,
    current_user,
    digest,
    hash_password,
    login,
    owner,
    rate_limit,
    remote_address,
    writer,
)

log = logging.getLogger("quarry")
REQUESTS = Counter("quarry_http_requests_total", "HTTP responses", ["method", "status"])
LATENCY = Histogram("quarry_http_duration_seconds", "HTTP handler latency", ["method"])
TERMINAL = {"completed", "failed", "cancelled", "quota_exhausted"}
BODY_SLOTS = threading.BoundedSemaphore(16)
BODY_TIMEOUT_SECONDS = 15


@asynccontextmanager
async def lifespan(_):
    await asyncio.to_thread(retrieval.warm_models)
    yield


app = FastAPI(
    title="Quarry Research API",
    version="0.1.0",
    lifespan=lifespan,
    docs_url=None if settings().env == "production" else "/docs",
    redoc_url=None,
    openapi_url=None if settings().env == "production" else "/openapi.json",
)


@app.middleware("http")
async def boundary(request: Request, call_next):
    if request.method not in {"POST", "PUT", "PATCH"}:
        return await guarded_boundary(request, call_next)
    if not BODY_SLOTS.acquire(blocking=False):
        return JSONResponse(
            {"detail": "Request capacity is busy; retry shortly"},
            status_code=503,
            headers={"Retry-After": "1"},
        )
    try:
        return await guarded_boundary(request, call_next)
    finally:
        BODY_SLOTS.release()


async def guarded_boundary(request: Request, call_next):
    started = time.perf_counter()
    request_id = request.headers.get("x-request-id", "")
    if not re.fullmatch(r"[a-zA-Z0-9-]{1,64}", request_id):
        request_id = uid()
    origin = request.headers.get("origin")
    if (
        request.method in {"POST", "PUT", "PATCH", "DELETE"}
        and origin
        and origin != settings().app_origin
    ):
        return JSONResponse({"detail": "Cross-origin mutations are not allowed"}, status_code=403)
    length = request.headers.get("content-length", "0")
    try:
        if int(length) > settings().max_upload_bytes + 64_000:
            return JSONResponse({"detail": "Request exceeds upload limit"}, status_code=413)
    except ValueError:
        return JSONResponse({"detail": "Invalid Content-Length"}, status_code=400)
    if request.method in {"POST", "PUT", "PATCH"}:
        size, parts = 0, []
        try:
            async with asyncio.timeout(BODY_TIMEOUT_SECONDS):
                async for part in request.stream():
                    size += len(part)
                    if size > settings().max_upload_bytes + 64_000:
                        return JSONResponse(
                            {"detail": "Request exceeds upload limit"}, status_code=413
                        )
                    parts.append(part)
        except TimeoutError:
            return JSONResponse({"detail": "Request body deadline exceeded"}, status_code=408)
        request._body = b"".join(parts)
    try:
        response = await call_next(request)
    except Exception as error:
        log.error(
            json.dumps(
                {
                    "event": "request_failed",
                    "request_id": request_id,
                    "reason": type(error).__name__,
                }
            )
        )
        response = JSONResponse(
            {"detail": "Request failed; use the request ID when reporting it"}, status_code=500
        )
    REQUESTS.labels(request.method, str(response.status_code)).inc()
    LATENCY.labels(request.method).observe(time.perf_counter() - started)
    log.info(
        json.dumps(
            {
                "event": "http_response",
                "request_id": request_id,
                "method": request.method,
                "status": response.status_code,
                "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            }
        )
    )
    response.headers.update(
        {
            "X-Request-ID": request_id,
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "same-origin",
            "Cache-Control": "no-store",
        }
    )
    return response


def scoped(db, model, object_id: str, user: User):
    result = db.scalar(
        select(model).where(model.id == object_id, model.workspace_id == user.workspace_id)
    )
    if result is None or (isinstance(result, Document) and result.deleted):
        raise HTTPException(404, "Resource not found")
    return result


@app.get("/health/live")
def live():
    return {"status": "alive"}


@app.get("/health/ready")
def ready():
    try:
        with session() as db:
            db.execute(text("SELECT 1"))
            if (
                settings().env == "production"
                and db.execute(
                    text(
                        "SELECT rolsuper OR rolcreatedb OR rolcreaterole FROM pg_roles WHERE rolname = current_user"
                    )
                ).scalar_one()
            ):
                raise RuntimeError("Runtime database privileges are excessive")
        retrieval.qdrant().get_collection(retrieval.COLLECTION)
        storage.client().head_bucket(Bucket=settings().s3_bucket)
        from quarry.ingest import parser_ready

        parser_ready()
    except Exception:
        raise HTTPException(503, "A required dependency is unavailable") from None
    return {"status": "ready"}


@app.get("/metrics", include_in_schema=False)
def metrics():
    from quarry.metrics import shared_metrics

    return Response(generate_latest() + shared_metrics(), media_type=CONTENT_TYPE_LATEST)


@app.post("/v1/auth/login", response_model=UserOut)
def sign_in(body: LoginInput, request: Request, response: Response):
    user, token = login(body.email, body.password, remote_address(request), body.code)
    response.set_cookie(
        COOKIE,
        token,
        httponly=True,
        secure=settings().cookie_secure,
        samesite="lax",
        max_age=7 * 86400,
        path="/",
    )
    return user


@app.get("/v1/auth/me", response_model=UserOut)
def me(user: User = Depends(current_user)):
    return user


@app.post("/v1/auth/logout", status_code=204)
def sign_out(request: Request, response: Response, user: User = Depends(current_user)):
    with session() as db, db.begin():
        row = db.get(LoginSession, digest(request.cookies.get(COOKIE, "")))
        if row:
            db.delete(row)
    response.delete_cookie(COOKIE, path="/")


@app.post("/v1/members", response_model=UserOut, status_code=201)
def create_member(body: MemberInput, user: User = Depends(owner)):
    if settings().env == "production":
        raise HTTPException(404, "Use workspace invitations")
    with session() as db, db.begin():
        member = User(
            email=body.email.lower(),
            password_hash=hash_password(body.password),
            workspace_id=user.workspace_id,
            role=body.role,
        )
        db.add(member)
        try:
            db.flush()
        except IntegrityError:
            raise HTTPException(409, "This email is already registered") from None
        return member


from quarry.accounts import router as accounts_router  # noqa: E402

app.include_router(accounts_router)

from quarry.capacity import router as capacity_router  # noqa: E402

app.include_router(capacity_router)


@app.get("/v1/providers")
def provider_options(user: User = Depends(current_user)):
    return providers.provider_status()


@app.get("/v1/overview")
def overview(user: User = Depends(current_user)):
    with session() as db:
        documents = db.scalar(
            select(func.count())
            .select_from(Document)
            .where(
                Document.workspace_id == user.workspace_id,
                Document.deleted.is_(False),
                Document.status == "ready",
            )
        )
        chunks = db.scalar(
            select(func.coalesce(func.sum(Document.chunk_count), 0)).where(
                Document.workspace_id == user.workspace_id,
                Document.deleted.is_(False),
                Document.status == "ready",
            )
        )
        completed = db.scalar(
            select(func.count())
            .select_from(Run)
            .where(Run.workspace_id == user.workspace_id, Run.status == "completed")
        )
        pending = db.scalar(
            select(func.count())
            .select_from(Job)
            .where(Job.workspace_id == user.workspace_id, Job.status.in_(["pending", "running"]))
        )
        return {
            "documents": documents,
            "chunks": chunks,
            "completed_runs": completed,
            "pending_jobs": pending,
            "workspace": db.get(Workspace, user.workspace_id).name,
            "generation": "free-only"
            if not settings().allow_paid_providers
            else "explicit-consent",
            "demo": settings().demo_seed,
        }


def add_document(user: User, body: bytes, media_type: str, title: str, source_url: str = ""):
    if len(body) > settings().max_upload_bytes:
        raise HTTPException(413, "Document exceeds the 10 MiB upload limit")
    if not body:
        raise HTTPException(422, "Document is empty")
    if not (
        media_type.startswith("text/")
        or media_type == "application/pdf"
        or title.lower().endswith((".pdf", ".md", ".txt", ".html"))
    ):
        raise HTTPException(422, "Supported formats: text PDF, Markdown, plain text, HTML")
    hashed = hashlib.sha256(body).hexdigest()
    source_key = hashlib.sha256((source_url or title).encode()).hexdigest()
    object_key = f"{user.workspace_id}/{uid()}"
    storage.put(object_key, body, media_type)
    try:
        with session() as db, db.begin():
            admit(db, check=False)
            db.scalar(select(Workspace).where(Workspace.id == user.workspace_id).with_for_update())
            existing = db.scalar(
                select(Document).where(
                    Document.workspace_id == user.workspace_id,
                    Document.content_hash == hashed,
                    Document.deleted.is_(False),
                    Document.status != "superseded",
                )
            )
            if existing:
                storage.remove(object_key)
                return existing
            admit(db)
            retained_count = db.scalar(
                select(func.count())
                .select_from(Document)
                .where(Document.workspace_id == user.workspace_id)
            )
            if retained_count >= settings().max_workspace_documents:
                raise HTTPException(
                    429, "Retained source-version limit reached; contact an operator"
                )
            stored = db.scalar(
                select(func.coalesce(func.sum(Document.byte_size), 0)).where(
                    Document.workspace_id == user.workspace_id, Document.object_key != ""
                )
            )
            total_stored = db.scalar(
                select(func.coalesce(func.sum(Document.byte_size), 0)).where(
                    Document.object_key != ""
                )
            )
            if stored + len(body) > settings().max_workspace_storage_bytes:
                raise HTTPException(
                    413, "Workspace storage allowance is full; delete sources and wait for cleanup"
                )
            if total_stored + len(body) > settings().max_global_storage_bytes:
                raise HTTPException(
                    503, "Shared storage allowance is full", headers={"Retry-After": "300"}
                )
            count = db.scalar(
                select(func.count())
                .select_from(Job)
                .where(
                    Job.workspace_id == user.workspace_id, Job.status.in_(["pending", "running"])
                )
            )
            if count >= settings().max_pending_jobs:
                raise HTTPException(429, "Workspace queue is full; wait for current jobs")
            version = (
                db.scalar(
                    select(func.coalesce(func.max(Document.version), 0)).where(
                        Document.workspace_id == user.workspace_id,
                        Document.source_key == source_key,
                    )
                )
                + 1
            )
            doc = Document(
                workspace_id=user.workspace_id,
                title=title[:240],
                content_hash=hashed,
                byte_size=len(body),
                content="",
                source_url=source_url,
                source_key=source_key,
                version=version,
                object_key=object_key,
                media_type=media_type,
            )
            db.add(doc)
            db.flush()
            enqueue(db, user.workspace_id, "ingest", doc.id)
            return doc
    except Exception:
        storage.remove(object_key)
        raise


@app.post("/v1/documents", response_model=DocumentOut, status_code=202)
def upload(file: UploadFile = File(...), user: User = Depends(writer)):
    rate_limit(f"upload:{user.workspace_id}", 20)
    body = file.file.read(settings().max_upload_bytes + 1)
    return add_document(user, body, file.content_type or "text/plain", file.filename or "Document")


@app.post("/v1/documents/url", response_model=DocumentOut, status_code=202)
def import_url(body: URLInput, user: User = Depends(writer)):
    rate_limit(f"upload:{user.workspace_id}", 20)
    try:
        content, media, final_url = fetch_public(body.url)
    except FetchError as error:
        raise HTTPException(422, str(error)) from error
    return add_document(user, content, media, body.title or final_url, final_url)


@app.get("/v1/documents", response_model=list[DocumentOut])
def documents(offset: int = 0, user: User = Depends(current_user)):
    with session() as db:
        return db.scalars(
            select(Document)
            .options(
                load_only(
                    Document.id,
                    Document.title,
                    Document.source_url,
                    Document.content_hash,
                    Document.version,
                    Document.status,
                    Document.error,
                    Document.chunk_count,
                    Document.created_at,
                )
            )
            .where(
                Document.workspace_id == user.workspace_id,
                Document.deleted.is_(False),
            )
            .order_by(Document.created_at.desc())
            .offset(max(0, offset))
            .limit(100)
        ).all()


@app.get("/v1/documents/{document_id}/passages")
def passages(document_id: str, offset: int = 0, user: User = Depends(current_user)):
    with session() as db:
        doc = scoped(db, Document, document_id, user)
        chunks = db.scalars(
            select(Chunk)
            .where(Chunk.document_id == doc.id)
            .order_by(Chunk.position)
            .offset(max(0, offset))
            .limit(50)
        ).all()
        return [{"id": c.id, "text": c.text, "page": c.page, "section": c.section} for c in chunks]


@app.get("/v1/documents/{document_id}/source")
def source_document(document_id: str, user: User = Depends(current_user)):
    with session() as db:
        doc = scoped(db, Document, document_id, user)
        key, title = doc.object_key, doc.title
    return Response(
        storage.get(key),
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": "attachment; filename*=UTF-8''"
            + __import__("urllib.parse", fromlist=["quote"]).quote(title),
        },
    )


@app.delete("/v1/documents/{document_id}", status_code=204)
def delete_document(document_id: str, user: User = Depends(writer)):
    with session() as db, db.begin():
        doc = scoped(db, Document, document_id, user)
        doc.deleted, doc.status = True, "deleted"
        affected = db.scalars(
            select(Run)
            .where(
                Run.workspace_id == user.workspace_id,
                cast(Run.evidence, JSONB).contains([{"document_id": doc.id}]),
            )
            .with_for_update()
        ).all()
        for run in affected:
            run.evidence = [e for e in run.evidence if e.get("document_id") != doc.id]
            run.answer = (
                "A supporting source was deleted. Re-run this research to generate a fresh brief."
            )
            deleted = list(dict.fromkeys([*run.diagnostics.get("deleted_documents", []), doc.id]))
            run.diagnostics = {**run.diagnostics, "deleted_documents": deleted}
            if run.status not in TERMINAL:
                run.cancel_requested = True
        enqueue(db, user.workspace_id, "cleanup", doc.id)


@app.post("/v1/documents/{document_id}/retry", response_model=DocumentOut)
def retry_document(document_id: str, user: User = Depends(writer)):
    rate_limit(f"ingest-retry:{user.workspace_id}", 10)
    with session() as db, db.begin():
        admit(db, check=False)
        doc = scoped(db, Document, document_id, user)
        if doc.status != "failed":
            raise HTTPException(409, "Only failed documents can be retried")
        admit(db)
        pending = db.scalar(
            select(func.count())
            .select_from(Job)
            .where(Job.workspace_id == user.workspace_id, Job.status.in_(["pending", "running"]))
        )
        if pending >= settings().max_pending_jobs:
            raise HTTPException(429, "Workspace queue is full", headers={"Retry-After": "30"})
        doc.status, doc.error = "pending", ""
        enqueue(db, user.workspace_id, "ingest", doc.id)
        return doc


@app.post("/v1/conversations", response_model=ConversationOut, status_code=201)
def create_conversation(body: ConversationInput, user: User = Depends(writer)):
    rate_limit(f"conversation-create:{user.workspace_id}", 20)
    with session() as db, db.begin():
        db.get(Workspace, user.workspace_id, with_for_update=True)
        count = db.scalar(
            select(func.count())
            .select_from(Conversation)
            .where(Conversation.workspace_id == user.workspace_id)
        )
        if count >= settings().max_workspace_conversations:
            raise HTTPException(429, "Workspace conversation limit reached")
        item = Conversation(workspace_id=user.workspace_id, title=body.title)
        db.add(item)
        db.flush()
        return item


@app.get("/v1/conversations", response_model=list[ConversationOut])
def conversations(user: User = Depends(current_user)):
    with session() as db:
        return db.scalars(
            select(Conversation)
            .where(Conversation.workspace_id == user.workspace_id)
            .order_by(Conversation.created_at.desc())
            .limit(100)
        ).all()


@app.post("/v1/runs", response_model=RunOut, status_code=202)
def create_run(body: RunInput, idempotency_key: str = Header(...), user: User = Depends(writer)):
    if not re.fullmatch(r"[a-zA-Z0-9_-]{8,100}", idempotency_key):
        raise HTTPException(422, "Idempotency-Key must be 8–100 URL-safe characters")
    try:
        providers.require_provider(body.provider, body.paid_consent)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    payload_hash = hashlib.sha256(body.model_dump_json().encode()).hexdigest()
    with session() as db, db.begin():
        admit(db, check=False)
        db.scalar(select(Workspace).where(Workspace.id == user.workspace_id).with_for_update())
        existing = db.scalar(
            select(Run).where(
                Run.workspace_id == user.workspace_id, Run.request_key == idempotency_key
            )
        )
        if existing:
            if existing.request_hash != payload_hash:
                raise HTTPException(409, "Idempotency key is already bound to another payload")
            return existing
        retained = db.scalar(
            select(func.count()).select_from(Run).where(Run.workspace_id == user.workspace_id)
        )
        if retained >= settings().max_workspace_runs:
            raise HTTPException(429, "Retained research limit reached; contact an operator")
        admit(db)
        conversation = scoped(db, Conversation, body.conversation_id, user)
        if body.parent_run_id:
            parent = scoped(db, Run, body.parent_run_id, user)
            if parent.conversation_id != conversation.id:
                raise HTTPException(422, "Continuation must stay in the same conversation")
        count = db.scalar(
            select(func.count())
            .select_from(Job)
            .where(Job.workspace_id == user.workspace_id, Job.status.in_(["pending", "running"]))
        )
        if count >= settings().max_pending_jobs:
            raise HTTPException(429, "Workspace queue is full")
        rate_limit(f"research:{user.workspace_id}", 20, db=db)
        item = Run(
            workspace_id=user.workspace_id,
            request_key=idempotency_key,
            request_hash=payload_hash,
            **body.model_dump(),
        )
        db.add(item)
        db.flush()
        enqueue(db, user.workspace_id, "research", item.id)
        event(db, item, "queued", {"provider": item.provider, "automatic_switch": False})
        if conversation.title == "New research":
            conversation.title = body.question[:80]
        return item


@app.get("/v1/runs", response_model=list[RunOut])
def runs(conversation_id: str | None = None, user: User = Depends(current_user)):
    with session() as db:
        query = select(Run).where(Run.workspace_id == user.workspace_id)
        if conversation_id:
            scoped(db, Conversation, conversation_id, user)
            query = query.where(Run.conversation_id == conversation_id)
        return db.scalars(query.order_by(Run.created_at.desc()).limit(50)).all()


@app.get("/v1/runs/{run_id}", response_model=RunOut)
def get_run(run_id: str, user: User = Depends(current_user)):
    with session() as db:
        return scoped(db, Run, run_id, user)


@app.post("/v1/runs/{run_id}/cancel", status_code=202)
def cancel_run(run_id: str, user: User = Depends(writer)):
    with session() as db, db.begin():
        run = scoped(db, Run, run_id, user)
        if run.status in TERMINAL:
            raise HTTPException(409, "Run already finished")
        run.cancel_requested = True
        event(db, run, "cancel_requested", {})
    return {"status": "cancellation_requested"}


@app.get("/v1/runs/{run_id}/events", response_model=list[EventOut])
def events(run_id: str, after: int = 0, user: User = Depends(current_user)):
    with session() as db:
        scoped(db, Run, run_id, user)
        return db.scalars(
            select(Event)
            .where(Event.run_id == run_id, Event.id > max(0, after))
            .order_by(Event.id)
            .limit(200)
        ).all()


@app.get("/v1/runs/{run_id}/stream")
async def stream(run_id: str, request: Request, after: int = 0, user: User = Depends(current_user)):
    get_run(run_id, user)
    try:
        cursor = max(after, int(request.headers.get("last-event-id", "0")))
    except ValueError:
        raise HTTPException(422, "Invalid event cursor") from None

    async def generate():
        nonlocal cursor
        for _ in range(600):
            if await request.is_disconnected():
                return
            # Session revocation/expiry is checked throughout a long-lived stream.
            try:
                await asyncio.to_thread(current_user, request)
            except HTTPException:
                return
            batch = await asyncio.to_thread(events, run_id, cursor, user)
            for item in batch:
                cursor = item.id
                value = EventOut.model_validate(item).model_dump_json()
                yield f"id: {item.id}\nevent: update\ndata: {value}\n\n"
            run = await asyncio.to_thread(get_run, run_id, user)
            if run.status in TERMINAL and not batch:
                yield "event: done\ndata: {}\n\n"
                return
            yield ": keepalive\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
    )


@app.get("/v1/runs/{run_id}/export")
def export(run_id: str, user: User = Depends(current_user)):
    run = get_run(run_id, user)
    if run.status != "completed":
        raise HTTPException(409, "Only completed runs can be exported")
    lines = [f"# {run.question}", "", run.answer, "", "## Sources", ""]
    for item in run.evidence:
        lines.append(
            f"[{item['citation']}] {item['title']} — page {item.get('page', 1)}\n"
            f"URL: {item.get('source_url') or 'Uploaded document'}\n"
            f"SHA-256: {item.get('content_hash', '')}\n"
        )
    lines.extend(
        [
            "## Run provenance",
            "",
            f"Provider: {run.provider}",
            f"Retrieval: {run.retrieval_mode}",
            f"Tokens: {run.token_usage}",
            "Factual support is not independently verified.",
        ]
    )
    return Response(
        "\n".join(lines),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="quarry-{run.id[:8]}.md"'},
    )


@app.post("/v1/search/compare", response_model=list[SearchResult])
def compare(body: SearchInput, user: User = Depends(current_user)):
    rate_limit(f"search:{user.workspace_id}", 20)
    return [
        retrieval.search(user.workspace_id, body.query, mode) for mode in dict.fromkeys(body.modes)
    ]


@app.get("/v1/evaluations")
def evaluations(user: User = Depends(current_user)):
    # Evaluation artifacts contain only the bundled public sample corpus, never tenant data.
    target = Path("/app/evaluation/results/latest.json")
    if not target.exists():
        return {
            "status": "not_run",
            "message": "Run the benchmark command to publish measured results",
            "results": [],
        }
    return json.loads(target.read_text())
