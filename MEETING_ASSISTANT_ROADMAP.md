# Meeting Assistant — Staff-Level POC Roadmap

> A 3-phase meeting assistant demonstrating production engineering patterns
> with multi-agent orchestration, nudge cards, advanced document intelligence,
> knowledge graph, and real voice pipeline.

---

## What Interviewers Will See

1. **Advanced document intelligence** — PDFs with images, tables, charts processed via OCR + layout analysis → structured knowledge graph
2. **3-phase data continuity** — research from BEFORE flows into DURING, decisions from DURING appear in AFTER summary
3. **Multi-agent orchestration** — 15 specialized agents coordinated across phases
4. **Nudge cards** — real-time contextual intelligence surfaced to users during meetings
5. **Knowledge graph** — entities + relationships extracted and used for multi-hop reasoning
6. **Production patterns** — DI, circuit breakers, structured logging, Prometheus, rate limiting (already built)
7. **Real voice pipeline** — LiveKit + Deepgram + Cartesia (already scaffolded)

---

## Tech Stack

| Layer | Technology | Notes |
|-------|-----------|-------|
| LLM | **OpenAI GPT-4** | All agents |
| Embeddings | **OpenAI text-embedding-3-small** | 1536-dim, already working |
| Voice | **LiveKit Agent + Deepgram + Cartesia** | Already scaffolded |
| PDF Processing | **Docling + pdfplumber + EasyOCR** | Already installed, needs wiring |
| Knowledge Graph | **NetworkX + PostgreSQL** | In-memory graph + persistent storage |
| Web Search | **Exa** | Pre-meeting research |
| Email | **Postmark** | Post-meeting summary delivery |
| Vector DB | **Qdrant** | Already working (4 collections) |
| DB | **PostgreSQL** | Already working |
| Cache | **Redis** | Already working |
| Frontend | **Next.js 14** | Already working |

---

## Phase 0: Data Models + Enhanced Document Processing (2 days)

### 0A: Meeting Tables (Alembic migration)

```sql
meetings (id, title, description, scheduled_at, started_at, ended_at,
          attendees JSONB, status, created_at, updated_at)

research_briefs (id, meeting_id FK, topics JSONB, executive_summary TEXT,
                 source_count INT, status, created_at)

meeting_transcripts (id, meeting_id FK, utterances JSONB, full_text TEXT, created_at)

nudges (id, meeting_id FK, nudge_type, title, content, source_agent,
        source_data JSONB, relevance_score FLOAT, shown_at, created_at)

decisions (id, meeting_id FK, decision_text, context TEXT, owner,
           deadline, status, source_nudge_id FK nullable, created_at)

action_items (id, meeting_id FK, decision_id FK nullable, description,
              assignee, deadline, priority, status, created_at)

meeting_summaries (id, meeting_id FK, summary_text TEXT, key_insights JSONB,
                   decisions_summary JSONB, email_sent_at, postmark_id, created_at)
```

### 0B: Knowledge Graph Tables

```sql
-- Entities extracted from documents (existing table, needs enhancement)
entities (id, document_id FK, chunk_id FK, entity_type, entity_value,
          entity_normalized, confidence_score, extraction_method,
          start_offset, end_offset, entity_metadata JSONB, created_at)

-- NEW: Relationships between entities
entity_relationships (id, source_entity_id FK, target_entity_id FK,
                      relationship_type VARCHAR, -- "works_at", "mentioned_in", "decided_on", etc.
                      confidence_score FLOAT, extraction_method VARCHAR,
                      context TEXT, -- sentence/chunk where relationship was found
                      document_id FK, meeting_id FK nullable,
                      created_at)

-- NEW: Document elements (tables, images, charts extracted from PDFs)
document_elements (id, document_id FK, chunk_id FK nullable,
                   element_type VARCHAR, -- "table", "image", "chart", "figure"
                   content TEXT, -- markdown for tables, OCR text for images
                   raw_data JSONB, -- original table data, image metadata
                   caption TEXT, page_number INT, position_index INT,
                   embedding_id VARCHAR, -- reference to vector in Qdrant
                   created_at)
```

### Files to Create
- `apps/api/models/meeting.py` — ORM models for meeting tables
- `apps/api/models/knowledge_graph.py` — ORM models for relationships + document elements
- `apps/api/services/meeting/meeting_service.py` — CRUD operations
- `apps/api/routers/meetings.py` — REST endpoints
- Alembic migration for all new tables

