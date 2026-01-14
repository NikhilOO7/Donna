#!/bin/bash
# Stop script for Voice Document Intelligence

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

print_step() {
    echo -e "${BLUE}==>${NC} $1"
}

print_success() {
    echo -e "${GREEN}✓${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}⚠${NC} $1"
}

echo -e "${YELLOW}"
echo "╔═══════════════════════════════════════════════════════════╗"
echo "║         Stopping Voice Document Intelligence             ║"
echo "╚═══════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# Stop application services
print_step "Stopping application services..."

if [ -f "$PROJECT_ROOT/logs/backend.pid" ]; then
    PID=$(cat "$PROJECT_ROOT/logs/backend.pid")
    if ps -p $PID > /dev/null 2>&1; then
        kill $PID 2>/dev/null && print_success "Backend stopped" || print_warning "Backend already stopped"
    fi
    rm "$PROJECT_ROOT/logs/backend.pid"
fi

if [ -f "$PROJECT_ROOT/logs/frontend.pid" ]; then
    PID=$(cat "$PROJECT_ROOT/logs/frontend.pid")
    if ps -p $PID > /dev/null 2>&1; then
        kill $PID 2>/dev/null && print_success "Frontend stopped" || print_warning "Frontend already stopped"
    fi
    rm "$PROJECT_ROOT/logs/frontend.pid"
fi

if [ -f "$PROJECT_ROOT/logs/worker.pid" ]; then
    PID=$(cat "$PROJECT_ROOT/logs/worker.pid")
    if ps -p $PID > /dev/null 2>&1; then
        kill $PID 2>/dev/null && print_success "Worker stopped" || print_warning "Worker already stopped"
    fi
    rm "$PROJECT_ROOT/logs/worker.pid"
fi

# Stop Docker services
print_step "Stopping Docker services..."

cd "$PROJECT_ROOT/infrastructure/local"

if docker compose version &> /dev/null; then
    docker compose down
elif command -v docker-compose &> /dev/null; then
    docker-compose down
else
    print_warning "Docker Compose not found, skipping Docker cleanup"
fi

cd "$PROJECT_ROOT"

echo ""
print_success "All services stopped successfully"
