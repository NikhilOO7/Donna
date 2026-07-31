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

from apps.api.core.jobs import get_redis_settings  # noqa: E402

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
    """
    from apps.api.main import process_document_task

    services = await _get_doc_services()
    await process_document_task(
        document_id, file_path, content_type, use_enhanced, services
    )


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


async def on_job_failure(ctx: Dict[str, Any]) -> None:
    """Logged when a job exhausts its retries (lightweight DLQ signal)."""
    logger.error(
        f"[job-worker] job permanently failed: "
        f"function={ctx.get('job_try')} id={ctx.get('job_id')}"
    )


def _cron_jobs():
    from arq import cron

    # 04:10 UTC daily — the "overnight research" run
    return [cron(scheduled_research, hour=4, minute=10)]


class WorkerSettings:
    """Arq worker configuration."""

    functions = [dispatch_job, research_job, summary_job, process_document_job]
    cron_jobs = _cron_jobs()
    redis_settings = get_redis_settings()
    max_tries = 3
    job_timeout = 600  # seconds — document OCR/layout can run for minutes
    keep_result = 3600
    health_check_interval = 30
