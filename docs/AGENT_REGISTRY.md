# Agent Registry

Definitive enumeration of the agents in the platform, grouped by the three-phase
meeting pipeline. This is the source of truth behind the "15 specialized agents across
research, meeting intelligence, and decision-tracking pipelines" claim.

**The 15 specialized agents** are the domain agents across the named pipelines (research,
live meeting intelligence, decision-tracking) plus the core document/query/voice agents.
On top of these sit **4 document-ingestion sub-agents** (layout/table/image/relationship,
which are parsing utilities, not pipeline specialists) and the **orchestration layer**
(coordinator, dispatcher, base runner). Counting everything, the repo defines ~22 agent
classes; the 15 below are the ones that do specialized reasoning in the meeting pipelines.

---

## Phase 1 — Pre-Meeting Research (4)

| # | Agent | File | Role |
|---|-------|------|------|
| 1 | TopicAgent | `apps/api/services/research/topic_agent.py` | Extract 3–5 searchable research topics from the meeting brief |
| 2 | SearchAgent | `apps/api/services/research/search_agent.py` | Semantic web search per topic (Exa) |
| 3 | ValidationAgent | `apps/api/services/research/validation_agent.py` | Classify sources into credibility tiers, keep top-N |
| 4 | SynthesisAgent | `apps/api/services/research/synthesis_agent.py` | Synthesize validated research into an executive brief |

Orchestrated by `ResearchPipeline` (`apps/api/services/research/pipeline.py`).

## Phase 2 — Live Meeting Intelligence (5)

| # | Agent | File | Role |
|---|-------|------|------|
| 5 | ScribeAgent | `apps/api/services/meeting/scribe_agent.py` | Detect decisions/agreements in utterances → decision_prompt nudges |
| 6 | InsightAgent | `apps/api/services/meeting/insight_agent.py` | Surface pre-meeting research when topically relevant |
| 7 | FactCheckAgent | `apps/api/services/meeting/fact_check_agent.py` | Verify checkable claims (Exa) → fact_check nudges |
| 8 | ContextAgent (meeting) | `apps/api/services/meeting/context_agent.py` | RAG retrieval over the knowledge base during the meeting, element-type re-ranking |
| 9 | KGQueryAgent | `apps/api/services/meeting/kg_query_agent.py` | 1–2 hop Neo4j knowledge-graph traversal for live connections |

Fanned out per utterance by `AgentDispatcher`
(`apps/api/services/meeting/agent_dispatcher.py`) via `asyncio.gather`.

## Phase 3 — Post-Meeting / Decision-Tracking (1)

| # | Agent | File | Role |
|---|-------|------|------|
| 10 | SummaryAgent | `apps/api/services/meeting/summary_agent.py` | Synthesize transcript + decisions + nudges + research into a structured report |

Run by `SummaryPipeline` (`apps/api/services/meeting/summary_pipeline.py`), which also
mirrors the meeting into the Neo4j knowledge graph (Meeting → Decisions / ActionItems /
ResearchTopics / Transcript).

## Core Document, Query & Voice agents (5)

These power document understanding and the voice/query loop the meeting agents build on.

| # | Agent | File | Role |
|---|-------|------|------|
| 11 | DocumentAgent | `apps/api/services/agents/document_agent.py` | Intelligent chunking, contextual extraction, metadata enrichment |
| 12 | QueryAgent | `apps/api/services/agents/query_agent.py` | Intent recognition + query enhancement |
| 13 | ContextAgent (core) | `apps/api/services/agents/context_agent.py` | Hybrid search (semantic + keyword + metadata) across the document hierarchy |
| 14 | VoiceAgent | `apps/api/services/agents/voice_agent.py` | Deepgram STT + Cartesia TTS voice I/O |
| 15 | AnalyticsAgent | `apps/api/services/agents/analytics_agent.py` | Usage patterns, knowledge gaps, system insights |

---

## Supporting agents (not counted in the 15)

**Document-ingestion sub-agents** — parsing utilities invoked during upload, not pipeline
specialists:

| Agent | File | Role |
|-------|------|------|
| LayoutAgent | `apps/api/services/document/layout_agent.py` | Docling structured layout analysis |
| TableAgent | `apps/api/services/document/table_agent.py` | Normalize tables to markdown (GPT-4) |
| ImageAgent | `apps/api/services/document/image_agent.py` | EasyOCR + GPT-4o Vision image understanding |
| RelationshipAgent | `apps/api/services/document/relationship_agent.py` | Extract entity relationships → graph edges |

**Orchestration layer** — coordinate the agents above, not specialists themselves:

| Component | File | Role |
|-----------|------|------|
| DocumentIntelligenceCoordinator | `apps/api/services/agents/agent_coordinator.py` | Registers agents, defines CrewAI workflows |
| AgentDispatcher | `apps/api/services/meeting/agent_dispatcher.py` | Parallel Phase-2 fan-out per utterance |
| AgentOrchestrator (base) | `apps/api/services/agents/base_agent.py` | Executes agent sequences with metrics |

---

## How the count maps to the resume

> "Designed a 3-phase agentic architecture orchestrating 15 specialized AI agents across
> research, meeting intelligence, and decision-tracking pipelines."

- Research pipeline → **4** (Phase 1)
- Meeting-intelligence pipeline → **5** (Phase 2) + **5** core document/query/voice agents the live loop depends on
- Decision-tracking pipeline → **1** (Phase 3, SummaryAgent + the decision/action-item graph it writes)

= **15 specialized agents**, with 4 ingestion sub-agents and 3 orchestrators on top.
