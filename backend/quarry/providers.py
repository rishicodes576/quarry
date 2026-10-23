import json
import time
from datetime import UTC, datetime

import httpx
from sqlalchemy.dialects.postgresql import insert

from quarry.config import settings
from quarry.db import Run, UsageDay
from quarry.queue import check_run, event, fenced

# Input is capped at 14,000 UTF-8 bytes, at most 12 messages, and 2,000 output tokens.
# Reserve a conservative upper bound, then release unused tokens after a known response.
RESERVATION = 17_000


class ProviderQuota(RuntimeError):
    def __init__(
        self,
        message="Free quota exhausted; retry later or explicitly choose another configured provider",
        retry_after=60,
        scope="provider",
    ):
        super().__init__(message)
        self.retry_after = retry_after
        self.scope = scope


class ProviderFailure(RuntimeError):
    pass


def provider_status() -> list[dict]:
    cfg = settings()
    return [
        {
            "id": "extractive",
            "name": "Local evidence",
            "available": True,
            "paid": False,
            "description": "Real retrieval and cited excerpts. No language model or API key.",
        },
        {
            "id": "groq",
            "name": "Groq · Free Plan",
            "paid": False,
            "available": bool(cfg.groq_api_key and cfg.groq_free_plan_confirmed),
            "description": "Your Free Plan key. Stops when the quota is exhausted.",
        },
        {
            "id": "openai",
            "name": "Optional paid provider",
            "paid": True,
            "available": bool(cfg.allow_paid_providers and cfg.openai_api_key),
            "description": "Owner-configured only. Requires explicit consent on every run.",
        },
    ]


def require_provider(name: str, consent: bool):
    status = next((p for p in provider_status() if p["id"] == name), None)
    if not status or not status["available"]:
        raise ValueError("Provider is unavailable; configure it server-side first")
    if status["paid"] and not consent:
        raise ValueError("Paid generation requires explicit consent for this run")


def reserve(job):
    check_run(job)
    day = datetime.now(UTC).date().isoformat()
    with fenced(job) as (db, _):
        run = db.get(Run, job.target_id)
        if run.model_calls >= settings().max_model_calls:
            raise ProviderFailure("Model-call budget exhausted")
        day_id = f"{run.workspace_id}:{day}"
        global_id = f"global:{day}"
        db.execute(
            insert(UsageDay)
            .values(id=global_id, workspace_id="global", day=day)
            .on_conflict_do_nothing()
        )
        global_row = db.get(UsageDay, global_id, with_for_update=True)
        if (
            global_row.tokens + global_row.reserved + RESERVATION
            > settings().max_global_daily_tokens
        ):
            raise ProviderQuota(
                "Shared deployment token budget exhausted; no provider switch was attempted",
                3600,
                scope="deployment",
            )
        db.execute(
            insert(UsageDay)
            .values(
                id=day_id,
                workspace_id=run.workspace_id,
                day=day,
            )
            .on_conflict_do_nothing()
        )
        row = db.get(UsageDay, day_id, with_for_update=True)
        if row.tokens + row.reserved + RESERVATION > settings().max_daily_tokens:
            raise ProviderQuota(
                "Workspace token budget exhausted; retry after the UTC daily reset",
                3600,
                scope="workspace",
            )
        if run.reserved_tokens:
            raise ProviderFailure("An unsettled model reservation requires worker recovery")
        row.reserved += RESERVATION
        global_row.reserved += RESERVATION
        run.reserved_tokens = RESERVATION
        run.model_calls += 1
        run.diagnostics = {
            **run.diagnostics,
            "reservation_day": day_id,
            "global_reservation_day": global_id,
        }


def settle(job, actual: int | None, *, quota: bool = False):
    with fenced(job) as (db, _):
        settle_run(db, db.get(Run, job.target_id), actual, quota=quota)


def settle_run(db, run: Run, actual: int | None, *, quota: bool = False):
    if not run.reserved_tokens:
        return
    day_id = run.diagnostics.get("reservation_day")
    charge = 0 if quota else (actual if actual is not None else run.reserved_tokens)
    for ledger_id in [run.diagnostics.get("global_reservation_day"), day_id]:
        if ledger_id:
            row = db.get(UsageDay, ledger_id, with_for_update=True)
            if row:
                row.reserved = max(0, row.reserved - run.reserved_tokens)
                row.tokens += charge
    run.billed_tokens += charge
    if actual is not None:
        run.token_usage += actual
    if quota:
        run.model_calls = max(0, run.model_calls - 1)
    if actual is None and not quota:
        run.diagnostics = {**run.diagnostics, "usage_unknown": True}
    run.reserved_tokens = 0


