import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from quarry import providers
from quarry.config import settings
from quarry.db import Job, Run, SchedulerState, UsageDay, Workspace, session, uid
from quarry.queue import admit, claim


def backlogs(heavy_count=40, small_count=10):
    with session() as db, db.begin():
        heavy, small = (
            Workspace(name="Noisy tenant", plan="enterprise"),
            Workspace(name="Trial tenant", plan="free"),
        )
        db.add_all([heavy, small])
        db.flush()
        for workspace, count in [(heavy, heavy_count), (small, small_count)]:
            for i in range(count):
                db.add(
                    Job(
                        workspace_id=workspace.id,
                        kind="research",
                        target_id=uid(),
                        cost_units=1,
                        created_at=time.time() + i * 0.001,
                    )
                )
        return heavy.id, small.id


def dispatch_to_completion(count):
    trace = []
    for _ in range(count):
        job = claim()
        assert job
        trace.append(job.workspace_id)
        with session() as db, db.begin():
            db.get(Job, job.id).status = "done"
    return trace


def test_noisy_paying_tenant_does_not_starve_trial_and_idle_capacity_is_borrowed():
    heavy, small = backlogs()
    trace = dispatch_to_completion(50)
    assert trace[:10].count(heavy) == 8
    assert trace[:10].count(small) == 2
    small_positions = [i for i, tenant in enumerate(trace) if tenant == small]
    assert small_positions[0] <= 4
    assert max(b - a for a, b in zip(small_positions, small_positions[1:], strict=False)) <= 5
    assert len(small_positions) == 10 and trace.count(heavy) == 40


def test_unused_tenant_share_is_borrowed_without_dedicated_capacity():
    heavy, small = backlogs(40, 2)
    trace = dispatch_to_completion(42)
    assert trace[:10].count(small) == 2
    assert set(trace[10:]) == {heavy}


def test_late_tenant_starts_at_shared_virtual_time_and_is_served_promptly():
    heavy, _ = backlogs(20, 0)
    assert set(dispatch_to_completion(8)) == {heavy}
    with session() as db, db.begin():
        newcomer = Workspace(name="New tenant")
        db.add(newcomer)
        db.flush()
        db.add(Job(workspace_id=newcomer.id, kind="research", target_id=uid(), cost_units=1))
        newcomer_id = newcomer.id
    trace = dispatch_to_completion(5)
    assert newcomer_id in trace


def test_global_concurrency_is_shared_across_claimers_and_workspaces(monkeypatch):
    backlogs(10, 10)
    monkeypatch.setattr(settings(), "max_global_runs", 3)
    with ThreadPoolExecutor(max_workers=8) as pool:
        jobs = list(pool.map(lambda _: claim(), range(8)))
    assert sum(job is not None for job in jobs) == 3


def test_admission_rejects_bounded_shared_backlog(monkeypatch):
    backlogs(2, 2)
    monkeypatch.setattr(settings(), "max_global_pending_jobs", 4)
    with pytest.raises(HTTPException) as error, session() as db, db.begin():
        admit(db)
    assert error.value.status_code == 503 and error.value.headers["Retry-After"] == "30"


def test_shared_model_budget_is_reserved_atomically_and_429_releases_it(make_run, monkeypatch):
    first, second = make_run(), make_run()
    a, b = claim(), claim()
    monkeypatch.setattr(settings(), "max_global_daily_tokens", providers.RESERVATION)
    providers.reserve(a)
    with pytest.raises(providers.ProviderQuota):
        providers.reserve(b)
    providers.settle(a, 0, quota=True)
    providers.reserve(b)
    providers.settle(b, 321)
    with session() as db:
        shared = db.scalar(select(UsageDay).where(UsageDay.workspace_id == "global"))
        assert shared.reserved == 0 and shared.tokens == 321
        assert db.get(Run, first.id).model_calls == 0
        assert db.get(Run, second.id).token_usage == 321


def test_client_cannot_choose_plan_or_scheduling_weight(client):
    assert (
        client.post("/v1/invitations", json={"email": "bad@example.com", "weight": 100}).status_code
        == 422
    )
    value = client.get("/v1/usage").json()
    assert value["plan"] == "free" and value["weight"] == 1
    assert "No payments" in value["billing"]
    assert client.patch("/v1/usage", json={"plan": "enterprise"}).status_code == 405
    with session() as db:
        assert db.get(SchedulerState, "dispatch") is None
