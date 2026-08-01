"""
Agent Dispatcher — the hot path of the live meeting.

Execution graph (per utterance):

    POST /utterances ──► append (row-locked) ──► WS utterance_added
                                   │
                                   ▼  (queue or background task)
                        dispatch(meeting_id)
                                   │  distributed lock (no waiting —
                                   │  bursts coalesce via a pending flag)
                                   ▼
                     slim state load (1 round of targeted selects,
                     NOT the full meeting tree)
                                   │
              ┌────────── streamed fan-out (as_completed) ──────────┐
              │  tier 1 (<10ms):  scribe-precheck, activation, memory│
              │  tier 2 (~100ms): context (Qdrant), kg (Neo4j)       │
              │  tier 3 (LLM/web): fact_check, insight               │
              └──────────────┬──────────────────────────────────────┘
                             ▼  each agent's nudge EMITS THE MOMENT
                                IT'S READY — no barrier, a regex-fast
                                scribe nudge never waits for Exa
                  persist → speak? → WS nudge_created → metrics

Per-agent timeouts bound the cycle; a hung external dependency degrades
one nudge type, never the meeting.
"""

import asyncio
import logging
from typing import Any, Dict, Optional
from uuid import UUID

from apps.api.core.config import settings
from apps.api.core.coordination import distributed_lock
from apps.api.core.database import AsyncSessionLocal
from apps.api.core.tracing import get_tracer
from apps.api.services.meeting.activation_agent import activation_agent
from apps.api.services.meeting.agenda_agent import agenda_agent
from apps.api.services.meeting.context_agent import context_agent
from apps.api.services.meeting.fact_check_agent import fact_check_agent
from apps.api.services.meeting.flow_agent import flow_agent
from apps.api.services.meeting.insight_agent import insight_agent
from apps.api.services.meeting.kg_query_agent import kg_query_agent
from apps.api.services.meeting.meeting_service import meeting_service
from apps.api.services.meeting.memory_agent import memory_agent
from apps.api.services.meeting.nudge_feedback import should_suppress
from apps.api.services.meeting.realtime import meeting_hub
from apps.api.services.meeting.scribe_agent import scribe_agent

logger = logging.getLogger(__name__)

# Donna speaks: only these types are worth interrupting the room for,
# and only above this relevance. Rate-limited to one spoken nudge / 2 min.
_SPEAK_TYPES = {"fact_check", "decision_prompt"}
_SPEAK_MIN_RELEVANCE = 0.8
_SPEAK_COOLDOWN_SECONDS = 120

# Per-agent wall-clock budgets (seconds). Tiered by dependency class:
# in-process matchers < retrieval < LLM/web calls.
_AGENT_TIMEOUTS = {
    "scribe": 12.0,  # regex pre-check + one gpt-4o-mini call
    "context": 10.0,  # embedding + Qdrant
    "insight": 12.0,  # gpt-4o-mini topical match
    "fact_check": 25.0,  # Exa search + verdict call
    "kg_query": 8.0,  # spaCy + Neo4j traversal
    "activation": 2.0,  # pure token matcher
    "memory": 6.0,  # Neo4j decision recall
    "agenda": 3.0,  # pure lexical matcher + one UPDATE on transitions
    "flow": 5.0,  # one SQL aggregate every Nth utterance
}

# Bursts of utterances coalesce: if a cycle is already running, we mark a
# pending flag instead of queueing, and the running cycle re-runs once.
_MAX_COALESCED_CYCLES = 3