### 0C: Enhanced PDF Processing Pipeline

Upgrade the existing PDF processor to properly handle images, tables, and charts.

```
PDF Upload
  │
  ▼
┌─────────────────────────────┐
│  LAYOUT ANALYSIS AGENT      │  Docling: detect document structure
│  → Identify: text blocks,   │  → page-by-page layout map
│    tables, images, headers   │  → element bounding boxes
└─────────────┬───────────────┘
              │
              ├──────────────────────────┐
              ▼                          ▼
┌─────────────────────┐   ┌─────────────────────────┐
│  TABLE EXTRACTION   │   │  IMAGE/CHART OCR AGENT  │
│  AGENT              │   │  EasyOCR + GPT-4 Vision │
│  → pdfplumber raw   │   │  → OCR text extraction  │
│  → GPT-4: normalize │   │  → GPT-4V: describe     │
│    headers, types   │   │    chart data, figures   │
│  → Markdown output  │   │  → Structured captions   │
└─────────┬───────────┘   └───────────┬─────────────┘
          │                           │
          ▼                           ▼
┌─────────────────────────────────────────────┐
│  ENTITY & RELATIONSHIP EXTRACTION AGENT     │
│  → spaCy NER on all text (existing)         │
│  → GPT-4: extract relationships between     │
│    entities (person→org, decision→topic)     │
│  → Build knowledge graph edges              │
└─────────────┬───────────────────────────────┘
              │
              ▼
┌─────────────────────────────┐
│  EMBEDDING AGENT            │  Existing contextual embeddings
│  → Text chunks → Qdrant    │  + table markdown → Qdrant
│  → Image descriptions →    │  + chart descriptions → Qdrant
│    Qdrant                   │  All with 3-level context
└─────────────────────────────┘
```

### Files to Create / Modify
```
apps/api/services/document/
├── layout_agent.py            — Docling layout analysis, element detection
├── table_agent.py             — pdfplumber extraction + GPT-4 normalization → markdown
├── image_agent.py             — EasyOCR + GPT-4 Vision for charts/figures → text descriptions
├── relationship_agent.py      — GPT-4: extract entity relationships → knowledge graph edges
├── knowledge_graph_service.py — Build/query NetworkX graph + persist to PostgreSQL
├── processor.py               — MODIFY: orchestrate new agents in pipeline
├── contextual_processor.py    — MODIFY: embed tables/images alongside text chunks
```

### What This Shows to Interviewer
- Multi-modal document understanding (not just text extraction)
- Knowledge graph construction from unstructured data
- Agent pipeline: each agent has a specific role, outputs feed the next
- Tables and charts become searchable during meetings

---

## Phase 1: BEFORE Meeting — Research Agents (3-4 days)

### Multi-Agent Pipeline
```
Meeting Brief
  │
  ▼
┌─────────────────────────────┐
│  TOPIC EXTRACTION AGENT     │  GPT-4: analyze meeting context
│  → Extract 3-5 topics       │  → Output: structured topic list
└─────────────┬───────────────┘
              │
              ▼  (parallel for each topic)
┌─────────────────────────────┐
│  SEARCH AGENT               │  Exa API: semantic web search
│  → 10 sources per topic     │  → Output: raw search results
└─────────────┬───────────────┘
              │
              ▼
┌─────────────────────────────┐
│  VALIDATION AGENT           │  GPT-4: score & classify sources
│  → Tier 1/2/3 classification│  → Filter to top 5 per topic
│  → Credibility scoring      │  → Output: validated sources
└─────────────┬───────────────┘
              │
              ▼
┌─────────────────────────────┐
│  SYNTHESIS AGENT            │  GPT-4: executive summary
│  → Strategic insights       │  → Key findings per topic
│  → Data gaps identified     │  → Output: research brief
└─────────────────────────────┘
              │
              ▼
Store in DB + Embed in Qdrant + Add to knowledge graph
```

### Files to Create
```
apps/api/services/research/
├── __init__.py
├── topic_agent.py         — GPT-4: extract research topics from meeting brief
├── search_agent.py        — Exa API: web search per topic
├── validation_agent.py    — GPT-4: tier classify + credibility score sources
├── synthesis_agent.py     — GPT-4: generate executive summary from validated sources
├── pipeline.py            — Orchestrator: runs agents in sequence, parallel search
├── exa_client.py          — Exa API wrapper with @resilient_call
```

