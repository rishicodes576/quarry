"""Shared-state operational metrics, consistent across stateless API replicas."""

import time

from prometheus_client import CollectorRegistry, Gauge, generate_latest
from sqlalchemy import Float, cast, func, select

from quarry.db import Event, Job, Run, session


def shared_metrics():
    registry = CollectorRegistry()
    jobs = Gauge("quarry_jobs", "Durable job count", ["kind", "status"], registry=registry)
    age = Gauge("quarry_queue_oldest_seconds", "Age of oldest pending job", registry=registry)
    throughput = Gauge(
        "quarry_runs_completed_per_second_5m",
        "Completions in the last five minutes / 300",
        registry=registry,
    )
    failures = Gauge(
        "quarry_provider_failures_5m",
        "Failed or quota-exhausted generation runs created in the last five minutes",
        ["provider", "status"],
        registry=registry,
    )
    phase = Gauge(
        "quarry_phase_mean_seconds_5m",
        "Mean completed graph phase latency in the last five minutes",
        ["stage"],
        registry=registry,
    )
    with session() as db:
        for kind, status, count in db.execute(
            select(Job.kind, Job.status, func.count()).group_by(Job.kind, Job.status)
        ):
            jobs.labels(kind, status).set(count)
        oldest = db.scalar(select(func.min(Job.created_at)).where(Job.status == "pending"))
        age.set(max(0, time.time() - oldest) if oldest else 0)
        completed = db.scalar(
            select(func.count())
            .select_from(Run)
            .where(Run.status == "completed", Run.finished_at >= time.time() - 300)
        )
        throughput.set(completed / 300)
        for provider, status, count in db.execute(
            select(Run.provider, Run.status, func.count())
            .where(
                Run.provider != "extractive",
                Run.status.in_(["failed", "quota_exhausted"]),
                Run.created_at >= time.time() - 300,
            )
            .group_by(Run.provider, Run.status)
        ):
            failures.labels(provider, status).set(count)
        stage = Event.payload["stage"].as_string()
        duration = cast(Event.payload["latency_ms"].as_string(), Float)
        for name, seconds in db.execute(
            select(stage, func.avg(duration) / 1000)
            .where(Event.kind == "stage_completed", Event.created_at >= time.time() - 300)
            .group_by(stage)
        ):
            phase.labels(name).set(seconds)
    return generate_latest(registry)
