# Implementation Requirements: Voice Document Intelligence System

> Cross-referenced against **POC Implementation Plan - Agentic Architecture.pdf** and actual codebase state as of 2026-05-09.

---

## Status Legend

- **DONE** - Fully implemented and functional
- **FIXED** - Was broken, fixed in current session
- **PARTIAL** - Has real logic but critical gaps remain
- **STUBBED** - Code structure exists but core functionality is fake/simulated
- **MISSING** - No implementation exists

---

## 1. Infrastructure & Foundation (POC Day 1)

### 1.1 Docker Environment
| Requirement | Status | Files | Notes |
|-------------|--------|-------|-------|
| PostgreSQL setup | **DONE** | `infrastructure/local/docker-compose.yml`, `init-db.sql` | v15-alpine, healthcheck, volumes |
| Redis setup | **DONE** | `infrastructure/local/docker-compose.yml` | v7-alpine, password auth |
| Vector DB setup | **DONE** | `infrastructure/local/docker-compose.yml` | Qdrant (upgraded from planned ChromaDB/FAISS) |
| Object storage | **DONE** | `infrastructure/local/docker-compose.yml` | MinIO + local filesystem fallback |
| LiveKit server | **DONE** | `infrastructure/local/docker-compose.yml`, `livekit.yaml` | WebRTC, rooms, Redis-backed |
| Service orchestration | **DONE** | `docker-compose.yml`, `run.sh` | All services with healthchecks + interactive startup |

### 1.2 External Service Connectivity
| Requirement | Status | Files | Notes |
|-------------|--------|-------|-------|
| OpenAI API (GPT-4 + embeddings) | **DONE** | `core/config.py`, `services/document/embeddings.py` | GPT-4-turbo + text-embedding-3-small |
| Deepgram API (STT) | **DONE** | `core/config.py`, `.env` | Nova-2-meeting model configured |
| Cartesia API (TTS) | **DONE** | `core/config.py`, `.env` | Sonic-turbo model configured |
| LiveKit SDK | **DONE** | `core/config.py`, `services/voice/` | API key + secret configured |
| Voyage AI (optional) | **DONE** | `core/config.py`, `services/document/embeddings.py` | voyage-3-large as optional alternative |

### 1.3 Agent Communication Framework
| Requirement | Status | Files | Notes |
|-------------|--------|-------|-------|
| Base agent infrastructure | **DONE** | `services/agents/base_agent.py` | Metrics, context, CrewAI factory |
| Agent orchestrator | **PARTIAL** | `services/agents/agent_coordinator.py` | Workflow definitions exist but depend on broken agents |
| CrewAI integration | **PARTIAL** | `services/agents/crew_setup.py` | Basic setup works; enhanced tools use `asyncio.run()` inside async context - **will crash at runtime** |
| Redis message bus | **PARTIAL** | `core/connections.py` | Redis client initialized but not used as inter-agent message bus |

### 1.3.1 What needs to be implemented
- [ ] **Fix `asyncio.run()` anti-pattern in `crew_setup.py`** - Replace with `await` or `asyncio.to_thread()` for sync CrewAI tool functions
- [ ] **Redis pub/sub for agent messaging** - Currently agents call each other directly; POC plan shows Redis as message bus between agents

---

## 2. Document Processing & Embeddings (POC Day 2)

### 2.1 Document Ingestion Pipeline
| Requirement (from POC plan) | Status | Files | Notes |
|-----------------------------|--------|-------|-------|
| PDF text extraction | **DONE** | `services/document/processor.py` | PyPDF2 |
| DOCX text extraction | **DONE** | `services/document/processor.py` | python-docx |
| TXT/MD extraction | **DONE** | `services/document/processor.py`, `contextual_processor.py` | Direct read |
| File storage (original docs) | **DONE** | `services/storage/local_storage.py` | Local filesystem + MinIO |
| PostgreSQL document records | **DONE** | `services/document/document_service.py` | Full CRUD, dedup, soft delete |
| Background processing | **DONE** | `main.py` | FastAPI BackgroundTasks |

### 2.2 Intelligent Chunking
| Requirement (from POC plan) | Status | Files | Notes |
|-----------------------------|--------|-------|-------|
| Semantic boundary preservation | **DONE** | `services/document/contextual_processor.py` | Section detection, paragraph boundaries |
| Token-based chunk sizing | **DONE** | `services/document/contextual_processor.py` | tiktoken cl100k_base, 512 target / 1024 max |
| Section/heading detection | **DONE** | `services/document/contextual_processor.py` | Markdown, numbered, title case, uppercase |
| Chunk overlap | **DONE** | `services/document/contextual_processor.py` | 50 token overlap |
| Chunk metadata | **DONE** | `services/document/contextual_processor.py` | ChunkMetadata dataclass with position, section_path, semantic_type |

### 2.3 Contextual Embedding Generation
| Requirement (from POC plan) | Status | Files | Notes |
|-----------------------------|--------|-------|-------|
| Local context (neighboring chunks) | **DONE** | `services/document/embeddings.py` | Previous 100 chars + next 100 chars |
| Document context (section/chapter) | **DONE** | `services/document/embeddings.py` | Title, type, sections, keywords |
| Global context (cross-document) | **STUBBED** | `services/document/embeddings.py` | Returns document context unchanged - **not actually cross-document** |
| OpenAI embedding generation | **FIXED** | `services/document/embeddings.py` | Now uses `text-embedding-3-small` with `dimensions=1536` |
| Voyage AI embeddings (optional) | **DONE** | `services/document/embeddings.py` | voyage-3-large if API key present |
| Local model fallback | **PARTIAL** | `services/document/embeddings.py` | SentenceTransformer all-MiniLM-L6-v2 loads but produces 384-dim (incompatible with 1536-dim Qdrant collections) |
| Semantic context extraction | **DONE** | `services/document/embeddings.py` | GPT-3.5 extracts key concepts per chunk |
| Embedding caching | **DONE** | `services/document/embeddings.py` | In-memory hash-based cache |

