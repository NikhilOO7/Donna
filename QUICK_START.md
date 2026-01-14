# 🚀 Quick Start Guide

## TL;DR - Get Running in 3 Commands

```bash
# 1. Copy and configure environment
cp .env.example .env
# Add your API keys to .env

# 2. Start everything with Docker
./run.sh
# Or manually: docker-compose up -d

# 3. Access the app
open http://localhost:3000
```

---

## Full Command Reference

### Option 1: Interactive Menu (Easiest)
```bash
./run.sh
```
This launches an interactive menu where you can:
- Start/stop services
- View logs and status
- Restart individual services
- Clean up containers

### Option 2: Manual Docker Commands

#### Start Everything
```bash
docker-compose up -d
```

#### Start Infrastructure Only (for local development)
```bash
docker-compose -f infrastructure/local/docker-compose-minimal.yml up -d

# Then run locally:
uv run uvicorn apps.api.main:app --reload  # Backend
cd apps/web && pnpm run dev                 # Frontend
```

#### Stop Everything
```bash
docker-compose down
```

#### View Logs
```bash
docker-compose logs -f                 # All services
docker-compose logs -f backend         # Backend only
docker-compose logs -f frontend        # Frontend only
```

#### Check Status
```bash
docker-compose ps                      # Service status
docker stats                           # Resource usage
```

---

## Access Points

| Service | URL | Credentials |
|---------|-----|-------------|
| **Frontend** | http://localhost:3000 | - |
| **Backend API** | http://localhost:8000/docs | - |
| **MinIO Console** | http://localhost:9001 | voicedoc / voicedoc123 |
| **Qdrant Dashboard** | http://localhost:6333/dashboard | - |
| **Redis Insight** | http://localhost:8001 | - |

---

## Required Environment Variables

Edit `.env` and set these **required** API keys:

```bash
# Required for AI features
OPENAI_API_KEY=sk-...

# Required for voice features
DEEPGRAM_API_KEY=...
CARTESIA_API_KEY=...

# Optional
VOYAGEAI_API_KEY=...  # For embeddings
```

---

## Troubleshooting

### Services won't start?
```bash
# Check what's wrong
docker-compose logs

# Restart specific service
docker-compose restart backend

# Full reset
docker-compose down -v
docker-compose up -d
```

### Port already in use?
```bash
# Find what's using the port
lsof -i :8000  # or :3000, :5432, etc.

# Kill it
kill -9 <PID>
```

### Need a clean slate?
```bash
# Remove everything and start fresh
docker-compose down -v
docker system prune -a
docker-compose up -d
```

---

## Common Tasks

### Run Database Migrations
```bash
docker-compose exec backend uv run alembic upgrade head
```

### Access Database
```bash
docker-compose exec postgres psql -U voicedoc -d voice_doc_intel
```

### Rebuild After Code Changes
```bash
docker-compose up -d --build backend
```

### View Real-time Logs
```bash
docker-compose logs -f backend frontend voice-worker
```

---

## Development Workflow

### Full Stack Development
```bash
# 1. Start infrastructure
docker-compose up -d postgres redis qdrant minio livekit

# 2. Run backend locally (with hot reload)
uv run uvicorn apps.api.main:app --reload

# 3. Run frontend locally (with hot reload)
cd apps/web && pnpm run dev

# 4. Make changes - they auto-reload!
```

### Testing Changes
```bash
# Test backend
uv run pytest

# Test frontend
cd apps/web && pnpm test

# Lint code
uv run ruff check .
uv run black .
```

---

## Production Deployment

```bash
# 1. Update .env for production
APP_ENV=production
DEBUG=false

# 2. Build production images
docker-compose build --no-cache

# 3. Start services
docker-compose up -d

# 4. Verify everything is running
docker-compose ps
```

---

## Need More Help?

- **Full Documentation**: See [DOCKER_SETUP.md](DOCKER_SETUP.md)
- **Architecture**: See project README
- **Issues**: Check `docker-compose logs`
- **Reset**: `docker-compose down -v && docker-compose up -d`

---

## Service Architecture

```
┌──────────────────────────────────────────┐
│          User Browser                    │
│  http://localhost:3000                   │
└──────────────┬───────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────┐
│      Next.js Frontend (Port 3000)        │
└──────────────┬───────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────┐
│  FastAPI Backend + CrewAI (Port 8000)    │
│  - 5 AI Agents (Document, Voice, Query,  │
│    Context, Analytics)                    │
└─────┬────────┬────────┬──────────┬───────┘
      │        │        │          │
      ▼        ▼        ▼          ▼
  ┌────────┐ ┌────┐ ┌───────┐ ┌────────┐
  │Postgres│ │Redis│ │Qdrant │ │LiveKit │
  │ :5432  │ │:6379│ │ :6333 │ │ :7880  │
  └────────┘ └────┘ └───────┘ └────────┘
                                    │
                                    ▼
                          ┌────────────────┐
                          │  Voice Worker  │
                          │  (Background)  │
                          └────────────────┘
```

**Happy coding! 🎉**
