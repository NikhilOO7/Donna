# Donna — Execution Graph & Agentic Architecture

How a live meeting turns into nudges, briefs, and memory — and where every
millisecond and dollar goes. The system is organized as three temperature
paths plus a shared knowledge substrate.

```
                        ┌─────────────────────────────────────────────┐
 utterance (Deepgram)   │                 HOT PATH                    │  < 2s to first nudge
 ──────────────────────▶│  agent_dispatcher — streaming as_completed  │
                        │  activation(2s) kg_query(8s) memory(6s)     │
                        │  context(10s) scribe(12s) insight(12s)      │
                        │  fact_check(25s)                            │
                        └───────────────┬─────────────────────────────┘
                                        │ each agent emits the moment it finishes
                        ┌───────────────▼─────────────────────────────┐
                        │                WARM PATH                    │  < 50ms fan-out
                        │  MeetingHub WS — per-connection visibility  │
                        │  (leader sees all, participants see pinned  │
                        │   + their own activation nudges)            │
                        └───────────────┬─────────────────────────────┘
                                        │
                        ┌───────────────▼─────────────────────────────┐
                        │                COLD PATH (Arq)              │  seconds–minutes, off API
                        │  research_job · summary_job ·               │
                        │  process_document_job · memory indexing ·   │
                        │  scheduled_research cron (04:10 UTC)        │
                        └─────────────────────────────────────────────┘
```

## Hot path — utterance → nudge

`apps/api/services/meeting/agent_dispatcher.py`

Design pattern: **streaming supervisor** (not scatter-gather). Seven agents
run concurrently under `asyncio.as_completed`; each result is persisted and
broadcast the moment it lands. A slow fact-check never delays a fast
activation nudge.

- **Per-agent timeouts** (`_AGENT_TIMEOUTS`): activation 2s, memory 6s,
  kg_query 8s, context 10s, scribe/insight 12s, fact_check 25s. A timeout
  cancels that agent only — the cycle completes with whatever finished.
- **Cost-gated pre-checks**: every agent runs a free check (regex/token
  matchers, thresholds) before any LLM call. Most utterances cost $0.
- **Burst coalescing**: a distributed Redis lock (`wait=False`) makes
  concurrent dispatches for the same meeting collapse into a "pending" flag;
  the running cycle re-runs (max `_MAX_COALESCED_CYCLES=3`) instead of
  queueing N duplicate cycles during rapid speech.
- **Slim state loading**: `meeting_service.get_dispatch_state` issues
  targeted selects (attendees, recent utterances, completed research topics,
  attached doc ids) instead of hydrating full ORM graphs.

## Warm path — fan-out

`apps/api/services/meeting/realtime.py` — `MeetingHub` holds per-connection
metadata `{role, name}` and filters every broadcast server-side
(`_visible_to`), so privacy is enforced at the socket, not in the client.
Redis pub/sub bridges hub instances for horizontal scale.

## Cold path — heavy work off the request cycle

`apps/workers/job_worker.py` (Arq, `job_timeout=600`):

- `process_document_job` — Docling parse, semantic chunking, 3-level
  embeddings, Qdrant upserts. Upload endpoint enqueues and returns
  immediately (`BackgroundTasks` fallback if Redis is down).
- `research_job` — topic → search → validation → synthesis pipeline.
- `summary_job` — post-meeting summary, then memory indexing (meeting →
  Qdrant memory records with citations).
- `scheduled_research` cron — 04:10 UTC; refreshes briefs stale > 24h.

## Model tiering — right model for each task

`apps/api/core/config.py`: `MODEL_FAST` (gpt-4o-mini), `MODEL_SMART`
(gpt-4o), `MODEL_VISION` (gpt-4o-mini). Every call site is tiered:

| Tier | Used by | Why |
|---|---|---|
| fast (~15× cheaper) | scribe, insight, fact-check extraction+verdict, prep, memory fact extraction, topic extraction, validation, query enhancement, table/relationship extraction | High-frequency, structured-output tasks — schema adherence matters, deep reasoning doesn't |
| smart | research synthesis, meeting summary, RAG answers | User-facing prose where quality is the product |
| vision | image/diagram understanding | Vision-capable, cheap default |

All calls are metered per-meeting in Redis (`llm_meter`, micro-USD) and
surfaced at `GET /api/v1/meetings/{id}/cost`.

## Caching layers

- **Embedding cache** (`apps/api/core/cache.py`, Redis, 24h TTL) — query
  embeddings are deterministic per model+text; repeats (nudge re-scans,
  common questions, burst dispatches) skip OpenAI entirely. Shared across
  API workers and job workers. Hit/miss visible in Prometheus
  (`cache_name="embedding"`).
- **RAG response cache** (Redis, 5 min TTL) — invalidated on document
  upload/delete.
- **Dispatch pending flag** — collapses redundant hot-path cycles.

## Knowledge substrate

Everything retrieves from the same Qdrant collections (local / document /
global / unified vectors) + Neo4j graph + Postgres:

- Documents → 3-level contextual embeddings (50% local / 30% document /
  20% global weighting).
- Meetings → memory records (summary, decisions, transcript windows,
  LLM-extracted facts) indexed idempotently after each meeting.
- Every retrieval result carries a **citation** built by `build_citation`
  ("Meeting: title (date)" or "doc · section · p. N") — provenance is part
  of the data contract, not a UI afterthought.

## MCP server — Donna as tools

`apps/mcp_server/server.py` (stdio, FastMCP). Exposes the knowledge
substrate to Claude Desktop / Claude Code / any MCP client, read-only,
citations included: `search_knowledge`, `ask_donna`, `list_meetings`,
`get_meeting_brief`, `list_decisions`. Scope with `DONNA_MCP_OWNER_EMAIL`
(same row-level isolation as the API). Run: `uv run python -m
apps.mcp_server.server`; Claude Desktop config is in the module docstring.

## Latency & cost budgets

| Stage | Budget | Mechanism |
|---|---|---|
| Utterance → first nudge | < 2s | activation agent (no LLM) streams first |
| Utterance → LLM nudge | < 12s | fast-tier models + per-agent timeouts |
| WS fan-out | < 50ms | in-process hub + Redis bridge |
| Upload → 202 response | < 1s | processing enqueued, not inline |
| Silent utterance | $0 | regex/token pre-checks gate every LLM call |
| Repeated query embedding | $0 | Redis embedding cache |