### 2.4 Context Metadata (from POC architecture diagram)
| Requirement | Status | Files | Notes |
|-------------|--------|-------|-------|
| Document info (title, date, type) | **DONE** | `services/document/contextual_processor.py` | Extracted during processing |
| Structural info (section, page, position) | **DONE** | `models/document.py`, `contextual_processor.py` | section_path, start_page, heading_level |
| Semantic tags (topics, entities, keywords) | **PARTIAL** | `services/document/contextual_processor.py` | Keywords extracted; entity extraction via spaCy NER works; but no dedicated entity storage pipeline |
| Relationship info (references, links) | **STUBBED** | `services/agents/document_agent.py` | Uses GPT-4 prompt but doesn't query document store for real cross-document relationships |

### 2.5 Vector Database Storage
| Requirement | Status | Files | Notes |
|-------------|--------|-------|-------|
| Vector dimension standardization | **FIXED** | `core/config.py`, `services/document/vector_store.py` | Standardized to 1536 via `settings.embedding_dimensions` |
| Basic collection (single-level) | **FIXED** | `services/document/vector_store.py` | `VectorStoreService` now uses config-based dimensions |
| Multi-level collections (local/doc/global/unified) | **FIXED** | `services/document/vector_store.py` | `ModernVectorStore` 4 collections, dimensions fixed |
| Contextual embedding storage | **DONE** | `services/document/vector_store.py` | `store_contextual_embeddings()` stores to all 4 levels |
| Redis metadata caching | **DONE** | `services/document/vector_store.py` | Document metadata cached with TTL |

### 2.5.1 What needs to be implemented
- [ ] **Fix local model fallback** - SentenceTransformer produces 384-dim, can't be stored in 1536-dim Qdrant. Either disable as vector store fallback or pad/project to 1536.
- [ ] **Implement real global context** - `_create_global_context()` in `embeddings.py` should query existing documents in the vector store to find thematically related content, not just reuse document context.
- [ ] **Implement entity extraction pipeline** - TODO at `services/document/__init__.py:181`. spaCy NER exists in `contextual_processor.py` but entities are not persisted to the `entities` DB table.
- [ ] **Implement real cross-document relationship mapping** - `document_agent.py._map_document_relationships()` should search the vector store for similar chunks across documents rather than just prompting GPT-4.
- [ ] **End-to-end validation** - Upload a document, verify chunks stored in DB, embeddings stored in all 4 Qdrant collections, and a query returns relevant results.

---

## 3. Query Processing & Voice Interface (POC Day 3)

### 3.1 Query Understanding & Enhancement
| Requirement (from POC plan) | Status | Files | Notes |
|-----------------------------|--------|-------|-------|
| Intent recognition (GPT-4) | **DONE** | `services/agents/query_agent.py` | 8 regex patterns + GPT-4 analysis |
| Query enhancement | **DONE** | `services/agents/query_agent.py` | Abbreviation expansion + GPT-4 |
| Contextual memory (follow-ups) | **PARTIAL** | `services/agents/query_agent.py` | In-memory dict, stores last 20 queries per conversation - **lost on restart** |
| Query reformulation (multiple variations) | **DONE** | `services/agents/query_agent.py` | Generates 3 search variations via GPT-4 |
| Entity extraction from queries | **DONE** | `services/agents/query_agent.py` | spaCy NER + GPT-4 extraction |

### 3.2 Contextual Search & Retrieval
| Requirement (from POC plan) | Status | Files | Notes |
|-----------------------------|--------|-------|-------|
| Semantic search (vector similarity) | **DONE** | `services/document/vector_store.py` | Qdrant cosine similarity |
| Keyword search | **DONE** | `services/agents/context_agent.py` | Term frequency matching (weight: 0.2) |
| Metadata filtering (type, date, author) | **DONE** | `services/agents/context_agent.py` | Title/category/tag matching (weight: 0.1) |
| Multi-factor ranking | **DONE** | `services/agents/context_agent.py` | Semantic(0.7) + keyword(0.2) + metadata(0.1) + recency + authority |
| Context expansion (related sections) | **PARTIAL** | `services/agents/context_agent.py` | `_get_surrounding_chunks()` exists but assumes linear chunk IDs |
| Search result caching | **DONE** | `services/agents/context_agent.py` | 5-minute TTL in-memory cache |

### 3.3 RAG Pipeline
| Requirement | Status | Files | Notes |
|-------------|--------|-------|-------|
| Basic RAG (embed -> search -> GPT answer) | **FIXED** | `services/rag/llamaindex_service.py` | `search_similar()` -> `search()` method name fixed |
| Enhanced RAG (multi-context) | **FIXED** | `services/rag/llamaindex_service.py` | `search()` -> `search_with_context()` fixed, result type handling fixed |
| Conversation history | **PARTIAL** | `services/rag/llamaindex_service.py` | In-memory, last 10 exchanges - **not persistent** |
| Source attribution | **DONE** | `services/rag/llamaindex_service.py` | Sources formatted with document_id, content preview, scores |

