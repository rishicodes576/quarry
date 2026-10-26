"""Explicit free-key evaluation. Every judge request passes through Quarry's budget ledger."""

import asyncio
import hashlib
import json
import math
import os
import time
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select

from quarry import providers
from quarry.benchmark import ROOT, validate_dataset
from quarry.bootstrap import EVAL_WORKSPACE
from quarry.config import settings
from quarry.db import Conversation, Event, Job, Run, session, uid
from quarry.queue import Heartbeat, LeaseLost, fenced
from quarry.worker import process


def evaluation_run(question, conversation_id, provider="groq", parent_id=None, *, judge=False, mode="hybrid_rerank", isolated=False):
    with session() as db, db.begin():
        row = Run(
            workspace_id=EVAL_WORKSPACE,
            conversation_id=conversation_id,
            question=question,
            provider=provider,
            request_key=uid(),
            request_hash="evaluation",
            parent_run_id=parent_id,
            retrieval_mode=mode,
            diagnostics={"evaluation_protocol": "isolated-v2"} if isolated else {},
        )
        db.add(row)
        db.flush()
        job = Job(
            workspace_id=EVAL_WORKSPACE,
            target_id=row.id,
            kind="evaluation_judge" if judge else "research",
            status="running",
            lease_until=time.time() + settings().lease_seconds,
            fence=uid(),
            attempt=1,
        )
        db.add(job)
        db.flush()
        return row, job


