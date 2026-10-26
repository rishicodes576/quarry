"""Operator-only isolated evaluation execution; separate from public report reading."""
import asyncio
import hashlib
import json
import os
import platform
import time
from datetime import UTC, datetime, timedelta
from importlib.metadata import version
from pathlib import Path

from quarry.campaigns import METRICS, MODES, ROOT, persist, read_report


def protocol(mode):
    from quarry.benchmark import validate_dataset
    from quarry.config import settings

    if mode not in MODES:
        raise ValueError("Unknown retrieval mode")
    manifest = validate_dataset()
    cases = [c for c in json.loads((ROOT / "cases.json").read_text()) if c["split"] == "test" and c["relevant_sources"]][:37]
    if len(cases) != 37:
        raise ValueError("Expected exactly 37 frozen selected cases")
    source = Path(__file__).parent
    files = ["agent.py", "providers.py", "retrieval.py", "encoders.py", "tools.py", "live_eval.py", "campaigns.py", "campaign_runner.py", "model_assets.py", "eval_guard.py"]
    assets = Path("/models/manifest.json")
    if not assets.exists():
        raise ValueError("Verified model asset manifest required before protocol freeze")
    from quarry.model_assets import verified_manifest

    if verified_manifest(assets.parent) is None:
        raise ValueError("Model asset hashes no longer match the prepared manifest")
    definition = {
        "version": "isolated-v2", "mode": mode, "dataset_sha256": manifest["sha256"],
        "case_ids": [c["id"] for c in cases], "provider": "groq", "model": settings().groq_model,
        "ragas": "0.4.3", "history_policy": "Independent research conversation per case/mode; separate judge conversation",
        "judge_cache_policy": "Exact model/messages/configuration hash reuse across the fixed sample workspace; original RPC conversation is exported and may be historical",
        "malformed_score_policy": "Reject nonfinite/out-of-range values, preserve raw RPCs and quarantine the last malformed judgment within this campaign; valid low/zero scores are retained",
        "temperature": 0, "reasoning_effort": "low", "reasoning_format": "hidden", "max_completion_tokens": 2000,
        "allow_web": False, "metrics": list(METRICS),
        "context_policy": "Precision/recall: first five retrieved passages; faithfulness: exact text passages supplied to generation",
        "execution_limits": {name: getattr(settings(), name) for name in ("max_model_calls", "max_tool_calls", "max_run_seconds", "embedding_mode")},
        "model_assets_sha256": hashlib.sha256(assets.read_bytes()).hexdigest(),
        "scorer_files_sha256": {name: hashlib.sha256(Path(path).read_bytes().replace(b"\r\n", b"\n")).hexdigest() for name, path in {
            "requirements.lock": "/app/requirements.lock", "requirements-eval.lock": "/app/requirements-eval.lock",
            "harden_eval.py": "/usr/local/share/quarry/harden_eval.py", "eval-hardening.json": "/usr/local/share/quarry/eval-hardening.json",
        }.items()},
        "scorer_package_versions": {name: version(name) for name in ("ragas", "instructor", "openai", "onnxruntime")},
        "implementation_sha256": {name: hashlib.sha256((source / name).read_bytes().replace(b"\r\n", b"\n")).hexdigest() for name in files},
    }
    digest = hashlib.sha256(json.dumps(definition, sort_keys=True).encode()).hexdigest()
    return definition, digest, cases


def run_isolated_once(mode):
    from quarry.bootstrap import EVAL_WORKSPACE
    from quarry.config import settings
    from quarry.db import Conversation, session
    from quarry.live_eval import evaluate_cases

    cfg = settings()
    if not cfg.groq_api_key or not cfg.groq_free_plan_confirmed or cfg.groq_model != "openai/gpt-oss-120b":
        raise SystemExit("Fixed Groq Free Plan model and local owner attestation required")
    definition, digest, cases = protocol(mode)
    campaign_id = "isolated-v2-" + mode
    report = read_report(campaign_id)
    if report is None:
        report = {
            "campaign_id": campaign_id, "protocol": "isolated-v2", "protocol_definition": definition,
            "protocol_sha256": digest, "mode": mode, "provider": "groq", "model": cfg.groq_model,
            "dataset_sha256": definition["dataset_sha256"], "requested_case_count": 37,
            "automatic_paid_switch": False, "rows": [], "status": "pending",
        }
    if report.get("protocol_sha256") != digest or report.get("protocol_definition") != definition:
        raise SystemExit("Frozen protocol changed; retain the report and create a new reviewed protocol version")
    if report["status"] == "completed":
        return report
    if "judge_conversation_id" not in report:
        with session() as db, db.begin():
            conversation = Conversation(workspace_id=EVAL_WORKSPACE, title=campaign_id + " judge only")
            db.add(conversation)
            db.flush()
            report["judge_conversation_id"] = conversation.id
    report["status"] = "running"
    for name in ("quota", "stopped_reason", "next_retry_at"):
        report.pop(name, None)
    report["started_at"] = report.get("started_at", datetime.now(UTC).isoformat())
    persist(report)
    from quarry.retrieval import warm_models

    began = time.perf_counter()
    warm_models()
    report.setdefault("sessions", []).append({
        "at": datetime.now(UTC).isoformat(), "platform": platform.platform(), "python": platform.python_version(),
        "logical_cpus": os.cpu_count(), "warmup_ms": round((time.perf_counter() - began) * 1000, 3),
        "conditions": "Warm local ONNX models; live provider; sequential inline worker. Graph latency excludes judge time and HTTP/browser delivery; first evidence is a durable event, not a generation token.",
    })
    ordinary = cfg.max_daily_tokens
    cfg.max_daily_tokens = min(cfg.max_evaluation_daily_tokens, cfg.max_global_daily_tokens)
    try:
        asyncio.run(evaluate_cases(report, cases, report["judge_conversation_id"], persist=persist, isolated=True, mode=mode))
    except Exception as error:
        report.update(status="partial", stopped_reason=type(error).__name__)
        raise
    finally:
        cfg.max_daily_tokens = ordinary
        if report["status"] == "completed":
            report["completed_at"] = datetime.now(UTC).isoformat()
        persist(report)
    return report


def run_suite(until_complete=False, campaign="all", modes=None):
    from quarry.live_eval import quota_wait_seconds, run_live, wait_for_quota_reset

    modes = list(modes or MODES)
    if campaign not in {"all", "legacy", "isolated-v2"} or not modes or len(modes) != len(set(modes)) or any(m not in MODES for m in modes):
        raise ValueError("Invalid campaign/mode selection")
    if campaign in {"legacy", "all"}:
        legacy = run_live(until_complete=until_complete)
        if campaign == "legacy" or legacy["status"] != "completed":
            return legacy
    import fcntl

    # Same lock as the legacy evaluator: never overlap metric writes or provider runs.
    with (ROOT / "results/.live-eval.lock").open("a") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit("Another live evaluation is already active") from None
        for mode in modes:
            for _ in range(64 if until_complete else 1):
                report = run_isolated_once(mode)
                if report["status"] == "completed":
                    break
                if not until_complete or not report.get("quota"):
                    return report
                now = datetime.now(UTC)
                delay = quota_wait_seconds(report["quota"], now)
                resume_at = now + timedelta(seconds=delay)
                report.update(status="quota_wait", next_retry_at=resume_at.isoformat())
                persist(report)
                wait_for_quota_reset(report["quota"], resume_at, delay)
            else:
                if not until_complete:
                    return report
                raise SystemExit("Bounded isolated campaign resume limit reached")
        return {"status": "completed", "campaign": campaign, "modes": modes}