### 3.4 Voice Interface (POC Plan: "Voice Agent")
| Requirement (from POC plan p.11) | Status | Files | Notes |
|----------------------------------|--------|-------|-------|
| LiveKit WebRTC integration | **DONE** | `services/voice/livekit_service.py`, workers | LiveKit rooms, token generation |
| **Speech-to-Text (real Deepgram)** | **STUBBED** | `services/agents/voice_agent.py` | **Returns hardcoded "This is a simulated transcript"** - the defining feature of the project is fake |
| **Text-to-Speech (real Cartesia)** | **STUBBED** | `services/agents/voice_agent.py` | **Generates random numpy arrays** - no Cartesia API call |
| Voice Activity Detection | **STUBBED** | `services/agents/voice_agent.py` | Simple energy threshold, **not using Silero VAD** |
| Stream management | **PARTIAL** | `services/voice/` | LiveKit connection works; audio stream processing incomplete |
| LiveKit worker (separate process) | **DONE** | `apps/workers/enhanced_voice_agent_worker.py` | Has real Deepgram/Cartesia init, Prometheus metrics |

### 3.5 Response Caching (POC Plan: "Intelligent Caching")
| Requirement (from POC plan p.4) | Status | Files | Notes |
|---------------------------------|--------|-------|-------|
| Redis-backed query/response cache | **MISSING** | - | POC plan shows cache check before query processing. Redis is running but no caching logic exists |
| Cache hit/miss flow | **MISSING** | - | Voice query workflow diagram (p.4) shows this as a key optimization |

### 3.5.1 What needs to be implemented
- [ ] **Wire VoiceAgent `_perform_stt()` to real Deepgram SDK** - Replace hardcoded string with actual `deepgram.transcription.prerecorded` or streaming API call
- [ ] **Wire VoiceAgent `_perform_tts()` to real Cartesia SDK** - Replace random numpy arrays with actual `cartesia.tts.sse()` call
- [ ] **Implement Silero VAD** in `_perform_vad()` - Replace energy threshold with actual Silero model inference
- [ ] **Implement `create_voice_assistant()`** - Currently just `pass`
- [ ] **Fix enhanced voice service** (`enhanced_voice_service.py`) - References undefined methods (`stream()`, `_room` attribute, `rag_service.search()`)
- [ ] **Fix modern voice service** (`modern_voice_service.py`) - `DocumentRAGIntegration.query_with_context()` has TODO for document store query, passes `None`
- [ ] **Implement response caching** - Add Redis cache layer in RAG service: hash query -> check cache -> return cached or process and store
- [ ] **Persist conversation history** - Move from in-memory dicts to PostgreSQL `conversation_sessions` table (already exists in `init-db.sql`)

---

## 4. Analytics & Web Interface (POC Day 4)

### 4.1 Analytics Collection
| Requirement (from POC plan p.6, p.13) | Status | Files | Notes |
|---------------------------------------|--------|-------|-------|
| Usage tracking (every query/response) | **STUBBED** | `services/agents/analytics_agent.py` | In-memory only - **all data lost on restart** |
| Pattern analysis (KMeans clustering) | **PARTIAL** | `services/agents/analytics_agent.py` | Logic exists but operates on volatile data |
| Knowledge gap analysis | **PARTIAL** | `services/agents/analytics_agent.py` | Groups failed queries, calculates severity |
| Insight generation | **PARTIAL** | `services/agents/analytics_agent.py` | Template-based recommendations |
| Performance monitoring | **PARTIAL** | `services/agents/analytics_agent.py` | Latency percentiles (p95, p99) - ephemeral |
| Predictive analytics | **STUBBED** | `services/agents/analytics_agent.py` | Basic heuristics, not actual prediction |

### 4.2 Analytics Persistence
| Requirement | Status | Files | Notes |
|-------------|--------|-------|-------|
| Analytics events DB table | **DONE** (schema only) | `infrastructure/local/init-db.sql` | `analytics_events` table exists in SQL |
| Write events to PostgreSQL | **MISSING** | - | No code writes to `analytics_events` table |
| Analytics API endpoints | **FIXED** | `main.py` | `/api/v1/analytics/usage` now queries real DB via `document_service.get_document_stats()` |
| Performance metrics endpoint | **PARTIAL** | `main.py` | `/api/v1/analytics/performance` returns hardcoded latency values |

### 4.3 Web Dashboard (Next.js)
| Requirement (from POC plan) | Status | Files | Notes |
|-----------------------------|--------|-------|-------|
| Document upload UI | **DONE** | `apps/web/components/documents/DocumentUpload.tsx` | Drag-drop, file validation, enhanced toggle |
| Document list/browser | **DONE** | `apps/web/components/documents/DocumentList.tsx` | Status badges, delete, summary |
| Chat interface | **DONE** | `apps/web/components/chat/ChatInterface.tsx` | Context levels, sources, latency |
| Voice interface | **DONE** | `apps/web/components/voice/VoiceInterface.tsx` | LiveKit, audio visualizer, state display |
| Analytics dashboard | **DONE** | `apps/web/components/analytics/AnalyticsDashboard.tsx` | Stats cards, latency bars, method breakdown |
| API client | **DONE** | `apps/web/lib/api-client.ts` | 11+ endpoints, WebSocket, error handling |
| Real-time updates (WebSocket) | **DONE** | `apps/web/app/page.tsx`, `main.py` | Document processing events |
| Type definitions | **DONE** | `apps/web/types/index.ts` | Matches backend contracts |