class FreeJudgeTransport(httpx.AsyncBaseTransport):
    """Intercept the judge SDK and route exclusively to the budgeted free provider."""

    def __init__(self, conversation_id, rejected_run_ids=()):
        self.conversation_id = conversation_id
        self.lock = asyncio.Lock()
        self.next_call = 0.0
        self.last_quota = None
        self.cache_hits = 0
        self.requests = 0
        self.used_runs = []
        self.used_requests = []
        self.rejected_run_ids = set(rejected_run_ids)

    @staticmethod
    def cache_key(payload):
        # Bind reuse to everything actually sent by complete(), not SDK defaults it ignores.
        value = {
            "version": 1,
            "provider": "groq",
            "model": settings().groq_model,
            "messages": payload["messages"],
            "json_mode": True,
            "temperature": 0,
            "max_completion_tokens": 2000,
            "reasoning_effort": "low",
            "reasoning_format": "hidden",
        }
        return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()

    def cached(self, key):
        with session() as db:
            rows = db.scalars(
                select(Run)
                .where(
                    Run.workspace_id == EVAL_WORKSPACE,
                    Run.provider == "groq",
                    Run.question == "Ragas judge request",
                    Run.request_hash == key,
                    Run.status == "completed",
                )
                .order_by(Run.created_at)
            )
            for row in rows:
                if row.id in self.rejected_run_ids or row.diagnostics.get("judge_cache_version") != 1:
                    continue
                try:
                    value = json.loads(row.answer)
                except (ValueError, TypeError):
                    continue
                if isinstance(value, dict):
                    return row.id, row.answer
            return None

    @staticmethod
    def response(request, run_id, content):
        return httpx.Response(
            200,
            request=request,
            json={
                "id": run_id,
                "object": "chat.completion",
                "created": int(time.time()),
                "model": settings().groq_model,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": content},
                        "finish_reason": "stop",
                    }
                ],
            },
        )

    async def handle_async_request(self, request):
        if request.url.host != "api.groq.com" or not request.url.path.endswith("/chat/completions"):
            raise RuntimeError("Evaluation network policy rejected an unexpected endpoint")
        payload = json.loads(request.content)
        self.last_quota = None
        key = self.cache_key(payload)
        async with self.lock:
            cached = await asyncio.to_thread(self.cached, key)
            if cached:
                self.cache_hits += 1
                self.used_runs.append(cached[0])
                self.used_requests.append({"run_id": cached[0], "request_sha256": key})
                return self.response(request, *cached)
            parent_id = None
            for attempt in range(4):
                # Benchmark-only pacing; API workers never hold a lease while waiting here.
                # Benchmark-only pacing is configurable; provider 429s still impose
                # at least 60 seconds of backoff, and daily reservations stay enforced.
                while (remaining := self.next_call - time.monotonic()) > 0:
                    await asyncio.sleep(min(30, remaining))
                result = await asyncio.to_thread(self._generate, request, payload, key, parent_id)
                self.requests += 1
                if result.status_code == 200:
                    self.used_runs.append(result.json()["id"])
                    self.used_requests.append({"run_id": result.json()["id"], "request_sha256": key})
                    self.last_quota = None
                self.next_call = time.monotonic() + settings().evaluation_pace_seconds
                if result.status_code != 429:
                    return result
                detail = result.json()["error"]
                self.last_quota = detail
                if detail["scope"] != "provider" or detail["retry_after"] > 120 or attempt == 3:
                    return result
                parent_id = detail["run_id"]
                self.next_call = time.monotonic() + max(60, detail["retry_after"] + 2)
                print(
                    json.dumps(
                        {
                            "event": "judge_rate_pause",
                            "attempt": attempt + 1,
                            "seconds": max(60, detail["retry_after"] + 2),
                        }
                    ),
                    flush=True,
                )
            raise AssertionError("Bounded retry loop exhausted")

    def _generate(self, request, payload, key, parent_id=None):
        row, job = evaluation_run("Ragas judge request", self.conversation_id, judge=True)
        with session() as db, db.begin():
            run = db.get(Run, row.id)
            run.request_hash, run.parent_run_id = key, parent_id
        try:
            with Heartbeat(job):
                content = providers.complete(job, payload["messages"], json_mode=True)
            if not isinstance(json.loads(content), dict):
                raise providers.ProviderFailure("Judge returned a non-object JSON response")
            with fenced(job) as (db, current):
                current.status = "done"
                run = db.get(Run, row.id)
                run.status, run.finished_at = "completed", time.time()
                run.answer = content
                run.diagnostics = {**run.diagnostics, "judge_cache_version": 1}
            return self.response(request, row.id, content)
        except providers.ProviderQuota as error:
            status, code = "quota_exhausted", 429
            message = str(error)
            quota = {"scope": error.scope, "retry_after": error.retry_after, "run_id": row.id}
        except Exception as error:
            status, code = "failed", 503
            message = "Free evaluation request failed: " + type(error).__name__
            if isinstance(error, providers.ProviderFailure):
                message += ": " + str(error)
            print(
                json.dumps(
                    {
                        "event": "judge_failed",
                        "reason": message,
                        "input_bytes": sum(
                            len(m.get("content", "").encode()) for m in payload["messages"]
                        ),
                    }
                ),
                flush=True,
            )
        try:
            with fenced(job) as (db, current):
                current.status = "done"
                run = db.get(Run, row.id)
                run.status, run.error = status, message
                run.finished_at = time.time()
        except LeaseLost:
            # The lease owner/recovery worker now owns this result and its reservation.
            pass
        return httpx.Response(
            code,
            request=request,
            json={"error": {"message": message, "type": status, **(quota if code == 429 else {})}},
        )


def checked_score(value, output, transport, *, isolated=False, request_start=0):
    score = float(value)
    if not math.isfinite(score) or not 0 <= score <= 1:
        # Empty structured judgments can produce NaN in Ragas. Preserve the raw
        # RPC but do not reuse that final malformed judgment forever on resume.
        if isolated and len(transport.used_runs) > request_start:
            rejected = transport.used_runs[-1]
            transport.rejected_run_ids.add(rejected)
            output["rejected_judge_runs"] = sorted(transport.rejected_run_ids)
        raise ValueError("Judge returned a nonfinite or out-of-range score")
    return score


