import contextlib
import secrets
import threading
import time

from fastapi import HTTPException
from sqlalchemy import and_, case, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert

from quarry.config import settings
from quarry.db import Event, Job, Run, SchedulerState, Workspace, session, uid

PLAN_WEIGHTS = {"free": 1, "team": 2, "enterprise": 4}


class LeaseLost(RuntimeError):
    pass


class Cancelled(RuntimeError):
    pass


def enqueue(db, workspace_id: str, kind: str, target_id: str):
    cost = {"research": 2, "ingest": 1, "cleanup": 0.5, "mail": 0.25}.get(kind, 1)
    db.add(Job(workspace_id=workspace_id, kind=kind, target_id=target_id, cost_units=cost))


def scheduler_lock(db, key):
    db.execute(insert(SchedulerState).values(id=key, virtual_time=0).on_conflict_do_nothing())
    return db.get(SchedulerState, key, with_for_update=True)


def admit(db, *, check=True):
    """Serialize admissions separately from dispatch; hold before workspace locks."""
    scheduler_lock(db, "admission")
    if not check:
        return
    pending = db.scalar(
        select(func.count()).select_from(Job).where(Job.status.in_(["pending", "running"]))
    )
    if pending >= settings().max_global_pending_jobs:
        raise HTTPException(
            503,
            "Shared queue is full; retry after capacity becomes available",
            headers={"Retry-After": "30"},
        )


def claim() -> Job | None:
    now = time.time()
    cfg = settings()
    with session() as db, db.begin():
        clock = scheduler_lock(db, "dispatch")
        active_total = db.scalar(
            select(func.count())
            .select_from(Job)
            .where(Job.status == "running", Job.lease_until >= now)
        )
        if active_total >= cfg.max_global_runs:
            return None
        eligible = and_(
            Job.available_at <= now,
            or_(Job.status == "pending", and_(Job.status == "running", Job.lease_until < now)),
        )
        heads = (
            select(
                Job.id,
                func.row_number()
                .over(
                    partition_by=Job.workspace_id,
                    order_by=[Job.available_at, Job.created_at, Job.id],
                )
                .label("rank"),
            )
            .where(eligible)
            .subquery()
        )
        weight = case(PLAN_WEIGHTS, value=Workspace.plan, else_=1)
        finish = func.greatest(Workspace.fair_finish, clock.virtual_time) + Job.cost_units / weight
        job = db.scalar(
            select(Job)
            .join(Workspace, Workspace.id == Job.workspace_id)
            .where(
                Job.id.in_(select(heads.c.id).where(heads.c.rank == 1)),
            )
            .order_by(finish, Job.created_at)
            .with_for_update(skip_locked=True, of=Job)
            .limit(1)
        )
        if job is None:
            return None
        # Serialize capacity decisions for the workspace across workers.
        workspace = db.scalar(
            select(Workspace).where(Workspace.id == job.workspace_id).with_for_update()
        )
        active = db.scalar(
            select(func.count())
            .select_from(Job)
            .where(
                Job.workspace_id == job.workspace_id,
                Job.status == "running",
                Job.lease_until >= now,
                Job.id != job.id,
            )
        )
        if active >= cfg.max_concurrent_runs:
            job.available_at = now + 0.5
            return None
        if job.attempt >= cfg.max_attempts:
            job.status = "dead"
            job.error = "Retry budget exhausted after worker interruption"
            if job.kind == "research":
                run = db.get(Run, job.target_id)
                if run:
                    from quarry.providers import settle_run

                    settle_run(db, run, None)
                    run.status, run.error, run.finished_at = "failed", job.error, now
                    event(db, run, "failed", {"reason": "worker_retry_budget_exhausted"})
            elif job.kind == "ingest":
                from quarry.db import Document

                doc = db.get(Document, job.target_id)
                if doc and not doc.deleted:
                    doc.status, doc.error = "failed", job.error
            return None
        job.status = "running"
        workspace.fair_finish = max(
            workspace.fair_finish, clock.virtual_time
        ) + job.cost_units / PLAN_WEIGHTS.get(workspace.plan, 1)
        job.fence = uid()
        job.lease_until = now + cfg.lease_seconds
        job.attempt += 1
        db.flush()
        minimum = db.scalar(
            select(func.min(Workspace.fair_finish)).where(
                Workspace.id.in_(select(Job.workspace_id).where(eligible))
            )
        )
        clock.virtual_time = max(
            clock.virtual_time, minimum if minimum is not None else workspace.fair_finish
        )
        return job


@contextlib.contextmanager
def fenced(job: Job):
    with session() as db, db.begin():
        current = db.scalar(select(Job).where(Job.id == job.id).with_for_update())
        if (
            current is None
            or current.status != "running"
            or current.fence != job.fence
            or current.lease_until <= time.time()
        ):
            raise LeaseLost("Worker lost its lease")
        yield db, current


def event(db, run: Run, kind: str, payload: dict):
    db.add(Event(workspace_id=run.workspace_id, run_id=run.id, kind=kind, payload=payload))


def check_run(job: Job):
    with fenced(job) as (db, _):
        run = db.get(Run, job.target_id)
        if run is None or run.cancel_requested:
            raise Cancelled("Research was cancelled")
        if run.started_at and time.time() - run.started_at > settings().max_run_seconds:
            raise TimeoutError("Research exceeded its execution time budget")


class Heartbeat:
    def __init__(self, job: Job):
        self.job = job
        self.stopped = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        while not self.stopped.wait(settings().lease_seconds / 3):
            try:
                with session() as db, db.begin():
                    result = db.execute(
                        update(Job)
                        .where(
                            Job.id == self.job.id,
                            Job.fence == self.job.fence,
                            Job.status == "running",
                            Job.lease_until > time.time(),
                        )
                        .values(lease_until=time.time() + settings().lease_seconds)
                    )
                    if result.rowcount != 1:
                        return
            except Exception:
                # A failed heartbeat cannot authorize a commit; fenced() checks again.
                return

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_):
        self.stopped.set()
        self.thread.join(timeout=3)


def retry_delay(attempt: int) -> float:
    return min(30, 2**attempt) + secrets.randbelow(1000) / 1000