### 4.3.1 What needs to be implemented
- [ ] **Persist analytics events to PostgreSQL** - Create `AnalyticsEventService` that writes to existing `analytics_events` table on every query and document upload
- [ ] **Wire performance endpoint to real metrics** - Replace hardcoded latency values with actual collected metrics (from Redis or DB)
- [ ] **Add React error boundaries** - No error boundary components exist; a component crash kills the whole app
- [ ] **Add WebSocket reconnection logic** - Currently doesn't reconnect after disconnect
- [ ] **Add request cancellation on unmount** - ChatInterface doesn't cancel in-flight requests

---

## 5. Integration, Testing & Optimization (POC Day 5)

### 5.1 Testing
| Requirement (from POC plan) | Status | Files | Notes |
|-----------------------------|--------|-------|-------|
| Unit tests | **PARTIAL** | `tests/unit/` | 14 tests across 3 files (~20% coverage) |
| Integration tests | **MISSING** | `tests/integration/` | Directory exists, empty |
| End-to-end flow test | **MISSING** | - | Upload -> chunk -> embed -> store -> query -> answer never validated |
| Performance benchmarks | **MISSING** | - | No benchmarking code |

### 5.2 Security & Auth
| Requirement | Status | Files | Notes |
|-------------|--------|-------|-------|
| API key authentication | **DONE** | `core/auth.py`, `main.py` | X-API-Key header, dev mode bypass |
| Auth on all protected endpoints | **DONE** | `main.py` | upload, query, list, get, delete protected |
| Pydantic request validation | **DONE** | `models/requests.py` | QueryRequest with field validation |
| Pydantic response models | **DONE** | `models/responses.py` | QueryResponse, HealthResponse, analytics models |

### 5.3 Code Quality
| Requirement | Status | Files | Notes |
|-------------|--------|-------|-------|
| Bare `except:` blocks eliminated | **FIXED** | All `.py` files | 16 bare `except:` -> `except Exception:` |
| Comprehensive health check | **FIXED** | `main.py` | Actual DB/Redis/Qdrant ping verification |
| Stale references removed | **FIXED** | `main.py` | `documents_store` references replaced with DB queries |
| Method name bugs fixed | **FIXED** | `services/rag/llamaindex_service.py` | `search_similar` -> `search`, `search` -> `search_with_context` |

### 5.4 Documentation & Deployment
| Requirement (from POC plan) | Status | Files | Notes |
|-----------------------------|--------|-------|-------|
| README | **DONE** | `README.md` | Feature overview, architecture, quick start |
| Quick start guide | **DONE** | `QUICK_START.md` | TL;DR 3-step, manual setup, troubleshooting |
| Docker setup guide | **DONE** | `DOCKER_SETUP.md` | Dev/prod modes, credentials, architecture |
| API documentation | **PARTIAL** | - | FastAPI auto-docs at `/docs`, but no standalone API doc |
| Demo scenarios | **MISSING** | - | No demo scripts or sample data loader beyond `/test/process-sample` |
| User documentation | **MISSING** | - | No end-user guide |

### 5.5.1 What needs to be implemented
- [ ] **Integration tests** - Test upload->process->query flow against real (or containerized) services
- [ ] **API endpoint tests** - Test all endpoints with httpx AsyncClient against the FastAPI app
- [ ] **RAG pipeline test** - Verify document upload produces searchable embeddings, and a query returns relevant sources
- [ ] **Performance benchmarks** - Measure and log: document processing time, query latency, embedding generation time
- [ ] **Demo script** - Script that uploads sample documents and runs example queries to demonstrate the system

---

## 6. Agent-Specific Requirements (from POC Plan pp. 10-14)

### 6.1 Document Agent
| POC Plan Requirement | Status | What's Missing |
|---------------------|--------|----------------|
| Document ingestion pipeline (PyPDF2, python-docx) | **DONE** | - |
| Intelligent chunking (semantic boundaries) | **DONE** | - |
| Multi-level context extraction (local/doc/global) | **PARTIAL** | Global context is fake (reuses doc context) |
| Metadata enrichment (type, date, author, topics) | **PARTIAL** | Basic metadata extracted; no author/date parsing from document content |
| Relationship mapping ("as mentioned in safety manual") | **STUBBED** | GPT-4 prompt only, doesn't query document store |

### 6.2 Voice Agent
| POC Plan Requirement | Status | What's Missing |
|---------------------|--------|----------------|
| LiveKit integration (WebRTC streaming) | **DONE** | - |
| STT pipeline (real-time transcription) | **STUBBED** | Returns simulated text, no Deepgram call |
| TTS pipeline (natural speech output) | **STUBBED** | Returns random bytes, no Cartesia call |
| Stream management (buffering, latency) | **PARTIAL** | LiveKit handles transport; app-level buffering incomplete |
| Noise cancellation / audio optimization | **MISSING** | Relies on Deepgram defaults, no custom processing |

### 6.3 Query Agent
| POC Plan Requirement | Status | What's Missing |
|---------------------|--------|----------------|
| Intent recognition (GPT-4) | **DONE** | - |
| Query enhancement (abbreviations, synonyms) | **DONE** | - |
| Contextual memory (follow-up questions) | **PARTIAL** | Works but not persistent across restarts |
| Query reformulation (multiple search variations) | **DONE** | - |