async def evaluate_cases(output, cases, conversation_id, *, persist=None, isolated=False, mode="hybrid_rerank"):
    from openai import AsyncOpenAI
    from ragas.llms import llm_factory
    from ragas.metrics.collections import ContextPrecision, ContextRecall, Faithfulness

    persist = persist or save
    # For isolated campaigns this is a dedicated judge conversation. Research uses
    # a separate durable conversation per case; RPC outputs never become history.
    transport = FreeJudgeTransport(conversation_id, output.get("rejected_judge_runs", []))
    async with httpx.AsyncClient(transport=transport, timeout=60) as http_client:
        client = AsyncOpenAI(
            api_key=settings().groq_api_key,
            base_url="https://api.groq.com/openai/v1",
            max_retries=0,
            http_client=http_client,
        )
        # Ragas' OpenAI-compatible adapter already patches Instructor in JSON mode.
        # Passing `mode` here forwards it to the raw completion API and is invalid.
        judge = llm_factory(settings().groq_model, client=client, max_retries=1)
        metrics = {
            "context_precision": ContextPrecision(llm=judge),
            "context_recall": ContextRecall(llm=judge),
            "faithfulness": Faithfulness(llm=judge),
        }
        for case in cases:
            entry = next((r for r in output["rows"] if r["case_id"] == case["id"]), None)
            if entry is None:
                research_conversation = conversation_id
                pending_id = output.setdefault("pending_case_runs", {}).get(case["id"])
                parent_id = None
                if pending_id:
                    with session() as db:
                        previous = db.get(Run, pending_id)
                        if previous is None:
                            raise ValueError("Saved evaluation run is missing; restore its database before resuming")
                        if isolated:
                            research_conversation = previous.conversation_id
                            if output.get("case_conversations", {}).get(case["id"]) != research_conversation:
                                raise ValueError("Saved case conversation binding changed")
                        if previous.status in {"quota_exhausted", "failed", "cancelled"}:
                            # Invoking --live again is an explicit same-provider continuation.
                            parent_id, pending_id = pending_id, None
                if not pending_id:
                    if isolated:
                        # A crash can commit a run before its JSON receipt is saved.
                        # Never reuse that conversation for another generation attempt.
                        with session() as db, db.begin():
                            conversation = Conversation(workspace_id=EVAL_WORKSPACE, title=f"{output['campaign_id']} {case['id']}")
                            db.add(conversation)
                            db.flush()
                            research_conversation = conversation.id
                        output.setdefault("case_conversations", {})[case["id"]] = research_conversation
                        persist(output)
                    row, job = evaluation_run(
                        case["question"], research_conversation, parent_id=parent_id, mode=mode, isolated=isolated
                    )
                    pending_id = row.id
                    output["pending_case_runs"][case["id"]] = pending_id
                    persist(output)
                    process(job)
                deadline = time.monotonic() + settings().max_run_seconds + settings().lease_seconds
                while True:
                    with session() as db:
                        state = db.get(Run, pending_id).status
                    if state not in {"queued", "running"} or time.monotonic() >= deadline:
                        break
                    await asyncio.sleep(1)
                with session() as db:
                    row = db.get(Run, pending_id)
                    if row.status != "completed":
                        output["status"] = "partial"
                        output["stopped_reason"] = row.status
                        if row.status == "quota_exhausted":
                            output["quota"] = {
                                "scope": row.diagnostics.get("quota_scope", "provider"),
                                "retry_after": row.diagnostics.get("retry_after", 60),
                                "run_id": row.id,
                            }
                        return
                    entry = {
                        "case_id": case["id"],
                        "run_id": row.id,
                        "response": row.answer,
                        "contexts": [e["text"] for e in row.evidence[:5]],
                        "metrics": {},
                        "latency_ms": row.diagnostics.get("total_ms"),
                        "tokens": row.token_usage,
                    }
                    if isolated:
                        first = db.scalar(
                            select(Event.created_at).where(
                                Event.run_id == row.id,
                                Event.kind == "stage_completed",
                                Event.payload["stage"].as_string() == "retrieve",
                            ).order_by(Event.id).limit(1)
                        )
                        entry.update(
                            question=case["question"],
                            reference=case["reference"],
                            conversation_id=row.conversation_id,
                            mode=row.retrieval_mode,
                            evidence=row.evidence[:5],
                            response_sha256=hashlib.sha256(row.answer.encode()).hexdigest(),
                            generation_request_sha256=row.diagnostics.get("generation_request_sha256", []),
                            model_calls=row.model_calls,
                            history_run_ids=row.diagnostics.get("history_run_ids"),
                            first_evidence_ms=round((first - row.created_at) * 1000, 3) if first is not None else None,
                            completed_at=datetime.now(UTC).isoformat(),
                            answer_contexts=[e["text"][:1200] for e in sorted(row.evidence, key=lambda e: e.get("kind") != "calculation")[:6]],
                            answer_kind=row.diagnostics.get("answer_kind", "unknown"),
                        )
                    output["rows"].append(entry)
                    output["pending_case_runs"].pop(case["id"], None)
                    persist(output)
            for name, metric in metrics.items():
                if name in entry["metrics"]:
                    continue
                arguments = {
                    "user_input": case["question"],
                    "retrieved_contexts": entry.get("answer_contexts", entry["contexts"]) if name == "faithfulness" else entry["contexts"],
                }
                arguments["response" if name == "faithfulness" else "reference"] = (
                    entry["response"] if name == "faithfulness" else case["reference"]
                )
                try:
                    request_start = len(transport.used_runs)
                    result = await metric.ascore(**arguments)
                    score = checked_score(result.value, output, transport, isolated=isolated, request_start=request_start)
                    entry["metrics"][name] = score
                    entry.setdefault("metric_configuration", {})[name] = {
                        "provider": "groq",
                        "model": settings().groq_model,
                        "reasoning_effort": "low",
                        "reasoning_format": "hidden",
                        "max_completion_tokens": 2000,
                        "judge_run_ids": transport.used_runs[request_start:],
                    }
                    if isolated:
                        entry["metric_configuration"][name]["judge_requests"] = transport.used_requests[request_start:]
                        entry["metric_configuration"][name]["arguments_sha256"] = hashlib.sha256(
                            json.dumps(arguments, sort_keys=True).encode()
                        ).hexdigest()
                except Exception as error:
                    output["status"] = "partial"
                    output["stopped_reason"] = type(error).__name__
                    output["quota"] = transport.last_quota
                    output["judge_transport"] = {
                        "cache_hits": transport.cache_hits,
                        "requests": transport.requests,
                    }
                    return
                output["judge_transport"] = {
                    "cache_hits": transport.cache_hits,
                    "requests": transport.requests,
                }
                print(
                    json.dumps(
                        {
                            "event": "judge_metric_completed",
                            "case_id": case["id"],
                            "metric": name,
                            "value": entry["metrics"][name],
                        }
                    ),
                    flush=True,
                )
                persist(output)
    output["status"] = "completed"
    output.pop("stopped_reason", None)
    output.pop("quota", None)
    output.pop("next_retry_at", None)


