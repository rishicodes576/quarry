"""Reproducible retrieval evaluation. Default execution has no generation-provider calls."""

import argparse
import asyncio
import hashlib
import json
import math
import platform
import statistics
import time
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

from sqlalchemy import select

from quarry.bootstrap import EVAL_WORKSPACE, seed_corpus
from quarry.db import Document, session
from quarry.retrieval import search, warm_models

ROOT = Path("/app/evaluation")


@lru_cache
def id_metrics():
    from ragas.metrics import IDBasedContextPrecision, IDBasedContextRecall

    return IDBasedContextPrecision(), IDBasedContextRecall()


async def ragas_id_scores(ranked, reference):
    from ragas.dataset_schema import SingleTurnSample

    sample = SingleTurnSample(
        retrieved_context_ids=list(dict.fromkeys(ranked))[:5], reference_context_ids=reference
    )
    precision, recall = id_metrics()
    return {
        "ragas_id_precision": await precision.single_turn_ascore(sample),
        "ragas_id_recall": await recall.single_turn_ascore(sample),
    }


def percentile(values, fraction):
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def score_sources(ranked: list[str], relevant: list[str], k=5):
    unique = list(dict.fromkeys(ranked))[:k]
    truth = set(relevant)
    if not truth:
        return None
    matches = [1 if source in truth else 0 for source in unique]
    recall = len(set(unique) & truth) / len(truth)
    mrr = next((1 / (i + 1) for i, value in enumerate(matches) if value), 0)
    dcg = sum(value / math.log2(i + 2) for i, value in enumerate(matches))
    ideal = sum(1 / math.log2(i + 2) for i in range(min(len(truth), k)))
    return {
        "recall_at_5": recall,
        "mrr": mrr,
        "ndcg_at_5": dcg / ideal,
        "precision_at_5": sum(matches) / max(1, len(unique)),
    }


def validate_dataset():
    manifest = json.loads((ROOT / "manifest.json").read_text())
    for name, expected in manifest["sha256"].items():
        if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != expected:
            raise ValueError(
                "Frozen evaluation dataset changed; create a new version before evaluating"
            )
    return manifest


def run(split="all"):
    manifest = validate_dataset()
    seed_corpus(EVAL_WORKSPACE, "Frozen benchmark corpus")
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        with session() as db:
            docs = db.scalars(
                select(Document).where(
                    Document.workspace_id == EVAL_WORKSPACE, Document.deleted.is_(False)
                )
            ).all()
            if docs and all(doc.status == "ready" for doc in docs):
                by_id = {doc.id: doc.source_key.removeprefix("sample:") for doc in docs}
                break
            if any(doc.status == "failed" for doc in docs):
                raise RuntimeError("Benchmark ingestion failed; inspect worker logs")
        time.sleep(1)
    else:
        raise TimeoutError("Benchmark indexing did not finish within five minutes")
    cases = json.loads((ROOT / "cases.json").read_text())
    if split != "all":
        cases = [case for case in cases if case["split"] == split]
    cold_started = time.perf_counter()
    warm_models()
    warmup_ms = (time.perf_counter() - cold_started) * 1000
    rows, summaries = [], []
    for mode in ["dense", "bm25", "hybrid", "hybrid_rerank"]:
        measured = []
        scored = []
        for case in cases:
            started = time.perf_counter()
            try:
                result = search(EVAL_WORKSPACE, case["question"], mode, limit=20)
                elapsed = (time.perf_counter() - started) * 1000
                sources = [by_id[h["document_id"]] for h in result["hits"]]
                metrics = score_sources(sources, case["relevant_sources"])
                if metrics:
                    metrics.update(asyncio.run(ragas_id_scores(sources, case["relevant_sources"])))
                rows.append(
                    {
                        "id": case["id"],
                        "split": case["split"],
                        "kind": case["kind"],
                        "mode": mode,
                        "latency_ms": round(elapsed, 3),
                        "sources": sources,
                        "scores": [h["score"] for h in result["hits"]],
                        "relevant_sources": case["relevant_sources"],
                        "metrics": metrics,
                        "status": "completed",
                    }
                )
                measured.append(elapsed)
                if metrics:
                    scored.append(metrics)
            except Exception as error:
                rows.append(
                    {
                        "id": case["id"],
                        "mode": mode,
                        "split": case["split"],
                        "status": "failed",
                        "error": type(error).__name__,
                    }
                )
        summary = {
            "mode": mode,
            "count": len(scored),
            "timed_count": len(measured),
            "failure_count": len(cases) - len(measured),
            "p50_ms": round(percentile(measured, 0.5), 3),
            "p95_ms": round(percentile(measured, 0.95), 3),
        }
        for metric in [
            "recall_at_5",
            "mrr",
            "ndcg_at_5",
            "precision_at_5",
            "ragas_id_precision",
            "ragas_id_recall",
        ]:
            summary[metric] = round(statistics.mean(r[metric] for r in scored), 6) if scored else 0
        summaries.append(summary)
        print(json.dumps(summary), flush=True)
    model_manifest = Path("/models/manifest.json")
    artifact = {
        "status": "completed" if all(s["failure_count"] == 0 for s in summaries) else "partial",
        "created_at": datetime.now(UTC).isoformat(),
        "split": split,
        "synthetic": True,
        "manifest": manifest,
        "results": summaries,
        "environment": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "logical_cpus": __import__("os").cpu_count(),
            "model_warmup_ms": round(warmup_ms, 3),
        },
        "model_assets": json.loads(model_manifest.read_text()) if model_manifest.exists() else {},
        "method": "Source-level unique-document ranks @5 from 20 passages. Answerless/tool cases excluded from relevance aggregates; included in timing. Warm models; uncached queries. Single sequential client.",
        "generation_api_calls": 0,
        "ragas": {
            "status": "id_metrics_completed"
            if all(s["failure_count"] == 0 for s in summaries)
            else "partial",
            "method": "ID-based precision and recall; no model judge or API calls",
            "faithfulness": {
                "status": "not_run",
                "reason": "Requires explicit --live and a Groq Free Plan key",
            },
        },
        "rows": rows,
    }
    output = ROOT / "results"
    output.mkdir(exist_ok=True)
    (output / f"retrieval-{split}.json").write_text(json.dumps(artifact, indent=2))
    if split in {"all", "test"}:
        (output / "latest.json").write_text(json.dumps(artifact, indent=2))
    return artifact


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=["all", "dev", "test"], default="all")
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    if args.live:
        from quarry.live_eval import run_live

        run_live()
    else:
        artifact = run(args.split)
        if artifact["status"] != "completed":
            raise SystemExit("Benchmark has failed rows; inspect the saved partial artifact")


if __name__ == "__main__":
    main()