### 6.4 Context Agent
| POC Plan Requirement | Status | What's Missing |
|---------------------|--------|----------------|
| Contextual embeddings (OpenAI enhanced with context) | **DONE** | - |
| Hybrid search (semantic + keyword + metadata) | **DONE** | - |
| Multi-factor ranking (similarity, recency, authority) | **DONE** | - |
| Context expansion (pull related sections) | **PARTIAL** | Surrounding chunk retrieval assumes linear IDs |

### 6.5 Analytics Agent
| POC Plan Requirement | Status | What's Missing |
|---------------------|--------|----------------|
| Usage tracking (every query, response, interaction) | **STUBBED** | In-memory only, not persisted |
| Pattern analysis (frequent topics, query patterns) | **PARTIAL** | KMeans exists but on volatile data |
| Knowledge gap analysis | **PARTIAL** | Logic exists, no persistent data |
| Insight generation (actionable recommendations) | **PARTIAL** | Template-based, basic |
| Performance monitoring (bottleneck detection) | **PARTIAL** | Latency tracking exists, not persisted |
| Predictive analytics | **STUBBED** | Basic heuristics only |

---

## 7. Complete Agent Workflow (POC Plan p.13)

The POC plan defines this end-to-end workflow:
> 1. User says: "What are the requirements for the new safety protocols?"
> 2. **Voice Agent**: Converts speech to text -> sends to Query Agent
> 3. **Query Agent**: Understands intent -> enhances query -> creates search variations
> 4. **Context Agent**: Searches vector DB -> ranks by relevance/recency -> expands context
> 5. **Document Agent**: Provides document context -> shows relationships -> identifies authority
> 6. **Voice Agent**: Synthesizes response -> converts to speech -> responds to user
> 7. **Analytics Agent**: Records interaction -> updates usage patterns

### Current State of This Workflow

| Step | Works? | Blocker |
|------|--------|---------|
| 1. User speaks | **NO** | STT is simulated |
| 2. Voice -> Query | **NO** | VoiceAgent returns fake transcript |
| 3. Query enhancement | **YES** | Intent + entity + variations work with GPT-4 |
| 4. Context search | **YES** | Hybrid search + ranking works (after dimension fix) |
| 5. Document context | **PARTIAL** | Relationships are fake GPT-4 prompts |
| 6. Voice response | **NO** | TTS is simulated |
| 7. Analytics tracking | **NO** | In-memory only, not persisted |

**Text-based version of this workflow (Chat interface) works for steps 3-5.**

---

## 8. Success Metrics (from POC Plan p.9-10)

### Technical Metrics
| Metric | Target | Current State |
|--------|--------|---------------|
| Query response time | <3 seconds | **UNKNOWN** - no benchmarks run |
| Voice recognition accuracy | >95% | **0%** - STT is simulated |
| Relevant document retrieval | >90% | **UNKNOWN** - no evaluation |
| System uptime | 99% | **N/A** - not deployed |
| Concurrent users | 5+ | **UNKNOWN** - no load testing |

### Business Metrics
| Metric | Target | Current State |
|--------|--------|---------------|
| User task completion rate | >85% | **UNKNOWN** |
| Query success rate | >90% | **UNKNOWN** |
| Document processing speed | <1 min/doc | **UNKNOWN** - no benchmarks |
| Insight generation accuracy | >80% | **N/A** - analytics not persisted |

---

## 9. Consolidated Implementation Backlog

### P0 - Critical (System doesn't work without these)

| # | Task | Files | Effort |
|---|------|-------|--------|
| 1 | **Wire VoiceAgent STT to Deepgram SDK** | `services/agents/voice_agent.py` | Medium |
| 2 | **Wire VoiceAgent TTS to Cartesia SDK** | `services/agents/voice_agent.py` | Medium |
| 3 | **Implement `create_voice_assistant()`** | `services/agents/voice_agent.py` | Medium |
| 4 | **End-to-end RAG validation** | Manual test or integration test | Small |
| 5 | **Fix `asyncio.run()` in crew_setup.py** | `services/agents/crew_setup.py` | Small |

### P1 - High Priority (Production readiness)

| # | Task | Files | Effort |
|---|------|-------|--------|
| 6 | **Persist analytics events to PostgreSQL** | New: `services/analytics/event_service.py`, modify `main.py` | Medium |
| 7 | **Persist conversation history to DB** | Modify `services/rag/llamaindex_service.py`, use `conversation_sessions` table | Medium |
| 8 | **Integration tests (API endpoints)** | `tests/integration/test_api_endpoints.py` | Medium |
| 9 | **RAG pipeline integration test** | `tests/integration/test_rag_pipeline.py` | Medium |
| 10 | **Wire performance analytics to real metrics** | Modify `main.py` analytics endpoint | Small |
| 11 | **Fix enhanced voice service undefined methods** | `services/voice/enhanced_voice_service.py` | Large |
| 12 | **Fix modern voice service TODO** | `services/voice/modern_voice_service.py` | Medium |

### P2 - Important (Feature completeness per POC plan)

| # | Task | Files | Effort |
|---|------|-------|--------|
| 13 | **Implement response caching (Redis)** | `services/rag/llamaindex_service.py` | Small |
| 14 | **Implement real global context** | `services/document/embeddings.py` | Medium |
| 15 | **Entity extraction pipeline (persist to DB)** | `services/document/contextual_processor.py`, `document_service.py` | Medium |
| 16 | **Real cross-document relationship mapping** | `services/agents/document_agent.py` | Medium |
| 17 | **Fix local model fallback dimensions** | `services/document/embeddings.py` | Small |
| 18 | **Implement Silero VAD** | `services/agents/voice_agent.py` | Small |
| 19 | **Add React error boundaries** | `apps/web/components/` | Small |
| 20 | **WebSocket reconnection logic** | `apps/web/lib/api-client.ts` | Small |