### API Endpoints
```
POST  /api/v1/meetings                     — Create meeting
GET   /api/v1/meetings                     — List meetings
GET   /api/v1/meetings/{id}                — Get meeting with all related data
POST  /api/v1/meetings/{id}/research       — Trigger research pipeline (background task)
GET   /api/v1/meetings/{id}/research       — Get research results
```

### Frontend
- "Meetings" tab in sidebar
- Meeting list with status badges
- Meeting detail page with research brief: topics, source cards (tier badge, score), executive summary
- "Run Research" button with WebSocket progress

### Data Continuity
- Research embedded in Qdrant → available to Context Agent during meeting
- Research entities added to knowledge graph → enables multi-hop reasoning
- "Our research found X" → traceable to specific source with credibility score

---

## Phase 2: DURING Meeting — Voice + Agents + Nudge Cards (4-5 days)

### Multi-Agent Architecture
```
Live Audio (LiveKit + Deepgram STT)
  │
  ▼
┌─────────────────────────────┐
│  TRANSCRIPT AGENT           │  Collects utterances, maintains context window
│  → Speaker labels           │  → Detects topic shifts / strategic moments
│  → Rolling context (last 5) │  → Triggers tool agents on keywords
└─────────────┬───────────────┘
              │ (triggers on strategic moments)
              ▼
┌─────────────────────────────────────────────────┐
│  TOOL AGENTS (dispatched by transcript agent)   │
│                                                  │
│  ┌──────────────┐  ┌──────────────┐             │
│  │ CONTEXT AGENT│  │ FACT-CHECK   │             │
│  │ (RAG + Graph)│  │ AGENT        │             │
│  │ Searches:    │  │ Verifies     │             │
│  │ • Docs       │  │ claims via   │             │
│  │ • Research   │  │ Exa search   │             │
│  │ • KG edges   │  │              │             │
│  └──────┬───────┘  └──────┬───────┘             │
│         │                  │                     │
│  ┌──────────────┐  ┌──────────────┐             │
│  │ SCRIBE AGENT │  │ INSIGHT      │             │
│  │ Detects &    │  │ AGENT        │             │
│  │ logs:        │  │ Surfaces     │             │
│  │ • Decisions  │  │ relevant     │             │
│  │ • Action     │  │ pre-meeting  │             │
│  │   items      │  │ research +   │             │
│  │              │  │ KG relations │             │
│  └──────┬───────┘  └──────┬───────┘             │
└─────────┼──────────────────┼─────────────────────┘
          │                  │
          ▼                  ▼
┌─────────────────────────────┐
│  NUDGE GENERATOR            │  Formats agent outputs as nudge cards
│  → type: insight / context  │  → Sends via WebSocket to UI
│     / fact_check / decision │  → Stores in nudges table
└─────────────────────────────┘
```

### Sub-phase 2A: Wire Real STT + Transcript Agent (2 days)

#### Files to Modify
- `apps/api/services/voice/enhanced_livekit_service.py` — Wire to transcript storage
- `apps/api/services/agents/voice_agent.py` — Already has Deepgram/Cartesia

#### Files to Create
```
apps/api/services/meeting/
├── __init__.py
├── session_service.py         — Start/end meeting, manage active session state
├── transcript_agent.py        — Accumulates utterances, detects topic shifts, triggers tool agents
```

### Sub-phase 2B: Tool Agents + Nudge Cards (2-3 days)

#### Files to Create
```
apps/api/services/meeting/
├── context_agent.py           — RAG queries across docs + research + knowledge graph traversal
├── fact_check_agent.py        — Exa search to verify claims made in meeting
├── scribe_agent.py            — Detects decisions/action items from transcript
├── insight_agent.py           — Surface relevant pre-meeting research + KG relationships
├── nudge_service.py           — Generates nudge card JSON, stores in DB, pushes via WebSocket
├── agent_dispatcher.py        — Routes transcript triggers to appropriate tool agents
```

