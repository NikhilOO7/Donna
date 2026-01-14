.PHONY: help install start stop restart logs clean docker-up docker-down docker-logs status health

# Default target
help:
	@echo "Voice Document Intelligence - Available Commands"
	@echo ""
	@echo "Setup Commands:"
	@echo "  make install          - Install all dependencies (Python + Node.js)"
	@echo "  make setup            - Complete setup (install + spaCy model)"
	@echo ""
	@echo "Running Services:"
	@echo "  make start            - Start all services (Docker + Backend + Frontend + Worker)"
	@echo "  make stop             - Stop all services gracefully"
	@echo "  make restart          - Restart all services"
	@echo "  make dev              - Start in development mode with logs"
	@echo ""
	@echo "Docker Management:"
	@echo "  make docker-up        - Start only Docker services"
	@echo "  make docker-down      - Stop Docker services"
	@echo "  make docker-restart   - Restart Docker services"
	@echo "  make docker-logs      - Show Docker service logs"
	@echo "  make docker-clean     - Remove all Docker volumes and data"
	@echo ""
	@echo "Application Services:"
	@echo "  make backend          - Start only backend API"
	@echo "  make frontend         - Start only frontend"
	@echo "  make worker           - Start only voice agent worker"
	@echo ""
	@echo "Monitoring:"
	@echo "  make logs             - Show logs from all services"
	@echo "  make logs-backend     - Show backend logs"
	@echo "  make logs-frontend    - Show frontend logs"
	@echo "  make logs-worker      - Show worker logs"
	@echo "  make status           - Check status of all services"
	@echo "  make health           - Run health checks on all services"
	@echo ""
	@echo "Utilities:"
	@echo "  make clean            - Clean logs and temporary files"
	@echo "  make test             - Run tests"
	@echo "  make lint             - Run linters"

# Installation targets
install: install-python install-node

install-python:
	@echo "Installing Python dependencies..."
	@python3 -m venv .venv || true
	@. .venv/bin/activate && pip install --upgrade pip
	@. .venv/bin/activate && pip install -r requirements.txt || \
		(echo "pip not available in venv, trying uv..." && \
		which uv > /dev/null && uv pip install -r requirements.txt)

install-node:
	@echo "Installing Node.js dependencies..."
	@cd apps/web && npm install

install-spacy:
	@echo "Installing spaCy language model..."
	@. .venv/bin/activate && python -m spacy download en_core_web_sm || \
		(echo "Using direct installation..." && \
		uv pip install https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl)

setup: install install-spacy
	@echo "✓ Setup complete!"

# Start/Stop targets
start:
	@echo "Starting all services..."
	@./start.sh

stop:
	@echo "Stopping all services..."
	@if [ -f logs/backend.pid ]; then kill $$(cat logs/backend.pid) 2>/dev/null || true; rm logs/backend.pid; fi
	@if [ -f logs/frontend.pid ]; then kill $$(cat logs/frontend.pid) 2>/dev/null || true; rm logs/frontend.pid; fi
	@if [ -f logs/worker.pid ]; then kill $$(cat logs/worker.pid) 2>/dev/null || true; rm logs/worker.pid; fi
	@cd infrastructure/local && (docker compose down 2>/dev/null || docker-compose down 2>/dev/null || true)
	@echo "✓ All services stopped"

restart: stop
	@sleep 2
	@make start

dev:
	@echo "Starting in development mode..."
	@./start.sh | tee logs/dev.log

# Docker-specific targets
docker-up:
	@echo "Starting Docker services..."
	@cd infrastructure/local && (docker compose up -d || docker-compose up -d)
	@echo "✓ Docker services started"

docker-down:
	@echo "Stopping Docker services..."
	@cd infrastructure/local && (docker compose down || docker-compose down)
	@echo "✓ Docker services stopped"

docker-restart:
	@make docker-down
	@sleep 2
	@make docker-up

docker-logs:
	@cd infrastructure/local && (docker compose logs -f || docker-compose logs -f)

