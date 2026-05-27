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


async def on_job_failure(ctx: Dict[str, Any]) -> None:
    """Logged when a job exhausts its retries (lightweight DLQ signal)."""
    logger.error(
        f"[job-worker] job permanently failed: "
        f"function={ctx.get('job_try')} id={ctx.get('job_id')}"
    )


class WorkerSettings:
    """Arq worker configuration."""

    functions = [dispatch_job, research_job, summary_job]
    redis_settings = get_redis_settings()
    max_tries = 3
    job_timeout = 300  # seconds — generous for LLM/Exa pipelines
    keep_result = 3600
    health_check_interval = 30
