# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Donna — an AI meeting collaborator with document intelligence. FastAPI backend, Next.js frontend, an 18-agent meeting pipeline (research / live nudges / summary), contextual embeddings, knowledge graph (Neo4j), and real-time voice via LiveKit/Deepgram/Cartesia.

## Commands

```bash
# Install dependencies
uv sync                          # Python (uses uv package manager)
cd apps/web && npm install       # Frontend

# Run backend (dev)
uv run uvicorn apps.api.main:app --reload

# Run frontend (dev)
cd apps/web && npm run dev

# Lint
uv run ruff check apps/ tests/
uv run ruff format --check apps/ tests/

# Format
uv run ruff format apps/ tests/

# Run all tests
uv run pytest tests/ -v --timeout=60

# Run a single test file
uv run pytest tests/unit/test_embeddings.py -v

# Run a single test
uv run pytest tests/unit/test_embeddings.py::test_function_name -v

# Database migrations
uv run alembic upgrade head
uv run alembic revision --autogenerate -m "description"

# Full stack via Docker
docker compose -f infrastructure/local/docker-compose.yml up -d

# Interactive startup menu
./run.sh
```

## Architecture

### Backend (`apps/api/`)

Entry point: `apps/api/main.py` — creates FastAPI app, initializes all services in lifespan, defines API routes inline (not all routes use routers).

- **`core/`** — config (`pydantic-settings`), database (async SQLAlchemy 2.0 + asyncpg), Redis/Qdrant/storage connections, auth (JWT + API key), structured logging, caching
- **`models/`** — SQLAlchemy models (`Document`, `DocumentChunk`, `Entity`, `Analytics`) and Pydantic schemas
- **`routers/`** — `auth.py`, `voice.py`, and `meetings.py` are separate routers; document/query endpoints are defined directly in `main.py`
- **`services/`** — core business logic, organized by domain:

#### Document Pipeline (`services/document/`)
1. `processor.py` — extracts text from PDF/DOCX/TXT using Docling
2. `contextual_processor.py` — semantic chunking with section awareness; `ContextualEmbeddingGenerator` creates 3-level embeddings
3. `embeddings.py` — `EmbeddingService` wraps OpenAI embeddings
4. `vector_store.py` — `VectorStoreService` and `ModernVectorStore` manage Qdrant collections
5. `service.py` — `DocumentService` for PostgreSQL CRUD

#### 3-Level Contextual Embeddings
Embeddings combine three context levels with weighted contributions:
- **Local** (50%): surrounding chunk context
- **Document** (30%): section and title context
- **Global** (20%): cross-document relationships

#### RAG (`services/rag/`)
`rag_service.py` — `RAGService` and `ModernRAGService` (raw OpenAI + Qdrant) for query routing, contextual retrieval, hybrid re-ranking, and source-attributed responses with confidence scores.

#### Voice (`services/voice/`)
- `livekit_service.py` — LiveKit token generation, room management
- `enhanced_livekit_service.py` — voice agent with Deepgram STT + Cartesia TTS + OpenAI LLM

#### Meeting Intelligence (`services/meeting/`, `services/research/`)
The live product surface — 18 specialized agents across 4 pipelines (see `docs/AGENT_REGISTRY.md`):
- **Research pipeline** (`services/research/`) — topic → Exa search → tier validation → synthesis
- **Live meeting agents** (`services/meeting/`) — scribe, context, insight, fact-check, KG-query, activation, memory, agenda — streamed per utterance by `agent_dispatcher.py` (`asyncio.as_completed`, per-agent timeouts)
- **Summary pipeline** — post-meeting aggregation, action-item extraction, Neo4j sync
- **Realtime** — `realtime.py` MeetingHub (WebSocket + Redis pub/sub fan-out)

### Frontend (`apps/web/`)

Next.js 14 App Router with TypeScript + Tailwind CSS. Components: `chat/`, `voice/` (LiveKit React), `documents/`, `analytics/`.

### Workers (`apps/worker/`, `apps/workers/`)

Background and voice agent workers that run as separate processes.

### Infrastructure

Docker Compose stack: PostgreSQL 15, Redis 7, Qdrant, MinIO (S3-compatible storage), LiveKit server.

## Key API Endpoints

All prefixed routes are under `/api/v1/`. Health check at `/health`, Prometheus metrics at `/metrics`.

- `POST /api/v1/documents/upload` — upload and process document
- `POST /api/v1/query` — query documents (RAG)
- `GET/DELETE /api/v1/documents/{id}` — document CRUD
- `GET /api/v1/voice/token` — LiveKit token for voice sessions
- `GET /api/v1/analytics/usage` — usage statistics

## Code Style

- Python: ruff for linting (line-length 88, rules E/F/I/N/W, E501 ignored) and formatting
- Async-first: all database and service operations use async/await
- SQLAlchemy 2.0 style with `Mapped[]` and `mapped_column()`
- Pydantic v2 for request/response schemas
- pytest with `asyncio_mode = "auto"` — async tests work without decorators

## Environment

Requires Python >=3.13. Copy `.env.example` to `.env` and fill in API keys (OpenAI, Deepgram, Cartesia, LiveKit). Infrastructure services (PostgreSQL, Redis, Qdrant) must be running for the API to start.