### P3 - Nice to Have (Polish & optimization)

| # | Task | Files | Effort |
|---|------|-------|--------|
| 21 | Performance benchmarks | New: `tests/benchmarks/` | Medium |
| 22 | Demo script with sample documents | New: `scripts/demo.py` | Small |
| 23 | API documentation (standalone) | New: `docs/api.md` | Small |
| 24 | Redis pub/sub agent messaging | `core/connections.py`, agents | Large |
| 25 | Worker health check fix (async server) | `apps/workers/enhanced_voice_agent_worker.py` | Small |
| 26 | Remove duplicate `main()` in worker | `apps/workers/enhanced_voice_agent_worker.py` | Small |

---

## 10. What Was Already Fixed (Current Session)

| Fix | Files Modified |
|-----|----------------|
| Vector dimension standardized to 1536 | `core/config.py`, `services/document/vector_store.py` |
| `VectorStoreService.vector_size` uses config | `services/document/vector_store.py` |
| `ModernVectorStore` uses config dimensions | `services/document/vector_store.py` |
| OpenAI embeddings pass `dimensions=1536` | `services/document/embeddings.py` |
| `RAGService` calls `search()` not `search_similar()` | `services/rag/llamaindex_service.py` |
| `ModernRAGService` calls `search_with_context()` | `services/rag/llamaindex_service.py` |
| Result type handling (SearchResult dataclass) | `services/rag/llamaindex_service.py` |
| `documents_store` references removed from analytics | `main.py` |
| `documents_store` references removed from test endpoint | `main.py` |
| Comprehensive health check (actual DB/Redis/Qdrant ping) | `main.py` |
| API key authentication created | `core/auth.py` |
| Auth config added | `core/config.py` |
| Auth dependency on all protected endpoints | `main.py` |
| Pydantic request models | `models/requests.py` |
| Pydantic response models | `models/responses.py` |
| Inline models moved to model files | `main.py` |
| 16 bare `except:` blocks fixed | 10 files across codebase |
| Unit test infrastructure | `tests/conftest.py`, `tests/unit/` (3 files, 14 tests) |

---

## 11. Architecture Alignment with POC Plan

### POC Plan Architecture (p.1) vs Current Implementation

| POC Plan Component | Current Implementation | Match? |
|-------------------|----------------------|--------|
| Web Dashboard (Next.js) | `apps/web/` - Full Next.js 14 app | YES |
| Voice Client (LiveKit Agent) | `apps/web/components/voice/VoiceInterface.tsx` | YES |
| API Gateway (FastAPI) | `apps/api/main.py` | YES |
| Master Orchestrator | `services/agents/agent_coordinator.py` | PARTIAL |
| Message Bus (Redis/Celery) | Redis running but not used as message bus | NO |
| Content Agent | `services/agents/context_agent.py` | YES |
| Document Agent | `services/agents/document_agent.py` | YES |
| Embedding Agent | Not a separate agent; embedded in `services/document/embeddings.py` | MERGED |
| Analytics Agent | `services/agents/analytics_agent.py` | PARTIAL |
| Query Agent | `services/agents/query_agent.py` | YES |
| Voice Agent | `services/agents/voice_agent.py` | STUBBED |
| Vector Database | Qdrant (upgraded from ChromaDB/FAISS) | YES (better) |
| Document Store | PostgreSQL + local filesystem (upgraded from SQLite) | YES (better) |
| Metadata Store | PostgreSQL (upgraded from SQLite) | YES (better) |
| Redis Cache | Redis 7 running | PARTIAL (not fully utilized) |
| OpenAI API | Connected via OpenAI SDK | YES |

---

## 12. Staff Engineer Level Elevation Plan

> **Context:** The project needs to demonstrate Staff-level engineering maturity for interview demos. A Staff engineer is evaluated not just on features but on *how* the system operates: observability, resilience, architectural clarity, and engineering rigor. The gaps below represent what an interviewer would immediately flag as missing from a Staff-level project.

### Phase S1: Structured Observability (Highest Demo Impact)

**Why first:** An interviewer who sees JSON structured logs, request-id propagation, and a `/metrics` endpoint immediately recognizes production thinking.

#### S1.1 Structured Logging with structlog
| Detail | Value |
|--------|-------|
| **Status** | MISSING |
| **Create** | `apps/api/core/logging.py` |
| **Modify** | `apps/api/main.py` (remove 50+ lines of manual logging setup) |
| **Library** | `structlog` (needs install) |
| **Pattern** | JSON renderer for production, ConsoleRenderer for dev. Use `structlog.contextvars` for automatic request_id propagation across all log calls. |
| **Impact** | Every log line becomes machine-parseable JSON with context. Enables log aggregation (ELK, Datadog). |
| **Config** | Add `log_format: str = Field(default="json", env="LOG_FORMAT")` to `config.py` |

#### S1.2 Request-ID Propagation Middleware
| Detail | Value |
|--------|-------|
| **Status** | PARTIAL (generated but not propagated) |
| **Modify** | `apps/api/main.py` - replace `RequestLoggingMiddleware` |
| **Pattern** | Read `X-Request-ID` header or generate UUID4. Bind into `structlog.contextvars`. Return in response `X-Request-ID` header. All downstream logs automatically include it. |
| **Impact** | Enables tracing a single request across all service logs. |