async def _maybe_speak_nudge(meeting_id: str, nudge: Dict[str, Any]) -> None:
    """Publish a short spoken version of a high-signal nudge (best-effort).

    Requires the leader to have enabled voice nudges for the meeting
    (Redis flag set via POST /{id}/voice-nudges).
    """
    try:
        if nudge.get("nudge_type") not in _SPEAK_TYPES:
            return
        if float(nudge.get("relevance_score") or 0) < _SPEAK_MIN_RELEVANCE:
            return

        import json as _json

        from apps.api.core.connections import get_redis_client

        redis = await get_redis_client()
        if await redis.get(f"voice_nudges:{meeting_id}") != "1":
            return
        if not await redis.set(
            f"voice_nudges:{meeting_id}:cooldown",
            "1",
            nx=True,
            ex=_SPEAK_COOLDOWN_SECONDS,
        ):
            return

        text = f"{nudge.get('title', '')}. {nudge.get('content', '')}"[:280]
        await redis.publish(f"meeting:{meeting_id}:speak", _json.dumps({"text": text}))
        logger.info(f"[Dispatcher] spoke nudge aloud in meeting {meeting_id}")
    except Exception as e:
        logger.debug(f"[Dispatcher] speak skipped: {e}")


async def _run_agent(name: str, coro) -> tuple[str, Optional[Dict[str, Any]]]:
    """Run one agent with tracing + timeout; failures degrade to None."""
    timeout = _AGENT_TIMEOUTS.get(name, 15.0)
    try:
        if settings.enable_tracing:
            tracer = get_tracer("meeting.agents")
            if tracer is not None:
                with tracer.start_as_current_span(f"agent.{name}"):
                    return name, await asyncio.wait_for(coro, timeout)
        return name, await asyncio.wait_for(coro, timeout)
    except asyncio.TimeoutError:
        logger.warning(f"[Dispatcher] agent '{name}' timed out after {timeout}s")
        return name, None
    except Exception as e:
        logger.warning(f"[Dispatcher] agent '{name}' error: {e}")
        return name, None


