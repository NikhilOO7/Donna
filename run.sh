#!/bin/bash
# Quick start script for Voice Document Intelligence System

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colored output
print_info() {
    echo -e "${BLUE}ℹ️  $1${NC}"
}

print_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

print_error() {
    echo -e "${RED}❌ $1${NC}"
}

# Check if Docker is installed
check_docker() {
    if ! command -v docker &> /dev/null; then
        print_error "Docker is not installed. Please install Docker Desktop first."
        echo "Download from: https://www.docker.com/products/docker-desktop/"
        exit 1
    fi

    if ! command -v docker-compose &> /dev/null; then
        print_error "Docker Compose is not installed."
        exit 1
    fi

    print_success "Docker and Docker Compose are installed"
}

# Check if .env file exists
check_env() {
    if [ ! -f .env ]; then
        print_warning ".env file not found. Creating from .env.example..."
        cp .env.example .env
        print_warning "⚠️  Please edit .env and add your API keys before continuing!"
        echo ""
        echo "Required API keys:"
        echo "  - OPENAI_API_KEY"
        echo "  - DEEPGRAM_API_KEY"
        echo "  - CARTESIA_API_KEY"
        echo ""
        echo "Run this script again after updating .env"
        exit 1
    fi

    # Check if API keys are set
    if ! grep -q "OPENAI_API_KEY=sk-" .env; then
        print_error "OPENAI_API_KEY not set in .env file"
        exit 1
    fi

    print_success ".env file configured"
}

# Display menu
show_menu() {
    echo ""
    echo "════════════════════════════════════════════════════"
    echo "  🎙️  Voice Document Intelligence System"
    echo "════════════════════════════════════════════════════"
    echo ""
    echo "Select an option:"
    echo ""
    echo "  1) 🚀 Start Full Stack (All services)"
    echo "  2) 🔧 Start Infrastructure Only (For local dev)"
    echo "  3) 📊 View Service Status"
    echo "  4) 📝 View Logs"
    echo "  5) 🔄 Restart Services"
    echo "  6) 🛑 Stop All Services"
    echo "  7) 🧹 Clean Up (Remove containers and volumes)"
    echo "  8) 🏗️  Build/Rebuild Images"
    echo "  9) ❓ Help"
    echo "  0) 🚪 Exit"
    echo ""
    echo "════════════════════════════════════════════════════"
    echo ""
}

# Start full stack
start_full_stack() {
    print_info "Starting all services (infrastructure + application)..."
    docker-compose up -d

    print_success "Services starting..."
    echo ""
    print_info "Waiting for services to be healthy..."
    sleep 10

    docker-compose ps

    echo ""
    print_success "🎉 All services started!"
    echo ""
    echo "Access points:"
    echo "  🌐 Frontend:        http://localhost:3000"
    echo "  🔧 Backend API:     http://localhost:8000"
    echo "  📚 API Docs:        http://localhost:8000/docs"
    echo "  🗄️  MinIO Console:   http://localhost:9001 (voicedoc/voicedoc123)"
    echo "  📊 Qdrant:          http://localhost:6333/dashboard"
    echo ""
    echo "View logs with: docker-compose logs -f"
}

# Start infrastructure only
start_infrastructure() {
    print_info "Starting infrastructure services only..."
    docker-compose -f infrastructure/local/docker-compose-minimal.yml up -d

    print_success "Infrastructure services starting..."
    echo ""
    print_info "Waiting for services to be healthy..."
    sleep 10

    docker-compose -f infrastructure/local/docker-compose-minimal.yml ps

    echo ""
    print_success "Infrastructure ready!"
    echo ""
    echo "Now you can run the application locally:"
    echo ""
    echo "  Backend:"
    echo "    uv run uvicorn apps.api.main:app --host 0.0.0.0 --port 8000 --reload"
    echo ""
    echo "  Frontend:"
    echo "    cd apps/web && pnpm run dev"
    echo ""
    echo "  Voice Worker:"
    echo "    uv run python -m apps.api.services.voice.enhanced_livekit_service"
    echo ""
}