def save(output):
    path = ROOT / "results/live-ragas.json"
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(output, indent=2))
    os.replace(temporary, path)


def quota_wait_seconds(quota, now):
    if quota["scope"] in {"workspace", "deployment"}:
        reset = (now + timedelta(days=1)).replace(hour=0, minute=1, second=0, microsecond=0)
        return max(60, int((reset - now).total_seconds()))
    return min(86400, max(60, int(quota.get("retry_after", 60)) + 2))


def wait_for_quota_reset(quota, resume_at, delay):
    if quota["scope"] in {"workspace", "deployment"}:
        # Daily ledgers use UTC dates. VM/host suspension can stop the monotonic
        # clock, so an elapsed-time wait can miss an already-passed UTC reset.
        while (remaining := (resume_at - datetime.now(UTC)).total_seconds()) > 0:
            time.sleep(min(30, remaining))
    else:
        # Provider retry hints are elapsed durations, independent of wall-clock edits.
        deadline = time.monotonic() + delay
        while (remaining := deadline - time.monotonic()) > 0:
            time.sleep(min(30, remaining))


def run_live(until_complete=False):
    # Compose uses Linux. Keep two benchmark processes from overwriting the same campaign.
    import fcntl

    with (ROOT / "results/.live-eval.lock").open("a") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit("Another live evaluation is already active") from None
        for _ in range(64 if until_complete else 1):
            output = _run_live_locked()
            if output["status"] == "completed" or not until_complete or not output.get("quota"):
                return output
            now = datetime.now(UTC)
            delay = quota_wait_seconds(output["quota"], now)
            resume_at = now + timedelta(seconds=delay)
            output.update(status="quota_wait", next_retry_at=resume_at.isoformat())
            save(output)
            print(
                json.dumps(
                    {
                        "event": "campaign_quota_wait",
                        "next_retry_at": output["next_retry_at"],
                        "scope": output["quota"]["scope"],
                        "automatic_provider_switch": False,
                    }
                ),
                flush=True,
            )
            wait_for_quota_reset(output["quota"], resume_at, delay)
        raise SystemExit("Campaign reached its bounded 64-resume limit; inspect the saved report")