#### S1.3 Prometheus Metrics Endpoint
| Detail | Value |
|--------|-------|
| **Status** | MISSING |
| **Create** | `apps/api/core/metrics.py` |
| **Modify** | `apps/api/main.py` - add `/metrics` endpoint + middleware instrumentation |
| **Library** | `prometheus_client` (already installed v0.23.1) |
| **Metrics** | `http_requests_total` (Counter), `http_request_duration_seconds` (Histogram), `document_processing_duration_seconds` (Histogram), `rag_query_duration_seconds` (Histogram), `external_api_calls_total` (Counter, labels: service, status), `external_api_duration_seconds` (Histogram, labels: service) |
| **Impact** | Operational visibility. Enables Grafana dashboards, alerting, SLA tracking. |

#### S1.4 OpenTelemetry Tracing (Stretch)
| Detail | Value |
|--------|-------|
| **Status** | MISSING |
| **Create** | `apps/api/core/tracing.py` |
| **Library** | `opentelemetry-instrumentation-fastapi`, `opentelemetry-exporter-otlp` (already installed v1.39.1) |
| **Pattern** | Auto-instrument FastAPI endpoints. Add manual spans for document processing, RAG queries, external API calls. Trace-id propagates alongside request-id. |
| **Impact** | Distributed tracing enables debugging latency across service boundaries. |

---

### Phase S2: Resilience Patterns (Second-Highest Demo Impact)

**Why this matters:** An interviewer will ask "what happens when OpenAI is down?" These patterns answer that question before it's asked.

#### S2.1 Circuit Breaker + Retry Decorator
| Detail | Value |
|--------|-------|
| **Status** | MISSING |
| **Create** | `apps/api/core/resilience.py` |
| **Library** | `tenacity` (already installed v9.1.2) |
| **Pattern** | Reusable `@resilient_call(service_name, max_retries=3, timeout=30.0)` decorator combining: retry with exponential backoff (1s, 2s, 4s), circuit breaker (open after 5 consecutive failures, half-open after 30s), timeout per call, Prometheus metrics per call. |
| **Modify** | `services/document/embeddings.py` (OpenAI calls), `services/rag/llamaindex_service.py` (OpenAI chat), `services/agents/voice_agent.py` (Deepgram/Cartesia), `services/document/vector_store.py` (Qdrant calls) |
| **Impact** | Prevents cascading failures. Shows production mindset. |

#### S2.2 Rate Limiting
| Detail | Value |
|--------|-------|
| **Status** | MISSING |
| **Create** | `apps/api/core/rate_limit.py` |
| **Library** | `slowapi` (needs install) or Redis-backed sliding window |
| **Limits** | `/api/v1/documents/upload`: 5/min, `/api/v1/query`: 30/min, `/health`: 60/min |
| **Impact** | Protects system from abuse. Shows security awareness. |

---

### Phase S3: Dependency Injection & Dead Code Cleanup (Architectural Clarity)

**Why this matters:** The 12 global singleton variables in `main.py` are the most visible anti-pattern. An interviewer reading `main.py` will immediately flag it.

#### S3.1 Protocol-Based Service Abstractions
| Detail | Value |
|--------|-------|
| **Status** | MISSING |
| **Create** | `apps/api/core/protocols.py` |
| **Pattern** | `typing.Protocol` classes for `DocumentProcessorProtocol`, `EmbeddingServiceProtocol`, `VectorStoreProtocol`, `RAGServiceProtocol`. Enables testability via substitution without inheritance coupling. |

#### S3.2 Service Container with FastAPI DI
| Detail | Value |
|--------|-------|
| **Status** | MISSING (currently 12 globals) |
| **Create** | `apps/api/core/dependencies.py` |
| **Modify** | `apps/api/main.py` - replace all `global` variables with `ServiceContainer` on `app.state` |
| **Pattern** | `ServiceContainer` dataclass created in `lifespan()`, stored on `app.state.services`. Endpoints use `Depends(get_rag_service)` instead of globals. |
| **Impact** | Clean testability, no global mutable state, proper lifecycle management. |

#### S3.3 Dead Code Removal
| Detail | Value |
|--------|-------|
| **Status** | Multiple duplicate implementations exist |
| **Files to verify and potentially remove** | `services/voice/modern_voice_service.py`, `services/voice/enhanced_voice_service.py`, `core/modern_database.py`, `apps/workers/modern_voice_worker.py` |
| **Method** | Grep for imports before removing each file. Keep only canonical implementations. |

---

### Phase S4: Database Migrations & CI/CD (Engineering Rigor)

#### S4.1 Alembic Migrations
| Detail | Value |
|--------|-------|
| **Status** | MISSING (uses `Base.metadata.create_all()`) |
| **Create** | `alembic.ini`, `alembic/env.py` (async-aware), `alembic/versions/001_initial_schema.py` |
| **Modify** | `apps/api/core/database.py` - remove `create_all()` from `init_db()` |
| **Library** | `alembic` (already installed) |
| **Impact** | Shows understanding of schema evolution, safe deployments, rollback capability. |

#### S4.2 GitHub Actions CI Pipeline
| Detail | Value |
|--------|-------|
| **Status** | MISSING |
| **Create** | `.github/workflows/ci.yml` |
| **Jobs** | `lint` (ruff + mypy), `test` (pytest with PostgreSQL/Redis service containers), `security` (pip-audit), `build` (Docker build validation) |
| **Impact** | Shows engineering discipline, automated quality gates. |

