# Meeting Assistant — Interview Demo Script

A 12-minute walkthrough hitting every Staff-level signal in the system.
Optimized to fail gracefully: even without Exa or Postmark keys, the
core flow remains intact and impressive.

---

## 0. Prep (before the call)

```bash
# Infrastructure
docker compose -f infrastructure/local/docker-compose.yml up -d

# Backend
uv run uvicorn apps.api.main:app --reload

# (Optional) LiveKit voice worker for real audio capture
uv run python -m apps.workers.meeting_voice_worker dev

# Frontend
cd apps/web && npm run dev
```

Open `http://localhost:3000`.

Required `.env`: `OPENAI_API_KEY`. Optional: `EXA_API_KEY`,
`POSTMARK_API_KEY`, `LIVEKIT_API_KEY`/`SECRET`/`URL`, `DEEPGRAM_API_KEY`,
`CARTESIA_API_KEY`.

For a 60-second smoke test of the full pipeline before the demo:

```bash
uv run python scripts/seed_meeting_demo.py
```

---

## 1. Knowledge Base — advanced document intelligence (3 min)

> "Before the meeting starts, the system ingests reference docs and
> builds a structured knowledge layer."

1. **Upload a PDF** with tables and at least one image/chart.
2. Watch the processing spinner — backend logs print:
   `[enhanced] Enriched chunks: +N tables, +M images (layout method=docling)`
   `[enhanced] KG extraction: entities=X relationships=Y tables=Z images=W`
3. Click the document row → expand the panel.
4. Toggle **Knowledge Graph** tab → SVG with entities colored by type,
   hover an entity to see its relationships.
5. Toggle **Tables & Images** tab → see normalized markdown for each
   table, OCR text for each image.

**Talking points:**
- "Four agents run in sequence inside one orchestrator
  ([enhanced_pipeline.py](apps/api/services/document/enhanced_pipeline.py)):
  layout (Docling), tables (pdfplumber + GPT-4o-mini), images
  (EasyOCR), and relationships (GPT-4o-mini)."
- "Tables and images become first-class searchable elements — they
  flow back into the chunk list before the contextual-embedding step,
  so the RAG pipeline indexes them alongside text."
- "The knowledge graph is stored in PostgreSQL but queried as a
  NetworkX DiGraph at runtime — multi-hop traversal is just BFS."

---

## 2. Pre-Meeting Research — BEFORE phase (2 min)

> "Now we plan the meeting. The user describes what we're discussing
> and the system runs a 4-agent research pipeline."

1. **Create a meeting** — title like "Q2 Vendor Selection", description
   spelling out the decision and key constraints.
2. Click **Run Pre-Meeting Research**. Step 1 lights up.
3. Watch topics extracted → sources retrieved via Exa → validated/tiered
   → synthesized into an executive summary.

**Talking points:**
- "Four agents — topic, search, validation, synthesis — coordinated by
  [pipeline.py](apps/api/services/research/pipeline.py)."
- "Sources are tier-classified for credibility (`tier_1` peer-reviewed,
  `tier_2` reputable outlet, `tier_3` blog/forum)."
- "Without an Exa key, the agents still extract topics and synthesize
  from whatever sources land; they just don't fetch fresh web data."

---

## 3. Live Meeting — DURING phase + nudge cards (4 min)

> "Once research is ready, we start the meeting. This is the live
> intelligence layer."

1. Click **Start Meeting**. Step 2 expands into the live meeting room.
2. **Either** type utterances in the manual input **or** click
   **Enable Mic** and speak (requires the voice worker).
3. As utterances accumulate, the right rail fills with nudge cards:
   - **Insight** (amber) — research finding matches the discussion
   - **Context** (blue) — knowledge-base chunk relevant to the topic
   - **Fact-Check** (emerald) — verifiable claim contradicted by Exa
   - **Decision** (violet) — scribe detected an agreement; one-click "Log Decision"

**Suggested utterances** (copy-paste, one at a time):
```
Alice:   Let's kick off the vendor selection review.
Bob:     Our research shows Beacon's compliance posture is the strongest.
Alice:   CoreScale spun out of Beacon back in 2022.
Charlie: Acme's CEO Jane Calder has co-certified with Beacon before.
Bob:     Acme's latency is fastest but their support SLAs are weak.
Alice:   Let's go with Vendor B — Beacon Cloud.
Charlie: Agreed. I'll take the action item to draft the contract by end of Q2.
```