### Nudge Card Types
| Type | Trigger | Example |
|------|---------|---------|
| `insight` | Topic matches pre-meeting research | "Research found: competitor raised prices 8% in Q3" |
| `context` | Question about past decisions | "In March meeting, team decided to delay launch by 2 weeks" |
| `fact_check` | Unverified claim detected | "Claim: 'Market grew 15%' — Exa found: actual growth was 12.3% (Reuters)" |
| `decision_prompt` | Scribe detects agreement | "It sounds like a decision was made: 'Go with vendor B' — Log this?" |
| `knowledge_graph` | KG traversal finds related entity | "Note: [Person X] is connected to [Company Y] via [previous deal]" |

### API Endpoints
```
POST  /api/v1/meetings/{id}/start          — Start meeting session
POST  /api/v1/meetings/{id}/end            — End meeting, save transcript, trigger summary
POST  /api/v1/meetings/{id}/decisions      — Log a decision (manual or from nudge)
POST  /api/v1/meetings/{id}/action-items   — Log an action item
GET   /api/v1/meetings/{id}/transcript     — Get transcript
GET   /api/v1/meetings/{id}/nudges         — Get all nudges for meeting
POST  /api/v1/meetings/{id}/query          — Manual RAG query during meeting
GET   /api/v1/meetings/{id}/knowledge-graph — Get entity/relationship graph for meeting context
WebSocket /ws/meeting/{id}                 — Real-time: transcript + nudge cards
```

### Sub-phase 2C: Meeting Room UI (1 day)

#### Frontend Files
```
apps/web/components/meeting/
├── MeetingRoom.tsx             — 3-panel layout: transcript | nudges | decisions
├── TranscriptPanel.tsx         — Live scrolling transcript with speaker labels
├── NudgeCard.tsx               — Single nudge card (icon, title, content, action buttons)
├── NudgeStream.tsx             — Stack of nudge cards, newest on top, auto-scroll
├── DecisionPanel.tsx           — Decision/action-item list + quick capture
├── MeetingControls.tsx         — Start/end/mute buttons + status indicator
├── KnowledgeGraphMini.tsx      — Small graph visualization of entities discussed (optional)
```

### Data Continuity
- Pre-meeting research in Qdrant + knowledge graph → Context Agent and Insight Agent query both
- Fact-Check Agent uses Exa to verify claims in real-time → nudge card with source
- Scribe Agent detects decisions → nudge card → user confirms → stored with `source_nudge_id`
- Knowledge graph grows during meeting: new entities/relationships from transcript

---

## Phase 3: AFTER Meeting — Summary + Email (2 days)

### Multi-Agent Pipeline
```
Meeting End
  │
  ▼
┌─────────────────────────────┐
│  DATA AGGREGATOR            │  Loads from DB:
│  → Transcript               │  → transcript, nudges, decisions,
│  → Nudges shown             │     action items, research brief,
│  → Decisions logged         │     knowledge graph snapshot
│  → Pre-meeting research     │
│  → Knowledge graph edges    │
└─────────────┬───────────────┘
              │
              ▼
┌─────────────────────────────┐
│  SUMMARY AGENT              │  GPT-4: structured meeting summary
│  → Executive summary        │  → References pre-meeting research
│  → Key discussion points    │  → Includes AI insights from nudges
│  → Decisions with owners    │  → Action items with deadlines
│  → Knowledge graph insights │  → Follow-up recommendations
└─────────────┬───────────────┘
              │
              ▼
┌─────────────────────────────┐
│  DELIVERY AGENT             │  Format + send
│  → Render HTML email        │  → Postmark API
│  → Track delivery status    │  → Store in meeting_summaries
└─────────────────────────────┘
```

### Files to Create
```
apps/api/services/meeting/
├── aggregator.py              — Loads all meeting data into context
├── summary_agent.py           — GPT-4: generate structured summary
├── delivery_agent.py          — Format HTML email, send via Postmark
├── templates/
│   └── meeting_summary.html   — Responsive email template
```

### API Endpoints
```
POST  /api/v1/meetings/{id}/summarize      — Generate summary (background task)
GET   /api/v1/meetings/{id}/summary        — Get summary
POST  /api/v1/meetings/{id}/send-summary   — Email summary to attendees
```

### Frontend
- Meeting summary page: executive summary, key insights, decisions, action items
- "Send to Attendees" button with email preview
- Decision tracker with status toggles (pending → in_progress → done)
- Knowledge graph visualization showing meeting entity connections