docker-clean:
	@echo "⚠️  WARNING: This will remove all Docker volumes and data!"
	@read -p "Are you sure? [y/N] " -n 1 -r; \
	echo; \
	if [[ $$REPLY =~ ^[Yy]$$ ]]; then \
		cd infrastructure/local && (docker compose down -v || docker-compose down -v); \
		echo "✓ Docker volumes removed"; \
	fi

# Individual service targets
backend:
	@echo "Starting Backend API..."
	@mkdir -p logs
	@. .venv/bin/activate && uvicorn apps.api.main:app --host 0.0.0.0 --port 8000 --reload

frontend:
	@echo "Starting Frontend..."
	@cd apps/web && npm run dev

worker:
	@echo "Starting Voice Agent Worker..."
	@. .venv/bin/activate && python apps/workers/enhanced_voice_agent_worker.py start

# Monitoring targets
logs:
	@echo "Showing logs from all services..."
	@tail -f logs/*.log 2>/dev/null || echo "No log files found. Have you started the services?"

logs-backend:
	@tail -f logs/backend.log 2>/dev/null || echo "Backend log not found"

logs-frontend:
	@tail -f logs/frontend.log 2>/dev/null || echo "Frontend log not found"

logs-worker:
	@tail -f logs/worker.log 2>/dev/null || echo "Worker log not found"

status:
	@echo "Service Status:"
	@echo ""
	@echo "Docker Services:"
	@docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" | grep -E "voice-doc|postgres|NAME" || echo "No Docker services running"
	@echo ""
	@echo "Application Services:"
	@if [ -f logs/backend.pid ] && ps -p $$(cat logs/backend.pid) > /dev/null 2>&1; then \
		echo "  Backend:  ✓ Running (PID: $$(cat logs/backend.pid))"; \
	else \
		echo "  Backend:  ✗ Not running"; \
	fi
	@if [ -f logs/frontend.pid ] && ps -p $$(cat logs/frontend.pid) > /dev/null 2>&1; then \
		echo "  Frontend: ✓ Running (PID: $$(cat logs/frontend.pid))"; \
	else \
		echo "  Frontend: ✗ Not running"; \
	fi
	@if [ -f logs/worker.pid ] && ps -p $$(cat logs/worker.pid) > /dev/null 2>&1; then \
		echo "  Worker:   ✓ Running (PID: $$(cat logs/worker.pid))"; \
	else \
		echo "  Worker:   ✗ Not running"; \
	fi

health:
	@echo "Running health checks..."
	@echo ""
	@echo -n "PostgreSQL:  "
	@curl -s -o /dev/null -w "%{http_code}" http://localhost:5432 2>/dev/null && echo "✓ Reachable" || echo "✗ Not reachable"
	@echo -n "Redis:       "
	@curl -s -o /dev/null -w "%{http_code}" http://localhost:6379 2>/dev/null && echo "✓ Reachable" || echo "✗ Not reachable"
	@echo -n "Qdrant:      "
	@curl -s -o /dev/null -w "%{http_code}" http://localhost:6333 | grep -q "200\|404" && echo "✓ Healthy" || echo "✗ Unhealthy"
	@echo -n "LiveKit:     "
	@curl -s http://localhost:7880 | grep -q "OK" && echo "✓ Healthy" || echo "✗ Unhealthy"
	@echo -n "Backend API: "
	@curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/api/v1/health | grep -q "200\|404" && echo "✓ Healthy" || echo "✗ Unhealthy"
	@echo -n "Frontend:    "
	@curl -s -o /dev/null -w "%{http_code}" http://localhost:3000 | grep -q "200\|404" && echo "✓ Healthy" || echo "✗ Unhealthy"

# Utility targets
clean:
	@echo "Cleaning temporary files..."
	@rm -rf logs/*.log
	@rm -rf logs/*.pid
	@find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	@find . -type f -name "*.pyc" -delete 2>/dev/null || true
	@echo "✓ Cleanup complete"

test:
	@echo "Running tests..."
	@. .venv/bin/activate && pytest tests/ -v

lint:
	@echo "Running linters..."
	@. .venv/bin/activate && ruff check apps/
	@cd apps/web && npm run lint