def complete(job, messages: list[dict], *, json_mode=False, transport=None) -> str:
    cfg = settings()
    with fenced(job) as (db, _):
        run = db.get(Run, job.target_id)
        name, consent = run.provider, run.paid_consent
    require_provider(name, consent)
    # The builder's default configuration makes paid endpoints unreachable.
    if name == "groq":
        endpoint, key, model = (
            "https://api.groq.com/openai/v1/chat/completions",
            cfg.groq_api_key,
            cfg.groq_model,
        )
    elif name == "openai" and cfg.allow_paid_providers and consent:
        endpoint, key, model = (
            "https://api.openai.com/v1/chat/completions",
            cfg.openai_api_key,
            cfg.openai_model,
        )
    else:
        raise ProviderFailure("This mode does not support generation")
    # Conservative byte-bound input cap prevents unexpectedly large contexts.
    if not 1 <= len(messages) <= 12 or any(
        m.get("role") not in {"system", "user", "assistant"}
        or not isinstance(m.get("content"), str)
        for m in messages
    ):
        raise ProviderFailure("Invalid model message envelope")
    if sum(len(m["content"].encode()) for m in messages) > 14_000:
        raise ProviderFailure("Model input exceeds the per-call context budget")
    payload = {
        "model": model,
        "messages": messages,
        "max_completion_tokens": 2000,
        "temperature": 0,
    }
    if name == "groq" and model.startswith("openai/gpt-oss-"):
        payload.update(reasoning_effort="low", reasoning_format="hidden")
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    reserve(job)
    started = time.perf_counter()
    try:
        with httpx.Client(
            timeout=httpx.Timeout(45, connect=8), trust_env=False, transport=transport
        ) as client:
            response = client.post(
                endpoint, headers={"Authorization": f"Bearer {key}"}, json=payload
            )
        if response.status_code == 429:
            settle(job, 0, quota=True)
            try:
                retry_after = min(86400, max(1, int(response.headers.get("retry-after", "60"))))
            except ValueError:
                retry_after = 60
            with fenced(job) as (db, _):
                run = db.get(Run, job.target_id)
                run.diagnostics = {
                    **run.diagnostics,
                    "quota": {"scope": "provider", "retry_after": retry_after},
                }
                event(
                    db,
                    run,
                    "provider_quota",
                    {"provider": name, "retry_after": retry_after, "scope": "provider"},
                )
            raise ProviderQuota(retry_after=retry_after)
        if response.status_code >= 400:
            settle(job, 0)
            code = "unclassified"
            try:
                candidate = response.json().get("error", {}).get("code")
                if candidate in {
                    "json_validate_failed",
                    "context_length_exceeded",
                    "invalid_request_error",
                    "model_not_found",
                }:
                    code = candidate
            except (ValueError, AttributeError, TypeError):
                pass
            with fenced(job) as (db, _):
                event(
                    db,
                    db.get(Run, job.target_id),
                    "provider_failure",
                    {"provider": name, "status": response.status_code, "code": code},
                )
            raise ProviderFailure(
                f"Provider returned HTTP {response.status_code} ({code}); no fallback was used"
            )
        data = response.json()
        usage = data.get("usage", {}).get("total_tokens")
        actual = int(usage) if isinstance(usage, (int, float)) and usage >= 0 else None
        settle(job, actual)
        content = data["choices"][0]["message"]["content"]
        if not isinstance(content, str) or not content.strip():
            raise ProviderFailure("Provider returned an empty answer")
        with fenced(job) as (db, _):
            run = db.get(Run, job.target_id)
            event(
                db,
                run,
                "model",
                {
                    "provider": name,
                    "model": model,
                    "tokens": actual,
                    "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                },
            )
        return content
    except ProviderQuota:
        raise
    except ProviderFailure:
        raise
    except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as error:
        settle(job, None)
        raise ProviderFailure(
            "Provider failed; progress is retained and no alternate provider was called"
        ) from error


def parse_plan(value: str) -> dict:
    try:
        plan = json.loads(value)
        if not isinstance(plan, dict):
            raise ValueError
        tools = plan.get("tools", [])
        if not isinstance(tools, list):
            raise ValueError
        allowed = {"web_search", "wikipedia", "fetch_url", "calculate"}
        clean = []
        for tool in tools[: settings().max_tool_calls]:
            if not isinstance(tool, dict) or tool.get("name") not in allowed:
                continue
            argument = tool.get("argument")
            if isinstance(argument, str) and 0 < len(argument) <= 1000:
                clean.append({"name": tool["name"], "argument": argument})
        return {
            "tools": clean,
            "summary": str(plan.get("summary", "Research supplied evidence"))[:300],
        }
    except (ValueError, TypeError):
        raise ProviderFailure("Provider returned an invalid research plan") from None