### Data Continuity (The Payoff)
- Summary weaves all three phases: "Research identified [X] → discussed at [timestamp] → decided [Y] → [owner] by [deadline]"
- Nudge cards cited: "AI surfaced [insight] which led to decision [Z]"
- Knowledge graph: "New relationship discovered: [Entity A] → [relationship] → [Entity B]"

---

## Full Agent Inventory (15 agents)

| # | Phase | Agent | Role | File |
|---|-------|-------|------|------|
| 1 | **DOC** | Layout Analysis Agent | Docling: detect PDF structure | `document/layout_agent.py` |
| 2 | **DOC** | Table Extraction Agent | pdfplumber + GPT-4: tables → markdown | `document/table_agent.py` |
| 3 | **DOC** | Image/Chart OCR Agent | EasyOCR + GPT-4V: images → text | `document/image_agent.py` |
| 4 | **DOC** | Relationship Extraction Agent | GPT-4: entity pairs → graph edges | `document/relationship_agent.py` |
| 5 | **BEFORE** | Topic Extraction Agent | Extract research topics | `research/topic_agent.py` |
| 6 | **BEFORE** | Search Agent | Exa web search | `research/search_agent.py` |
| 7 | **BEFORE** | Validation Agent | Tier classify + score | `research/validation_agent.py` |
| 8 | **BEFORE** | Synthesis Agent | Executive summary | `research/synthesis_agent.py` |
| 9 | **DURING** | Transcript Agent | Collect utterances, trigger agents | `meeting/transcript_agent.py` |
| 10 | **DURING** | Context Agent | RAG + knowledge graph queries | `meeting/context_agent.py` |
| 11 | **DURING** | Fact-Check Agent | Verify claims via Exa | `meeting/fact_check_agent.py` |
| 12 | **DURING** | Scribe Agent | Detect decisions + action items | `meeting/scribe_agent.py` |
| 13 | **DURING** | Insight Agent | Surface research + KG relations | `meeting/insight_agent.py` |
| 14 | **AFTER** | Summary Agent | Structured meeting summary | `meeting/summary_agent.py` |
| 15 | **AFTER** | Delivery Agent | HTML email via Postmark | `meeting/delivery_agent.py` |

Plus the **Nudge Generator** (service, not agent) that formats all DURING agent outputs into nudge cards.

---

## What This Demonstrates in an Interview

| Signal | How We Show It |
|--------|----------------|
| **System design** | 3-phase architecture, 15-agent orchestration, data continuity |
| **Document intelligence** | Multi-modal PDF processing (text + tables + images + OCR) |
| **Knowledge graph** | Entity extraction → relationship mapping → graph-powered retrieval |
| **Multi-agent patterns** | Parallel research agents, trigger-based dispatch, aggregation pipeline |
| **Real-time UX** | Nudge cards pushed via WebSocket during live meeting |
| **Production thinking** | DI, circuit breakers, structured logging, Prometheus, rate limiting |
| **Data modeling** | Normalized schema with FK relationships, nudge→decision lineage, graph edges |
| **API design** | RESTful + WebSocket, async background tasks |
| **External integrations** | 5+ APIs (OpenAI, Deepgram, Cartesia, Exa, Postmark) with resilience |
| **Observability** | Request-ID propagation, JSON logs, `/metrics`, per-agent latency tracking |
| **Code quality** | Protocol-based DI, no globals, ruff/pre-commit, Alembic migrations |
| **Real-time systems** | LiveKit WebRTC, Deepgram streaming STT, WebSocket nudge delivery |

---

## Timeline

| Phase | Duration | What |
|-------|----------|------|
| Phase 0 | 2 days | DB models + enhanced PDF processing + knowledge graph |
| Phase 1 | 3-4 days | 4 research agents + Exa integration + frontend |
| Phase 2 | 4-5 days | Voice + 5 meeting agents + nudge cards + meeting room UI |
| Phase 3 | 2 days | Summary + delivery agents + Postmark + email template |
| **Total** | **~11-13 days** | |

---

## New Dependencies

```bash
uv add exa-py postmarker
```

(Docling, EasyOCR, pdfplumber, NetworkX, spaCy already installed)

## New Environment Variables
```env
EXA_API_KEY=              # Pre-meeting web search
POSTMARK_API_KEY=         # Post-meeting email delivery
POSTMARK_FROM_EMAIL=      # Sender address for summaries
```

---

*Last updated: 2026-05-11*