class AgentDispatcher:
    """Streamed, tiered orchestration of the meeting agents."""

    async def dispatch(self, meeting_id: str) -> None:
        """Analyze the latest meeting state, coalescing utterance bursts.

        One cycle per meeting at a time (distributed lock). If a burst of
        utterances arrives mid-cycle, we don't queue N redundant cycles —
        a pending flag makes the current holder run exactly one more pass
        over the (now newer) state.
        """
        try:
            mid = UUID(meeting_id)
        except ValueError:
            logger.warning(f"[Dispatcher] invalid meeting_id: {meeting_id}")
            return

        for _cycle in range(_MAX_COALESCED_CYCLES):
            async with distributed_lock(
                f"dispatch:{meeting_id}", ttl_seconds=45.0, wait=False
            ) as acquired:
                if not acquired:
                    # A cycle is running — ask it to go once more, then stop.
                    await self._set_pending(meeting_id)
                    return
                await self._dispatch_locked(meeting_id, mid)

            if not await self._consume_pending(meeting_id):
                return  # nothing arrived while we were analyzing

    @staticmethod
    async def _set_pending(meeting_id: str) -> None:
        try:
            from apps.api.core.connections import get_redis_client

            redis = await get_redis_client()
            await redis.set(f"dispatch:pending:{meeting_id}", "1", ex=120)
        except Exception:
            pass  # no Redis → single-process; the running cycle covered us

    @staticmethod
    async def _consume_pending(meeting_id: str) -> bool:
        try:
            from apps.api.core.connections import get_redis_client

            redis = await get_redis_client()
            return bool(await redis.delete(f"dispatch:pending:{meeting_id}"))
        except Exception:
            return False

    async def _dispatch_locked(self, meeting_id: str, mid: UUID) -> None:
        try:
            # Short-lived session: load state, release the connection.
            # Holding one across the (up to 25s) agent fan-out would pin a
            # pool connection per active meeting and exhaust the pool.
            async with AsyncSessionLocal() as session:
                state = await meeting_service.get_dispatch_state(session, mid)
            if state is None or not state["utterances"]:
                return

            utterances = state["utterances"]
            owner_id = state["owner_id"]

            tasks = [
                asyncio.create_task(_run_agent(name, coro))
                for name, coro in (
                    ("scribe", scribe_agent.analyze(utterances)),
                    (
                        "context",
                        context_agent.analyze(
                            utterances,
                            owner_id=owner_id,
                            attached_doc_ids=state["attached_doc_ids"],
                        ),
                    ),
                    (
                        "insight",
                        insight_agent.analyze(utterances, state["research_topics"]),
                    ),
                    (
                        "fact_check",
                        fact_check_agent.analyze(utterances, meeting_id=meeting_id),
                    ),
                    (
                        "kg_query",
                        kg_query_agent.analyze(
                            meeting_id, utterances, owner_id=owner_id
                        ),
                    ),
                    (
                        "activation",
                        activation_agent.analyze(
                            utterances,
                            attendees=state["attendees"],
                            meeting_id=meeting_id,
                        ),
                    ),
                    (
                        "memory",
                        memory_agent.analyze(meeting_id, utterances, owner_id=owner_id),
                    ),
                    (
                        "agenda",
                        agenda_agent.analyze(
                            meeting_id,
                            utterances,
                            agenda=state.get("agenda") or [],
                            utterance_count=state.get("utterance_count", 0),
                        ),
                    ),
                    (
                        "flow",
                        flow_agent.analyze(
                            meeting_id,
                            utterance_count=state.get("utterance_count", 0),
                            started_at=state.get("started_at"),
                            decision_count=state.get("decision_count", 0),
                        ),
                    ),
                )
            ]

            created = 0
            try:
                # Stream: each nudge reaches the room the moment its agent
                # finishes — fast agents are never blocked by slow ones.
                for fut in asyncio.as_completed(tasks):
                    name, nudge = await fut
                    if not nudge:
                        continue
                    if await should_suppress(owner_id, nudge["nudge_type"]):
                        continue
                    if await self._emit_nudge(mid, meeting_id, nudge):
                        created += 1
            finally:
                # No-op on the normal path (all done); on an exception it
                # stops orphaned agent tasks from running unobserved.
                for t in tasks:
                    t.cancel()

            if created:
                logger.info(
                    f"[Dispatcher] meeting {meeting_id}: {created} nudge(s) created"
                )

        except Exception as e:
            logger.error(f"[Dispatcher] failed for meeting {meeting_id}: {e}")

    async def _emit_nudge(
        self, mid: UUID, meeting_id: str, nudge: Dict[str, Any]
    ) -> bool:
        """Persist → speak? → broadcast → metrics for one nudge.

        Opens its own short-lived session so DB connections are only
        checked out for the milliseconds of the write, not the seconds
        the agents spend thinking.
        """
        try:
            async with AsyncSessionLocal() as session:
                return await self._emit_nudge_in_session(
                    session, mid, meeting_id, nudge
                )
        except Exception as e:
            logger.warning(f"[Dispatcher] failed to persist nudge: {e}")
            return False

    async def _emit_nudge_in_session(
        self, session, mid: UUID, meeting_id: str, nudge: Dict[str, Any]
    ) -> bool:
        try:
            persisted = await meeting_service.add_nudge(
                session=session,
                meeting_id=mid,
                nudge_type=nudge["nudge_type"],
                title=nudge["title"],
                content=nudge["content"],
                source_agent=nudge.get("source_agent"),
                source_data=nudge.get("source_data"),
                relevance_score=nudge.get("relevance_score"),
            )
            await _maybe_speak_nudge(meeting_id, nudge)
            await meeting_hub.broadcast(
                meeting_id,
                {
                    "type": "nudge_created",
                    "nudge": {
                        "id": str(persisted.id),
                        "type": persisted.nudge_type,
                        "title": persisted.title,
                        "content": persisted.content,
                        "source_agent": persisted.source_agent,
                        "source_data": persisted.source_data,
                        "relevance_score": persisted.relevance_score,
                        "created_at": persisted.created_at.isoformat()
                        if persisted.created_at
                        else None,
                    },
                },
            )
            try:
                from apps.api.services.analytics_service import track_event

                await track_event(
                    session,
                    event_type="nudge_created",
                    session_id=meeting_id,
                    event_data={"nudge_type": nudge["nudge_type"]},
                )
            except Exception:
                pass
            return True
        except Exception as e:
            logger.warning(f"[Dispatcher] failed to persist nudge: {e}")
            return False


agent_dispatcher = AgentDispatcher()
