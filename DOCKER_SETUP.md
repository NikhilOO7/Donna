# 🐳 Docker Setup Guide - Voice Document Intelligence System

Complete guide to run the entire Voice Document Intelligence system using Docker.

## 📋 Table of Contents

1. [Prerequisites](#prerequisites)
2. [Quick Start](#quick-start)
3. [Development Mode](#development-mode)
4. [Production Mode](#production-mode)
5. [Service Details](#service-details)
6. [Troubleshooting](#troubleshooting)
7. [Useful Commands](#useful-commands)

---

## Prerequisites

### Required Software

1. **Docker Desktop** (or Docker Engine + Docker Compose)
   - Install from: https://www.docker.com/products/docker-desktop/
   - Minimum version: Docker 20.10+, Docker Compose 2.0+

2. **Verify Installation**
   ```bash
   docker --version
   docker-compose --version
   ```

### Required Configuration

1. **API Keys** - Add these to your `.env` file:
   ```bash
   OPENAI_API_KEY=sk-...           # Required
   DEEPGRAM_API_KEY=...            # Required for voice
   CARTESIA_API_KEY=...            # Required for voice
   VOYAGEAI_API_KEY=...            # Optional (embeddings)
   ```

2. **Copy environment file**
   ```bash
   cp .env.example .env
   # Edit .env and add your API keys
   ```

---

## Quick Start

### Option 1: Run Everything (Full Stack)

```bash
# 1. Start all services (infrastructure + application)
docker-compose up -d

# 2. Check if all services are running
docker-compose ps

# 3. View logs
docker-compose logs -f

# 4. Access the application
# - Frontend: http://localhost:3000
# - Backend API: http://localhost:8000
# - API Docs: http://localhost:8000/docs
# - MinIO Console: http://localhost:9001
# - Qdrant Dashboard: http://localhost:6333/dashboard
```

### Option 2: Run Infrastructure Only (For Local Development)

```bash
# Start only infrastructure services (good for development)
docker-compose -f infrastructure/local/docker-compose-minimal.yml up -d

# Then run backend locally:
uv sync
uv run uvicorn apps.api.main:app --host 0.0.0.0 --port 8000 --reload

# And frontend locally:
cd apps/web
pnpm install
pnpm run dev
```

---

## Development Mode

### Step-by-Step Development Setup

```bash
# 1. Clone and navigate to project
cd voice-doc-intelligence

# 2. Start infrastructure services only
docker-compose up -d postgres redis qdrant minio livekit

# 3. Wait for services to be healthy (30-60 seconds)
docker-compose ps

# 4. Run database migrations
uv run alembic upgrade head

# 5. Start backend (with hot reload)
uv run uvicorn apps.api.main:app --host 0.0.0.0 --port 8000 --reload

# 6. In another terminal, start frontend
cd apps/web
pnpm run dev

# 7. In another terminal, start voice worker
uv run python -m apps.api.services.voice.enhanced_livekit_service
```

### Useful Development Commands

```bash
# Restart only backend
docker-compose restart backend

# View backend logs
docker-compose logs -f backend

# Rebuild backend after code changes
docker-compose up -d --build backend

# Access backend container shell
docker-compose exec backend bash

# Run database migrations
docker-compose exec backend uv run alembic upgrade head
```

---

## Production Mode

### Production Deployment

```bash
# 1. Build production images
docker-compose build --no-cache

# 2. Start all services
docker-compose up -d

# 3. Verify all services are healthy
docker-compose ps

# 4. Check logs for any errors
docker-compose logs -f backend frontend voice-worker

# 5. Run database migrations
docker-compose exec backend uv run alembic upgrade head

# 6. Access the application
open http://localhost:3000
```

### Production Environment Variables

Update `.env` for production:

```bash
APP_ENV=production
DEBUG=false
LOG_LEVEL=WARNING

# Use strong passwords
POSTGRES_PASSWORD=<strong-password>
REDIS_PASSWORD=<strong-password>
MINIO_ROOT_PASSWORD=<strong-password>

# Production database (if using external)
DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/db
```

---

## Service Details

### 🗄️ Infrastructure Services

| Service | Port | Purpose | UI Access |
|---------|------|---------|-----------|
| **PostgreSQL** | 5432 | Document metadata, user data | - |
| **Redis** | 6379 | Caching, real-time features | - |
| **Qdrant** | 6333, 6334 | Vector database for embeddings | http://localhost:6333/dashboard |
| **MinIO** | 9000, 9001 | Object storage for documents | http://localhost:9001 (admin/admin123) |
| **LiveKit** | 7880, 7881 | Real-time voice server | http://localhost:7880 |

### 🚀 Application Services

| Service | Port | Purpose | Access |
|---------|------|---------|--------|
| **Backend API** | 8000 | FastAPI + CrewAI agents | http://localhost:8000/docs |
| **Frontend** | 3000 | Next.js web interface | http://localhost:3000 |
| **Voice Worker** | - | LiveKit agent for voice processing | Background service |

### Default Credentials

```bash
# PostgreSQL
User: voicedoc
Password: voicedoc123
Database: voice_doc_intel

# Redis
Password: (empty in dev)

# MinIO
Access Key: voicedoc
Secret Key: voicedoc123

# LiveKit (dev mode)
API Key: devkey
API Secret: secret
```

---

## Troubleshooting

### Common Issues

#### 1. Port Already in Use

```bash
# Check what's using the port
lsof -i :8000  # or :3000, :5432, etc.

# Kill the process
kill -9 <PID>

# Or change the port in docker-compose.yml
ports:
  - "8001:8000"  # Map to different host port
```

#### 2. Services Not Healthy

```bash
# Check service logs
docker-compose logs <service-name>

# Examples:
docker-compose logs postgres
docker-compose logs backend
docker-compose logs voice-worker

# Restart specific service
docker-compose restart <service-name>
```

#### 3. Database Connection Errors

```bash
# Ensure PostgreSQL is running and healthy
docker-compose ps postgres

# Check database logs
docker-compose logs postgres

# Connect to database directly
docker-compose exec postgres psql -U voicedoc -d voice_doc_intel

# Run migrations
docker-compose exec backend uv run alembic upgrade head
```

#### 4. Frontend Can't Connect to Backend

```bash
# Check if backend is running
curl http://localhost:8000/health

# Check environment variables
docker-compose exec frontend env | grep API_URL

# Rebuild frontend with correct env
docker-compose up -d --build frontend
```

#### 5. Voice Worker Issues

```bash
# Check voice worker logs
docker-compose logs -f voice-worker

# Verify LiveKit is accessible
curl http://localhost:7880/

# Restart voice worker
docker-compose restart voice-worker
```

#### 6. Out of Disk Space

```bash
# Check Docker disk usage
docker system df

# Clean up unused images, containers, volumes
docker system prune -a --volumes

# Remove specific volumes (⚠️ DELETES DATA)
docker volume rm voice-doc-intelligence_postgres_data
```

---

## Useful Commands

### Container Management

```bash
# Start all services
docker-compose up -d

# Start specific services
docker-compose up -d postgres redis qdrant

# Stop all services
docker-compose down

# Stop and remove volumes (⚠️ DELETES DATA)
docker-compose down -v

# Restart specific service
docker-compose restart backend

# View all containers
docker-compose ps

# View logs (all services)
docker-compose logs -f

# View logs (specific service)
docker-compose logs -f backend

# Follow logs from specific time
docker-compose logs -f --since 10m backend
```

### Build and Rebuild

```bash
# Build all images
docker-compose build

# Build specific service
docker-compose build backend

# Build without cache (clean build)
docker-compose build --no-cache

# Rebuild and restart
docker-compose up -d --build
```

### Debugging

```bash
# Access container shell
docker-compose exec backend bash
docker-compose exec postgres psql -U voicedoc -d voice_doc_intel

# Run command in container
docker-compose exec backend uv run python -c "import sys; print(sys.version)"

# Inspect container
docker inspect voice-doc-backend

# View container resource usage
docker stats

# Check network connectivity
docker-compose exec backend ping postgres
docker-compose exec backend curl http://livekit:7880/
```

### Database Operations

```bash
# Run migrations
docker-compose exec backend uv run alembic upgrade head

# Rollback migration
docker-compose exec backend uv run alembic downgrade -1

# Create new migration
docker-compose exec backend uv run alembic revision --autogenerate -m "description"

# Backup database
docker-compose exec postgres pg_dump -U voicedoc voice_doc_intel > backup.sql

# Restore database
cat backup.sql | docker-compose exec -T postgres psql -U voicedoc -d voice_doc_intel
```

### Monitoring

```bash
# View resource usage
docker-compose top

# Stream stats
docker stats --format "table {{.Container}}\t{{.CPUPerc}}\t{{.MemUsage}}"

# Health check status
docker-compose ps

# Inspect specific service health
docker inspect --format='{{json .State.Health}}' voice-doc-backend | jq
```

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                         Docker Host                             │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐        │
│  │   Frontend   │  │   Backend    │  │ Voice Worker │        │
│  │  (Next.js)   │  │  (FastAPI)   │  │  (LiveKit)   │        │
│  │  Port: 3000  │  │  Port: 8000  │  │  Background  │        │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘        │
│         │                 │                  │                 │
│         └────────┬────────┴──────────────────┘                 │
│                  │                                              │
│  ┌───────────────┴──────────────────────────────────────────┐ │
│  │                                                            │ │
│  │  ┌──────────┐ ┌────────┐ ┌────────┐ ┌───────┐ ┌────────┐│ │
│  │  │PostgreSQL│ │ Redis  │ │ Qdrant │ │ MinIO │ │LiveKit ││ │
│  │  │  :5432   │ │ :6379  │ │ :6333  │ │ :9000 │ │ :7880  ││ │
│  │  └──────────┘ └────────┘ └────────┘ └───────┘ └────────┘│ │
│  │                                                            │ │
│  │              Infrastructure Services                       │ │
│  └────────────────────────────────────────────────────────────┘ │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## Next Steps

1. ✅ Services running - Access http://localhost:3000
2. 📝 Upload a document via the web interface
3. 🎤 Start a voice conversation with LiveKit
4. 🤖 Watch the multi-agent system process your requests
5. 📊 View analytics and insights

---

## Need Help?

- Check logs: `docker-compose logs -f <service-name>`
- View service health: `docker-compose ps`
- Restart service: `docker-compose restart <service-name>`
- Full reset: `docker-compose down -v && docker-compose up -d`

**For production deployment, ensure you:**
- Use strong passwords
- Enable SSL/TLS
- Set up proper backups
- Configure monitoring
- Review security settings
