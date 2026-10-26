"""Fixed synthetic-corpus campaign registry, isolated protocols and free-only execution."""

import json
import math
import os
import statistics
from pathlib import Path

from quarry.schemas import CampaignCaseOut, CampaignDetail, CampaignSummary

ROOT = Path("/app/evaluation")
MODES = ("dense", "bm25", "hybrid", "hybrid_rerank")
IDS = ("legacy", *("isolated-v2-" + mode for mode in MODES))
METRICS = ("context_precision", "context_recall", "faithfulness")


def report_path(campaign_id):
    if campaign_id not in IDS:
        raise ValueError("Unknown evaluation campaign")
    return ROOT / "results" / ("live-ragas.json" if campaign_id == "legacy" else campaign_id + ".json")


def read_report(campaign_id):
    path = report_path(campaign_id)
    if not path.exists():
        return None
    if path.is_symlink() or path.stat().st_size > 16 * 1024 * 1024:
        raise ValueError("Invalid evaluation report")
    value = json.loads(path.read_text())
    if not isinstance(value, dict) or not isinstance(value.get("rows"), list):
        raise ValueError("Invalid evaluation report")
    if (value.get("requested_case_count") != 37 or value.get("provider") != "groq"
            or value.get("model") != "openai/gpt-oss-120b"
            or value.get("status") not in {"pending", "running", "partial", "quota_wait", "completed"}):
        raise ValueError("Invalid evaluation identity/status")
    ids = []
    for row in value["rows"]:
        parsed = CampaignCaseOut.model_validate(row)
        ids.append(parsed.case_id)
    if len(ids) != len(set(ids)) or len(ids) > 37:
        raise ValueError("Invalid evaluation case matrix")
    if campaign_id != "legacy" and (value.get("campaign_id") != campaign_id or value.get("mode") != campaign_id.removeprefix("isolated-v2-") or value.get("protocol") != "isolated-v2"):
        raise ValueError("Invalid isolated campaign identity")
    if value["status"] == "completed" and (len(ids) != 37 or any(set(r["metrics"]) != set(METRICS) for r in value["rows"])):
        raise ValueError("Completed campaign lacks scored cases")
    return value


def persist(report):
    path = report_path(report["campaign_id"])
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(report, indent=2, allow_nan=False))
    os.replace(temporary, path)


def summaries():
    return [describe(campaign_id) for campaign_id in IDS]


def describe(campaign_id):
    report = read_report(campaign_id)
    if report is None:
        return CampaignSummary(id=campaign_id, mode="hybrid_rerank" if campaign_id == "legacy" else campaign_id.removeprefix("isolated-v2-"), protocol="legacy-shared-conversation" if campaign_id == "legacy" else "isolated-v2")
    complete = [r for r in report["rows"] if set(r.get("metrics", {})) == set(METRICS)]
    scores = [v for r in complete for v in r["metrics"].values()]
    if any(type(v) not in {int, float} or not math.isfinite(v) or not 0 <= v <= 1 for v in scores):
        raise ValueError("Invalid evaluation scores")
    return CampaignSummary(
        id=campaign_id, mode=report.get("mode", "hybrid_rerank"),
        protocol=report.get("protocol", "legacy-shared-conversation"),
        status=report.get("status", "partial"), completed=len(complete),
        requested=report["requested_case_count"], provider=report["provider"], model=report["model"],
        next_retry_at=report.get("next_retry_at"),
        quota_scope=(report.get("quota") or {}).get("scope"),
        stopped_reason=report.get("stopped_reason"),
        means={name: statistics.mean(r["metrics"][name] for r in complete) for name in METRICS} if complete else {},
        protocol_sha256=report.get("protocol_sha256"),
        provenance_gaps=sum(not c.get("judge_run_ids") for r in complete for c in [r.get("metric_configuration", {}).get(m, {}) for m in METRICS]),
        limitations=["Synthetic authored labels; same-family model judge; not independent human validation"]
        + (["Historical shared conversation and mixed legacy configurations; excluded from isolated comparisons"] if campaign_id == "legacy" else []),
    )


def detail(campaign_id):
    summary = describe(campaign_id)
    report = read_report(campaign_id)
    # Only explicitly typed public sample fields are serialized. No diagnostic or
    # environment dictionaries are exposed through this API.
    rows = [] if report is None else [CampaignCaseOut.model_validate(r) for r in report["rows"]]
    return CampaignDetail(**summary.model_dump(), rows=rows, configuration=report.get("protocol_definition") if report else None)


