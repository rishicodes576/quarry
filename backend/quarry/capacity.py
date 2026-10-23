"""Shared capacity is finite. Plan weights affect dispatch; they never mean unlimited work."""

import time
from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlalchemy import func, select

from quarry.config import settings
from quarry.db import Conversation, Document, Job, Run, UsageDay, User, Workspace, session
from quarry.queue import PLAN_WEIGHTS
from quarry.security import current_user

router = APIRouter(prefix="/v1")


@router.get("/usage")
def usage(user: User = Depends(current_user)):
    cfg, now = settings(), time.time()
    day = datetime.now(UTC).date().isoformat()
    with session() as db:
        workspace = db.get(Workspace, user.workspace_id)
        ledger = db.get(UsageDay, f"{workspace.id}:{day}")
        shared = db.get(UsageDay, f"global:{day}")
        pending = db.scalar(
            select(func.count())
            .select_from(Job)
            .where(Job.workspace_id == workspace.id, Job.status == "pending")
        )
        active = db.scalar(
            select(func.count())
            .select_from(Job)
            .where(
                Job.workspace_id == workspace.id, Job.status == "running", Job.lease_until >= now
            )
        )
        oldest = db.scalar(
            select(func.min(Job.created_at)).where(
                Job.workspace_id == workspace.id, Job.status == "pending"
            )
        )
        stored = db.scalar(
            select(func.coalesce(func.sum(Document.byte_size), 0)).where(
                Document.workspace_id == workspace.id, Document.object_key != ""
            )
        )
        return {
            "plan": workspace.plan,
            "weight": PLAN_WEIGHTS.get(workspace.plan, 1),
            "storage": {"bytes": stored, "limit_bytes": cfg.max_workspace_storage_bytes},
            "metadata": {
                "conversations": db.scalar(
                    select(func.count())
                    .select_from(Conversation)
                    .where(Conversation.workspace_id == workspace.id)
                ),
                "conversation_limit": cfg.max_workspace_conversations,
                "retained_source_versions": db.scalar(
                    select(func.count())
                    .select_from(Document)
                    .where(Document.workspace_id == workspace.id)
                ),
                "source_version_limit": cfg.max_workspace_documents,
                "retained_runs": db.scalar(
                    select(func.count()).select_from(Run).where(Run.workspace_id == workspace.id)
                ),
                "run_limit": cfg.max_workspace_runs,
                "members": db.scalar(
                    select(func.count()).select_from(User).where(User.workspace_id == workspace.id)
                ),
                "member_limit": cfg.max_workspace_members,
            },
            "tokens": {
                "used": ledger.tokens if ledger else 0,
                "reserved": ledger.reserved if ledger else 0,
                "daily_limit": cfg.max_daily_tokens,
            },
            "shared_tokens": {
                "used": shared.tokens if shared else 0,
                "reserved": shared.reserved if shared else 0,
                "daily_limit": cfg.max_global_daily_tokens,
            },
            "queue": {
                "pending": pending,
                "running": active,
                "oldest_age_seconds": round(now - oldest, 2) if oldest else 0,
                "workspace_limit": cfg.max_pending_jobs,
                "workspace_concurrency": cfg.max_concurrent_runs,
                "shared_concurrency": cfg.max_global_runs,
            },
            "scheduling": "Weighted virtual finish time; FIFO within each workspace. Unused capacity is shared. No preemption or latency guarantee.",
            "billing": "No payments are collected. Plans are operator provisioned. Model providers and paid consent are separate from service entitlements.",
        }