**Talking points:**
- "Four agents fire in parallel after every utterance via
  [agent_dispatcher.py](apps/api/services/meeting/agent_dispatcher.py):
  scribe, context (RAG), insight (research match), fact-check (Exa
  re-verification)."
- "Each agent has a cheap pre-check before any LLM call — scribe uses
  a regex of decision keywords, fact-check screens for numeric / 
  attribution patterns. We don't pay for GPT calls on small-talk."
- "Nudges push over a meeting-scoped WebSocket
  ([realtime.py](apps/api/services/meeting/realtime.py))
  — there's no polling lag, but the UI falls back to a 30s heartbeat
  if the socket drops."
- "The audio path is a separate LiveKit Agent process
  ([meeting_voice_worker.py](apps/workers/meeting_voice_worker.py))
  that streams each participant's audio to Deepgram and POSTs final
  utterances to the same endpoint manual input uses — so both modes
  fan into one dispatcher."

---

## 4. Post-Meeting — AFTER phase (2 min)

> "When the meeting ends, the system aggregates everything and produces
> a structured summary."

1. Click **End Meeting** → **Generate Summary**.
2. Step 3 expands: executive summary, decisions with owners, action
   items with deadlines, key insights extracted from nudges shown.
3. (Optional, requires Postmark key) click **Send Summary Email** — the
   delivery agent renders HTML and sends via Postmark.

**Talking points:**
- "The summary agent loads transcript, nudges, research, decisions, and
  the knowledge graph snapshot — then GPT-4 weaves them into a single
  narrative."
- "Each decision references the source nudge via `source_nudge_id`, so
  the summary can say 'AI surfaced X, which led to the decision to Y.'"

---

## 5. Production patterns (1 min, on request)

If interviewers ask about engineering rigor:

- **Resilience**: every external call wrapped with `@resilient_call`
  ([resilience.py](apps/api/core/resilience.py)) — circuit breaker +
  exponential backoff + timeout. Per-provider state (`openai`, `exa`,
  `deepgram`, `postmark`).
- **DI**: `ServiceContainer` in [main.py](apps/api/main.py) — every
  service is initialized once at startup, injected via FastAPI deps.
- **Observability**: request-ID propagation via structlog,
  `/metrics` Prometheus endpoint, JSON logs by default.
- **Rate limiting**: slowapi backed by Redis.
- **Async-first**: all DB, vector, and external calls use async/await;
  the dispatcher uses `asyncio.gather(..., return_exceptions=True)` so
  one agent failure doesn't break the batch.
- **Migrations**: Alembic with autogenerate.
- **Tests**: 70 passing, including unit tests for the agent pre-checks
  ([test_meeting_agents.py](tests/unit/test_meeting_agents.py)) and
  WebSocket fan-out ([test_meeting_realtime.py](tests/unit/test_meeting_realtime.py)).

---

## Failure recovery (live tips)

| Symptom | What to do |
|---|---|
| Mic doesn't connect | The voice worker isn't running — pivot to manual input mode without breaking flow. |
| No nudges appear | Check backend logs for `[Dispatcher]` — confirm `OPENAI_API_KEY` is set. Manual decision-prompt utterance ("let's go with X") is the most reliable trigger. |
| Research stalls | Without `EXA_API_KEY` the synthesis agent still runs from extracted topics — surface that as "graceful degradation". |
| Email doesn't send | Postmark key missing — open the in-app summary view to show the same content. |

---

## What this demo demonstrates

| Signal | Evidence |
|---|---|
| System design | 3-phase architecture, 15 specialized agents, one continuous data flow |
| Multi-agent orchestration | Parallel dispatch, fan-out via `asyncio.gather`, fail-soft pattern |
| Document intelligence | Multi-modal extraction (Docling layout + table normalization + OCR) |
| Knowledge graph | Per-chunk entities → GPT-extracted relationships → queryable NetworkX |
| Real-time UX | WebSocket nudge fan-out, sub-second latency from utterance to UI |
| Production engineering | DI, circuit breakers, structured logging, Prometheus, async everywhere |
| Voice pipeline | LiveKit + Deepgram in a separate worker process, not embedded in API |
| Data continuity | Research → context → fact-check → decisions → summary, all linked by FK |
