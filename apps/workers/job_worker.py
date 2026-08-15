"""
Durable job worker (Arq).

Runs the meeting pipelines enqueued by the API when
``USE_JOB_QUEUE=true``: agent dispatch (DURING), research (BEFORE), and
summary (AFTER). Each job retries up to ``max_tries`` with backoff; jobs
persist in Redis so a worker restart doesn't lose in-flight work.

Run with::

    uv run arq apps.workers.job_worker.WorkerSettings
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any, Dict, List

# Project root + .env loading
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv  # noqa: E402

env_path = project_root / ".env"
if env_path.exists():
    load_dotenv(env_path)

from apps.api.core.jobs import (  # noqa: E402
    QUEUE_BULK,
    QUEUE_HOT,
    get_redis_settings,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("job-worker")


# ---- Job functions ---------------------------------------------------------


async def dispatch_job(ctx: Dict[str, Any], meeting_id: str) -> None:
    """Run the DURING-phase agent dispatcher for a meeting."""
    from apps.api.services.meeting.agent_dispatcher import agent_dispatcher

    await agent_dispatcher.dispatch(meeting_id)


async def research_job(
    ctx: Dict[str, Any], meeting_id: str, title: str, description: str
) -> None:
    """Run the BEFORE-phase research pipeline."""
    from apps.api.services.research.pipeline import research_pipeline

    await research_pipeline.run(
        meeting_id=meeting_id, title=title, description=description
    )


async def summary_job(
    ctx: Dict[str, Any],
    meeting_id: str,
    meeting_title: str,
    description: str,
    transcript_text: str,
    decisions: List[Dict[str, Any]],
    action_items: List[Dict[str, Any]],
    nudges: List[Dict[str, Any]],
    research_summary: str,
) -> None:
    """Run the AFTER-phase summary pipeline."""
    from apps.api.services.meeting.summary_pipeline import summary_pipeline

    await summary_pipeline.run(
        meeting_id=meeting_id,
        meeting_title=meeting_title,
        description=description,
        transcript_text=transcript_text,
        decisions=decisions,
        action_items=action_items,
        nudges=nudges,
        research_summary=research_summary,
    )


# Built once per worker process and reused across jobs — Docling/EasyOCR
# model loading takes seconds; paying it per document would dominate
# small-file processing time.
_doc_services = None


async def _get_doc_services():
    global _doc_services
    if _doc_services is not None:
        return _doc_services

    from apps.api.core.dependencies import ServiceContainer
    from apps.api.services.document.contextual_processor import (
        ContextualEmbeddingGenerator,
        ModernDocumentProcessor,
    )
    from apps.api.services.document.embeddings import EmbeddingService
    from apps.api.services.document.processor import DocumentProcessor
    from apps.api.services.document.vector_store import (
        ModernVectorStore,
        VectorStoreService,
    )

    store = ModernVectorStore()
    await store.initialize()
    _doc_services = ServiceContainer(
        doc_processor=DocumentProcessor(),
        modern_doc_processor=ModernDocumentProcessor(),
        embedding_service=EmbeddingService(),
        contextual_embedding_generator=ContextualEmbeddingGenerator(),
        vector_store=VectorStoreService(),
        modern_vector_store=store,
    )
    return _doc_services


async def process_document_job(
    ctx: Dict[str, Any],
    document_id: str,
    file_path: str,
    content_type: str,
    use_enhanced: bool = True,
) -> None:
    """Cold-path document processing (OCR, layout, embeddings, KG).

    Runs in the worker so multi-minute Docling/EasyOCR work never
    competes with the API's hot path for CPU.

    Imported from the service layer — NEVER from apps.api.main, whose
    module-level app setup once crashed this job at the import line.
    The safety net matters: a failure OUTSIDE process_document_task's
    own try/except (imports, service construction, timeout) must still
    move the document out of 'processing', or the UI polls forever.
    """
    from apps.api.services.document.processing_task import (
        mark_document_failed,
        process_document_task,
    )

    try:
        services = await _get_doc_services()
        await process_document_task(
            document_id, file_path, content_type, use_enhanced, services
        )
    except Exception as e:
        await mark_document_failed(document_id, f"{type(e).__name__}: {e}")
        raise  # let arq record the job as failed too


async def scheduled_research(ctx: Dict[str, Any]) -> None:
    """Nightly cron: auto-research upcoming meetings that lack a fresh brief.

    The retention loop's "briefs that refresh themselves without being
    asked": any meeting scheduled in the next 48h with no completed
    research gets the full pipeline run overnight.
    """
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import select

    from apps.api.core.database import AsyncSessionLocal
    from apps.api.models.meeting import Meeting, ResearchBrief
    from apps.api.services.research.pipeline import research_pipeline

    now = datetime.now(timezone.utc)
    horizon = now + timedelta(hours=48)

    async with AsyncSessionLocal() as session:
        rows = await session.execute(
            select(Meeting).where(
                Meeting.deleted_at.is_(None),
                Meeting.status.in_(["scheduled", "ready"]),
                Meeting.scheduled_at.isnot(None),
                Meeting.scheduled_at >= now,
                Meeting.scheduled_at <= horizon,
            )
        )
        meetings = list(rows.scalars().all())

        stale_cutoff = now - timedelta(hours=24)
        ran = 0
        for meeting in meetings:
            brief = (
                await session.execute(
                    select(ResearchBrief).where(
                        ResearchBrief.meeting_id == meeting.id,
                        ResearchBrief.status.in_(["completed", "researching"]),
                    )
                )
            ).scalar_one_or_none()
            if brief is not None:
                # Continuous re-scan: refresh briefs older than 24h so the
                # meeting walks in with current intelligence, not last week's.
                if (
                    brief.status == "completed"
                    and brief.created_at is not None
                    and brief.created_at < stale_cutoff
                ):
                    logger.info(
                        f"[cron] refreshing stale brief for meeting {meeting.id}"
                    )
                    await session.delete(brief)
                    await session.commit()
                else:
                    continue
            logger.info(
                f"[cron] auto-researching upcoming meeting {meeting.id} "
                f"({meeting.title!r})"
            )
            await research_pipeline.run(
                meeting_id=str(meeting.id),
                title=meeting.title,
                description=meeting.description or "",
            )
            ran += 1

        logger.info(
            f"[cron] scheduled_research: {len(meetings)} upcoming, {ran} researched"
        )


async def kg_outbox_drain_job(ctx: Dict[str, Any]) -> None:
    """Drain pending knowledge-graph writes into Neo4j.

    The reconciliation half of the outbox pattern. Runs on a schedule so a
    Neo4j outage self-heals: entries accumulate while it is down and converge
    when it returns, instead of the graph silently diverging from Postgres
    forever (which is what the old direct dual-write did).
    """
    from apps.api.core.database import AsyncSessionLocal
    from apps.api.services.document import kg_outbox

    async with AsyncSessionLocal() as session:
        result = await kg_outbox.drain(session, limit=200)
        if result.get("applied") or result.get("failed"):
            logger.info(f"[cron] kg_outbox_drain: {result}")


async def on_job_failure(ctx: Dict[str, Any]) -> None:
    """Logged when a job exhausts its retries (lightweight DLQ signal)."""
    logger.error(
        f"[job-worker] job permanently failed: "
        f"function={ctx.get('job_try')} id={ctx.get('job_id')}"
    )


def _cron_jobs():
    from arq import cron

    return [
        # 04:10 UTC daily — the "overnight research" run
        cron(scheduled_research, hour=4, minute=10),
        # Every 2 minutes — reconcile Postgres -> Neo4j. Frequent because the
        # cost of a run with an empty outbox is one indexed SELECT, and the
        # cost of NOT running is a graph that disagrees with the system of
        # record for however long the gap is.
        cron(kg_outbox_drain_job, minute=set(range(0, 60, 2))),
    ]


class WorkerSettings:
    """Bulk worker — the cold path. Consumes ``donna:bulk``.

    Research, summaries and document processing: minutes-long jobs that
    nobody is watching a spinner for. Deliberately does NOT handle
    ``dispatch_job``: a 100-document upload batch would otherwise fill every
    slot here with 600-second jobs while a live meeting's dispatch waits
    behind it, inverting the hot/cold design (see core/jobs.py).

        uv run arq apps.workers.job_worker.WorkerSettings
    """

    functions = [research_job, summary_job, process_document_job, kg_outbox_drain_job]
    cron_jobs = _cron_jobs()
    redis_settings = get_redis_settings()
    queue_name = QUEUE_BULK
    max_tries = 3
    job_timeout = 600  # seconds — document OCR/layout can run for minutes
    keep_result = 3600
    health_check_interval = 30


class DispatchWorkerSettings:
    """Hot worker — the live meeting path. Consumes ``donna:hot``.

    Only ``dispatch_job``, so an in-progress meeting's agent fan-out never
    queues behind bulk work. Must be running whenever ``USE_JOB_QUEUE=true``,
    or dispatch jobs accumulate unconsumed — ``/health`` reports the depth of
    this queue precisely so that failure is visible rather than silent.

        uv run arq apps.workers.job_worker.DispatchWorkerSettings
    """

    functions = [dispatch_job]
    redis_settings = get_redis_settings()
    queue_name = QUEUE_HOT
    max_tries = 3
    # The dispatcher's own per-agent budgets cap a cycle near 25s; this is the
    # outer bound on the whole job, not a per-agent one.
    job_timeout = 90
    keep_result = 300
    health_check_interval = 30
    # Live dispatch is bursty and short — allow more concurrency than the
    # bulk worker's default so a busy meeting room never queues on itself.
    max_jobs = 20
