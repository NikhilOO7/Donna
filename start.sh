#!/bin/bash
# Unified startup script for Voice Document Intelligence
# This script starts all services in the correct order

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PATH="$PROJECT_ROOT/.venv"
BACKEND_PORT=8000
FRONTEND_PORT=3000
WORKER_LOG="$PROJECT_ROOT/logs/worker.log"
BACKEND_LOG="$PROJECT_ROOT/logs/backend.log"
FRONTEND_LOG="$PROJECT_ROOT/logs/frontend.log"

# Create logs directory
mkdir -p "$PROJECT_ROOT/logs"

# Function to print colored messages
print_step() {
    echo -e "${BLUE}==>${NC} $1"
}

print_success() {
    echo -e "${GREEN}✓${NC} $1"
}

print_error() {
    echo -e "${RED}✗${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}⚠${NC} $1"
}

# Function to check if a port is in use
check_port() {
    lsof -ti:$1 > /dev/null 2>&1
}

# Function to kill process on port
kill_port() {
    if check_port $1; then
        print_warning "Port $1 is in use. Killing existing process..."
        lsof -ti:$1 | xargs kill -9 2>/dev/null || true
        sleep 2
    fi
}

# Function to wait for service
wait_for_service() {
    local url=$1
    local name=$2
    local max_attempts=30
    local attempt=0

    print_step "Waiting for $name to be ready..."
    while [ $attempt -lt $max_attempts ]; do
        if curl -s -o /dev/null -w "%{http_code}" "$url" | grep -q "200\|404\|OK"; then
            print_success "$name is ready!"
            return 0
        fi
        attempt=$((attempt + 1))
        sleep 1
    done

    print_error "$name failed to start within $max_attempts seconds"
    return 1
}

# Function to cleanup on exit
cleanup() {
    print_step "Shutting down services..."

    # Kill background processes
    jobs -p | xargs -r kill 2>/dev/null || true

    print_success "Cleanup complete"
    exit 0
}

trap cleanup SIGINT SIGTERM

# Main script
echo -e "${GREEN}"
echo "╔═══════════════════════════════════════════════════════════╗"
echo "║   Voice Document Intelligence - Unified Startup           ║"
echo "╚═══════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# Step 1: Check prerequisites
print_step "Checking prerequisites..."

if [ ! -f "$PROJECT_ROOT/.env" ]; then
    print_error ".env file not found. Please create one from .env.example"
    exit 1
fi

if [ ! -d "$VENV_PATH" ]; then
    print_error "Virtual environment not found at $VENV_PATH"
    print_warning "Please run: python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"
    exit 1
fi

if ! command -v docker &> /dev/null; then
    print_error "Docker is not installed. Please install Docker first."
    exit 1
fi

if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null; then
    print_error "Docker Compose is not installed. Please install Docker Compose first."
    exit 1
fi

if [ ! -d "$PROJECT_ROOT/apps/web/node_modules" ]; then
    print_error "Frontend dependencies not installed"
    print_warning "Please run: cd apps/web && npm install"
    exit 1
fi

print_success "All prerequisites met"

# Step 2: Start Docker services
print_step "Starting Docker services (PostgreSQL, Redis, Qdrant, LiveKit)..."

cd "$PROJECT_ROOT/infrastructure/local"

# Check if we should use 'docker compose' or 'docker-compose'
if docker compose version &> /dev/null; then
    DOCKER_COMPOSE_CMD="docker compose"
else
    DOCKER_COMPOSE_CMD="docker-compose"
fi

$DOCKER_COMPOSE_CMD up -d postgres redis-stack qdrant livekit

cd "$PROJECT_ROOT"

# Wait for services to be healthy
wait_for_service "http://localhost:5432" "PostgreSQL" || true
wait_for_service "http://localhost:6379" "Redis" || true
wait_for_service "http://localhost:6333" "Qdrant"
wait_for_service "http://localhost:7880" "LiveKit"

print_success "All Docker services are running"

# Step 3: Kill any processes on required ports
print_step "Checking for port conflicts..."
kill_port $BACKEND_PORT
kill_port $FRONTEND_PORT

# Step 4: Start Backend API
print_step "Starting Backend API on port $BACKEND_PORT..."
cd "$PROJECT_ROOT"
source "$VENV_PATH/bin/activate"
nohup uvicorn apps.api.main:app --host 0.0.0.0 --port $BACKEND_PORT --reload > "$BACKEND_LOG" 2>&1 &
BACKEND_PID=$!
echo $BACKEND_PID > "$PROJECT_ROOT/logs/backend.pid"

sleep 3
wait_for_service "http://localhost:$BACKEND_PORT/api/v1/health" "Backend API" || print_warning "Backend may still be starting..."

print_success "Backend API started (PID: $BACKEND_PID)"
print_success "Backend logs: $BACKEND_LOG"

# Step 5: Start Frontend
print_step "Starting Frontend on port $FRONTEND_PORT..."
cd "$PROJECT_ROOT/apps/web"
nohup npm run dev > "$FRONTEND_LOG" 2>&1 &
FRONTEND_PID=$!
echo $FRONTEND_PID > "$PROJECT_ROOT/logs/frontend.pid"

cd "$PROJECT_ROOT"
sleep 3
print_success "Frontend started (PID: $FRONTEND_PID)"
print_success "Frontend logs: $FRONTEND_LOG"

# Step 6: Start LiveKit Voice Agent Worker
print_step "Starting LiveKit Voice Agent Worker..."
cd "$PROJECT_ROOT"
source "$VENV_PATH/bin/activate"
nohup python apps/workers/enhanced_voice_agent_worker.py start > "$WORKER_LOG" 2>&1 &
WORKER_PID=$!
echo $WORKER_PID > "$PROJECT_ROOT/logs/worker.pid"

sleep 2
print_success "Voice Agent Worker started (PID: $WORKER_PID)"
print_success "Worker logs: $WORKER_LOG"

# Summary
echo ""
echo -e "${GREEN}╔═══════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║              All Services Started Successfully!           ║${NC}"
echo -e "${GREEN}╚═══════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${BLUE}Services:${NC}"
echo "  • PostgreSQL:    http://localhost:5432"
echo "  • Redis:         http://localhost:6379"
echo "  • Qdrant:        http://localhost:6333"
echo "  • LiveKit:       http://localhost:7880"
echo "  • Backend API:   http://localhost:$BACKEND_PORT"
echo "  • Frontend:      http://localhost:$FRONTEND_PORT"
echo ""
echo -e "${BLUE}Logs:${NC}"
echo "  • Backend:  tail -f $BACKEND_LOG"
echo "  • Frontend: tail -f $FRONTEND_LOG"
echo "  • Worker:   tail -f $WORKER_LOG"
echo ""
echo -e "${BLUE}Documentation:${NC}"
echo "  • API Docs:      http://localhost:$BACKEND_PORT/docs"
echo "  • Qdrant UI:     http://localhost:6333/dashboard"
echo "  • Redis Insight: http://localhost:8001"
echo ""
echo -e "${YELLOW}Press Ctrl+C to stop all services${NC}"
echo ""

# Wait for user interrupt
while true; do
    sleep 1
done