#### S4.3 Pre-commit Hooks
| Detail | Value |
|--------|-------|
| **Status** | MISSING |
| **Create** | `.pre-commit-config.yaml` |
| **Hooks** | ruff, mypy, trailing-whitespace, end-of-file-fixer |

---

### Phase S5: Tests, Caching & ADRs (Polish)

#### S5.1 API Contract Tests
| Detail | Value |
|--------|-------|
| **Status** | MISSING (0 endpoint tests) |
| **Create** | `tests/api/test_health.py`, `tests/api/test_documents.py`, `tests/api/test_query.py`, `tests/api/conftest.py` |
| **Pattern** | `httpx.AsyncClient` with `ASGITransport(app=app)`. Mock services via DI container (Phase S3). |
| **Target** | 50+ API tests covering all endpoints, error cases, auth, validation. |

#### S5.2 Redis Query Caching
| Detail | Value |
|--------|-------|
| **Status** | MISSING (Redis running but unused for caching) |
| **Create** | `apps/api/core/cache.py` |
| **Modify** | `services/rag/llamaindex_service.py` - wrap `process_query` with cache check |
| **Pattern** | SHA256 hash of query as key, 5-min TTL, invalidate on document upload/delete. Cache hit/miss metrics via Prometheus. |
| **Impact** | Simple but demonstrable optimization using existing infrastructure. |

#### S5.3 Architecture Decision Records
| Detail | Value |
|--------|-------|
| **Status** | MISSING |
| **Create** | `docs/adr/001-contextual-embeddings.md`, `docs/adr/002-voice-pipeline-choices.md`, `docs/adr/003-observability-stack.md`, `docs/adr/004-resilience-patterns.md` |
| **Template** | Title, Status, Context, Decision, Consequences |
| **Impact** | Demonstrates system thinking and decision documentation discipline. |

#### S5.4 Analytics Persistence
| Detail | Value |
|--------|-------|
| **Status** | MISSING (in-memory only, DB table exists unused) |
| **Create** | `apps/api/services/analytics/event_service.py` |
| **Modify** | `apps/api/main.py` - track events on query and upload endpoints |
| **Pattern** | Write to existing `analytics_events` PostgreSQL table on every query/upload. Wire performance endpoint to real aggregated metrics. |

#### S5.5 Conversation History Persistence
| Detail | Value |
|--------|-------|
| **Status** | MISSING (in-memory dicts, lost on restart) |
| **Modify** | `services/rag/llamaindex_service.py` |
| **Pattern** | Use existing `conversation_sessions` PostgreSQL table (defined in `init-db.sql`). Load/save conversation on each query. |

---

### Staff-Level Implementation Priority

| # | Phase | Item | Effort | Demo Impact | Key Signal to Interviewer |
|---|-------|------|--------|-------------|--------------------------|
| 1 | S1.1 | Structured logging (structlog) | 2h | **Very High** | "Production observability" |
| 2 | S1.2 | Request-ID propagation | 1h | **Very High** | "Distributed tracing readiness" |
| 3 | S1.3 | Prometheus metrics | 2h | **Very High** | "Operational maturity" |
| 4 | S2.1 | Circuit breaker + retry | 3h | **High** | "Resilience engineering" |
| 5 | S4.1 | Alembic migrations | 1h | **High** | "Schema evolution discipline" |
| 6 | S3.2 | DI container (replace globals) | 3h | **High** | "Testable architecture" |
| 7 | S4.2 | GitHub Actions CI | 1h | **High** | "Engineering rigor" |
| 8 | S5.3 | ADRs (4 docs) | 1h | **Medium-High** | "System thinking, decision documentation" |
| 9 | S3.3 | Dead code removal | 1h | **Medium** | "Code hygiene" |
| 10 | S5.1 | API contract tests (50+) | 3h | **Medium** | "Test discipline" |
| 11 | S2.2 | Rate limiting | 1h | **Medium** | "Security awareness" |
| 12 | S5.2 | Redis query caching | 1h | **Medium** | "Performance optimization" |
| 13 | S5.4 | Analytics persistence | 2h | **Medium** | "Data-driven operations" |
| 14 | S5.5 | Conversation persistence | 1h | **Medium** | "Stateful service design" |
| 15 | S1.4 | OpenTelemetry tracing | 2h | **Medium** | "Distributed systems expertise" |

### What the Interviewer Will See After Execution

1. **Opening `main.py`** -- clean lifespan with DI container, no globals, no logging boilerplate
2. **Hitting `/health`** -- structured JSON with circuit breaker states and service versions
3. **Hitting `/metrics`** -- Prometheus-format metrics with request latencies, document counts, API call stats
4. **Reading logs** -- JSON-structured entries with `request_id` propagated across all services
5. **Looking at `alembic/`** -- proper schema versioning, no `create_all()`
6. **Looking at `.github/workflows/`** -- automated linting, testing, security scanning
7. **Looking at `core/resilience.py`** -- circuit breaker + retry + timeout on every external call
8. **Looking at `docs/adr/`** -- documented rationale for architectural decisions
9. **Running `pytest`** -- 75+ tests including API contract tests with mocked DI
10. **Looking at git log** -- incremental, well-structured commits showing engineering discipline

---

*Last updated: 2026-05-09*
*Based on: POC Implementation Plan - Agentic Architecture.pdf + codebase analysis + Staff-level gap analysis*
