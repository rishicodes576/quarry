"""Explicit free-key evaluation. Every judge request passes through Quarry's budget ledger."""

import asyncio
import json
import time

import httpx
from sqlalchemy import select

from quarry import providers
from quarry.benchmark import ROOT, validate_dataset
from quarry.bootstrap import EVAL_WORKSPACE
from quarry.config import settings
from quarry.db import Conversation, Job, Run, session, uid
from quarry.queue import Heartbeat
from quarry.worker import process


def evaluation_run(question, conversation_id, provider="groq"):
    with session() as db, db.begin():
        row = Run(
            workspace_id=EVAL_WORKSPACE,
            conversation_id=conversation_id,
            question=question,
            provider=provider,
            request_key=uid(),
            request_hash="evaluation",
        )
        db.add(row)
        db.flush()
        job = Job(
            workspace_id=EVAL_WORKSPACE,
            target_id=row.id,
            kind="research",
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

    def __init__(self, conversation_id):
        self.conversation_id = conversation_id

    async def handle_async_request(self, request):
        if request.url.host != "api.groq.com" or not request.url.path.endswith("/chat/completions"):
            raise RuntimeError("Evaluation network policy rejected an unexpected endpoint")
        payload = json.loads(request.content)
        return await asyncio.to_thread(self._generate, request, payload)

    def _generate(self, request, payload):
        row, job = evaluation_run("Ragas judge request", self.conversation_id)
        try:
            with Heartbeat(job):
                content = providers.complete(job, payload["messages"], json_mode=True)
            with session() as db, db.begin():
                db.get(Job, job.id).status = "done"
                run = db.get(Run, row.id)
                run.status, run.finished_at = "completed", time.time()
            return httpx.Response(
                200,
                request=request,
                json={
                    "id": row.id,
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
        except providers.ProviderQuota as error:
            status, code = "quota_exhausted", 429
            message = str(error)
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
        with session() as db, db.begin():
            db.get(Job, job.id).status = "done"
            run = db.get(Run, row.id)
            run.status, run.error = status, message
        return httpx.Response(
            code, request=request, json={"error": {"message": message, "type": status}}
        )


async def evaluate_cases(output, cases, conversation_id):
    from openai import AsyncOpenAI
    from ragas.llms import llm_factory
    from ragas.metrics.collections import ContextPrecision, ContextRecall, Faithfulness

    transport = FreeJudgeTransport(conversation_id)
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
                row, job = evaluation_run(case["question"], conversation_id)
                process(job)
                with session() as db:
                    row = db.get(Run, row.id)
                    if row.status != "completed":
                        output["status"] = "partial"
                        output["stopped_reason"] = row.status
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
                    output["rows"].append(entry)
            for name, metric in metrics.items():
                if name in entry["metrics"]:
                    continue
                arguments = {
                    "user_input": case["question"],
                    "retrieved_contexts": entry["contexts"],
                }
                arguments["response" if name == "faithfulness" else "reference"] = (
                    entry["response"] if name == "faithfulness" else case["reference"]
                )
                try:
                    result = await metric.ascore(**arguments)
                    entry["metrics"][name] = float(result.value)
                    entry.setdefault("metric_configuration", {})[name] = {
                        "reasoning_effort": "low",
                        "reasoning_format": "hidden",
                        "max_completion_tokens": 2000,
                    }
                except Exception as error:
                    output["status"] = "partial"
                    output["stopped_reason"] = type(error).__name__
                    return
                save(output)
    output["status"] = "completed"


def save(output):
    (ROOT / "results/live-ragas.json").write_text(json.dumps(output, indent=2))


def run_live():
    cfg = settings()
    if not cfg.groq_api_key or not cfg.groq_free_plan_confirmed:
        raise SystemExit(
            "Live evaluation requires a locally configured Groq Free Plan key. No provider was called."
        )
    validate_dataset()
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
        asyncio.run(evaluate_cases(output, cases, conversation_id))
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