# View status
view_status() {
    print_info "Service Status:"
    echo ""
    docker-compose ps
    echo ""

    print_info "Resource Usage:"
    docker stats --no-stream --format "table {{.Container}}\t{{.CPUPerc}}\t{{.MemUsage}}"
}

# View logs
view_logs() {
    echo ""
    echo "Which service logs do you want to view?"
    echo "  1) All services"
    echo "  2) Backend"
    echo "  3) Frontend"
    echo "  4) Voice Worker"
    echo "  5) PostgreSQL"
    echo "  6) Redis"
    echo "  7) Qdrant"
    echo ""
    read -p "Enter choice [1-7]: " log_choice

    case $log_choice in
        1) docker-compose logs -f ;;
        2) docker-compose logs -f backend ;;
        3) docker-compose logs -f frontend ;;
        4) docker-compose logs -f voice-worker ;;
        5) docker-compose logs -f postgres ;;
        6) docker-compose logs -f redis ;;
        7) docker-compose logs -f qdrant ;;
        *) print_error "Invalid choice" ;;
    esac
}

# Restart services
restart_services() {
    echo ""
    echo "Which services do you want to restart?"
    echo "  1) All services"
    echo "  2) Backend only"
    echo "  3) Frontend only"
    echo "  4) Voice Worker only"
    echo "  5) Infrastructure only"
    echo ""
    read -p "Enter choice [1-5]: " restart_choice

    case $restart_choice in
        1) docker-compose restart ;;
        2) docker-compose restart backend ;;
        3) docker-compose restart frontend ;;
        4) docker-compose restart voice-worker ;;
        5) docker-compose restart postgres redis qdrant minio livekit ;;
        *) print_error "Invalid choice" ;;
    esac

    print_success "Services restarted"
}

# Stop services
stop_services() {
    print_warning "Stopping all services..."
    docker-compose down
    print_success "All services stopped"
}

# Clean up
clean_up() {
    print_warning "⚠️  This will remove all containers and volumes (DATA WILL BE LOST)"
    read -p "Are you sure? (yes/no): " confirm

    if [ "$confirm" = "yes" ]; then
        print_info "Cleaning up..."
        docker-compose down -v
        docker system prune -f
        print_success "Cleanup complete"
    else
        print_info "Cleanup cancelled"
    fi
}

# Build images
build_images() {
    print_info "Building Docker images..."
    docker-compose build --no-cache
    print_success "Images built successfully"
}

# Show help
show_help() {
    echo ""
    echo "📚 Quick Help"
    echo ""
    echo "Full documentation: See DOCKER_SETUP.md"
    echo ""
    echo "Common commands:"
    echo "  Start:     docker-compose up -d"
    echo "  Stop:      docker-compose down"
    echo "  Logs:      docker-compose logs -f"
    echo "  Status:    docker-compose ps"
    echo "  Rebuild:   docker-compose up -d --build"
    echo ""
    echo "Troubleshooting:"
    echo "  - Check logs if services fail to start"
    echo "  - Ensure API keys are set in .env"
    echo "  - Make sure ports are not in use"
    echo "  - Run 'docker-compose down -v' for clean restart"
    echo ""
    read -p "Press Enter to continue..."
}

# Main loop
main() {
    check_docker
    check_env

    while true; do
        show_menu
        read -p "Enter your choice [0-9]: " choice

        case $choice in
            1) start_full_stack ;;
            2) start_infrastructure ;;
            3) view_status ;;
            4) view_logs ;;
            5) restart_services ;;
            6) stop_services ;;
            7) clean_up ;;
            8) build_images ;;
            9) show_help ;;
            0)
                print_info "Goodbye!"
                exit 0
                ;;
            *)
                print_error "Invalid option. Please try again."
                sleep 2
                ;;
        esac

        echo ""
        read -p "Press Enter to continue..."
    done
}

# Run main function
main
