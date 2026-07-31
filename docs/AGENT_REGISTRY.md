# Agent Registry

Definitive enumeration of the agents in the platform, grouped by the three-phase
meeting pipeline. Every agent listed here is wired into a live execution path —
this registry contains no aspirational entries.

**The count:** 4 document-ingestion agents + 1 prep agent + 4 research agents +
8 live-meeting agents + 1 summary agent = **18 specialized agents**, coordinated by
an orchestration layer (research pipeline, per-utterance streaming dispatcher,
summary pipeline).

---

## Phase 0 — Document Ingestion (4)

Run in sequence by `EnhancedPipeline`
(`apps/api/services/document/enhanced_pipeline.py`) on every upload.

| # | Agent | File | Role |
|---|-------|------|------|
| 1 | LayoutAgent | `apps/api/services/document/layout_agent.py` | Docling structured layout analysis (pdfplumber fallback) |
| 2 | TableAgent | `apps/api/services/document/table_agent.py` | Normalize tables to markdown (GPT) |
| 3 | ImageAgent | `apps/api/services/document/image_agent.py` | EasyOCR + Vision image/chart understanding |
| 4 | RelationshipAgent | `apps/api/services/document/relationship_agent.py` | Extract entity relationships → knowledge-graph edges |

## Phase 1 — Pre-Meeting Research (4)

Orchestrated by `ResearchPipeline` (`apps/api/services/research/pipeline.py`).

| # | Agent | File | Role |
|---|-------|------|------|
| 5 | TopicAgent | `apps/api/services/research/topic_agent.py` | Extract 3–5 searchable research topics from the meeting brief |
| 6 | SearchAgent | `apps/api/services/research/search_agent.py` | Semantic web search per topic (Exa) |
| 7 | ValidationAgent | `apps/api/services/research/validation_agent.py` | Classify sources into credibility tiers, keep top-N |
| 8 | SynthesisAgent | `apps/api/services/research/synthesis_agent.py` | Synthesize validated research into an executive brief |

## Phase 1.5 — Meeting Prep (1)

| # | Agent | File | Role |
|---|-------|------|------|
| 9 | PrepAgent | `apps/api/services/meeting/prep_agent.py` | Free-text/voice input → structured prep JSON (role, goal, agenda, risks) — Smart Fill + conversational setup |

## Phase 2 — Live Meeting Intelligence (8)

Fanned out per utterance by `AgentDispatcher`
(`apps/api/services/meeting/agent_dispatcher.py`) as a **streaming** fan-out
(`asyncio.as_completed` with per-agent timeouts — each nudge emits the moment
its agent finishes), under a Redis distributed lock with burst coalescing.
Each has a cheap pre-check (regex / similarity floor / cooldown) before any
LLM call.

| # | Agent | File | Role |
|---|-------|------|------|
| 10 | ScribeAgent | `apps/api/services/meeting/scribe_agent.py` | Detect decisions/agreements → decision_prompt nudges with verbatim trigger quotes |
| 11 | InsightAgent | `apps/api/services/meeting/insight_agent.py` | Surface pre-meeting research when topically relevant |
| 12 | FactCheckAgent | `apps/api/services/meeting/fact_check_agent.py` | Verify checkable claims (Exa) → fact_check nudges with source links |
| 13 | ContextAgent | `apps/api/services/meeting/context_agent.py` | RAG retrieval over documents + meeting memories, element-type re-ranking, citations |
| 14 | KGQueryAgent | `apps/api/services/meeting/kg_query_agent.py` | 1–2 hop Neo4j knowledge-graph traversal for live connections |
| 15 | ActivationAgent | `apps/api/services/meeting/activation_agent.py` | "Your expertise needed" — match live topics to attendee expertise, delivered privately |
| 16 | MemoryAgent | `apps/api/services/meeting/memory_agent.py` | Resurface past decisions when a settled topic comes back up |
| 17 | AgendaAgent | `apps/api/services/meeting/agenda_agent.py` | Track agenda coverage lexically; progress events + "uncovered items" nudges (LLM-free) |

## Phase 3 — Post-Meeting / Decision-Tracking (1)

| # | Agent | File | Role |
|---|-------|------|------|
| 18 | SummaryAgent | `apps/api/services/meeting/summary_agent.py` | Synthesize transcript + decisions (with trigger quotes) + pinned nudges + research into a structured report; extracts new action items |

Run by `SummaryPipeline` (`apps/api/services/meeting/summary_pipeline.py`), which
persists extracted action items and mirrors the meeting into the Neo4j knowledge
graph (Meeting → Decisions / ActionItems / ResearchTopics / Transcript).

---

## Orchestration layer (not counted)

| Component | File | Role |
|-----------|------|------|
| EnhancedPipeline | `apps/api/services/document/enhanced_pipeline.py` | Sequential ingestion-agent orchestration on upload |
| ResearchPipeline | `apps/api/services/research/pipeline.py` | 4-stage research orchestration with parallel per-topic search |
| AgentDispatcher | `apps/api/services/meeting/agent_dispatcher.py` | Parallel Phase-2 fan-out per utterance (fail-soft, distributed lock) |
| SummaryPipeline | `apps/api/services/meeting/summary_pipeline.py` | Post-meeting aggregation, persistence, KG sync |

---

## How the count maps to the resume

> "Designed a 3-phase agentic architecture orchestrating 18 specialized AI agents
> across document-ingestion, research, meeting-intelligence, and decision-tracking
> pipelines."

- Document ingestion → **4** (Phase 0)
- Meeting prep → **1** (Phase 1.5)
- Research pipeline → **4** (Phase 1)
- Meeting-intelligence pipeline → **8** (Phase 2)
- Decision-tracking → **1** (Phase 3, SummaryAgent + the decision/action-item graph it writes)

= **18 specialized agents**, with 4 pipeline orchestrators on top.