def _run_live_locked():
    cfg = settings()
    if not cfg.groq_api_key or not cfg.groq_free_plan_confirmed:
        raise SystemExit(
            "Live evaluation requires a locally configured Groq Free Plan key. No provider was called."
        )
    manifest = validate_dataset()
    if not (ROOT / "results/latest.json").exists():
        raise SystemExit("Run the no-key retrieval benchmark first.")
    cases = [
        c
        for c in json.loads((ROOT / "cases.json").read_text())
        if c["split"] == "test" and c["relevant_sources"]
    ][:37]
    path = ROOT / "results/live-ragas.json"
    output = (
        json.loads(path.read_text())
        if path.exists()
        else {
            "status": "running",
            "provider": "groq",
            "model": cfg.groq_model,
            "judge_independence": "Same free model family; scores require manual corroboration",
            "automatic_paid_switch": False,
            "requested_case_count": len(cases),
            "rows": [],
        }
    )
    if output["provider"] != "groq" or output["model"] != cfg.groq_model:
        raise SystemExit(
            "Saved campaign uses a different provider/model; archive it before a new campaign"
        )
    dataset = manifest["sha256"]
    if output.get("dataset_sha256", dataset) != dataset:
        raise SystemExit("Saved campaign uses a different frozen dataset; archive it first")
    output["dataset_sha256"] = dataset
    output["status"] = "running"
    output.pop("stopped_reason", None)
    output.pop("quota", None)
    save(output)
    with session() as db, db.begin():
        conversation = db.scalar(
            select(Conversation).where(
                Conversation.workspace_id == EVAL_WORKSPACE, Conversation.title == "Free evaluation"
            )
        )
        if not conversation:
            conversation = Conversation(workspace_id=EVAL_WORKSPACE, title="Free evaluation")
            db.add(conversation)
            db.flush()
        conversation_id = conversation.id
    try:
        # This operator-only process uses a finite campaign allowance for its dedicated
        # workspace. The shared ledger cap still applies, and ordinary API limits stay intact.
        ordinary_limit = cfg.max_daily_tokens
        cfg.max_daily_tokens = min(cfg.max_evaluation_daily_tokens, cfg.max_global_daily_tokens)
        output["campaign_daily_token_limit"] = cfg.max_daily_tokens
        output["shared_daily_token_limit"] = cfg.max_global_daily_tokens
        output["judge_pacing_seconds"] = cfg.evaluation_pace_seconds
        try:
            asyncio.run(evaluate_cases(output, cases, conversation_id))
        finally:
            cfg.max_daily_tokens = ordinary_limit
    finally:
        save(output)
    print(
        json.dumps(
            {
                "status": output["status"],
                "completed_cases": sum(len(r["metrics"]) == 3 for r in output["rows"]),
                "reason": output.get("stopped_reason"),
                "paid_calls": 0,
            }
        )
    )
    return output
