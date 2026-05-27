"""
Enhanced Voice Agent Worker with Deepgram + Cartesia + LiveKit
Optimized for ultra-low latency meeting assistance
"""

import asyncio
import logging
import signal
import sys
from pathlib import Path

# Add the project root to Python path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

# Load environment variables from .env file
from dotenv import load_dotenv

env_path = project_root / ".env"
if env_path.exists():
    load_dotenv(env_path)
    print(f"✅ Loaded environment from {env_path}")
else:
    print(f"⚠️  No .env file found at {env_path}")

from livekit.agents import cli
from prometheus_client import Counter, Gauge, Histogram, start_http_server

from apps.api.core.config import settings
from apps.api.services.voice.enhanced_livekit_service import create_worker_options

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.log_level),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("enhanced_voice_agent.log"),
    ],
)

logger = logging.getLogger("enhanced-voice-agent-worker")

# Prometheus metrics
session_counter = Counter("voice_sessions_total", "Total number of voice sessions")
error_counter = Counter("voice_errors_total", "Total number of errors", ["error_type"])
latency_histogram = Histogram(
    "voice_latency_seconds", "Voice pipeline latency", ["component"]
)
concurrent_sessions = Gauge(
    "voice_concurrent_sessions", "Number of concurrent sessions"
)


class MetricsCollector:
    """Collect and expose metrics for monitoring"""

    def __init__(self):
        import time

        self.start_time = time.time()

    def record_session_start(self):
        session_counter.inc()
        concurrent_sessions.inc()

    def record_session_end(self):
        concurrent_sessions.dec()

    def record_error(self, error_type: str):
        error_counter.labels(error_type=error_type).inc()

    def record_latency(self, component: str, duration: float):
        latency_histogram.labels(component=component).observe(duration)


# Global metrics collector
metrics = MetricsCollector()


async def health_check_server():
    """Run a simple health check server"""
    from aiohttp import web

    async def health(request):
        return web.json_response(
            {
                "status": "healthy",
                "uptime": asyncio.get_event_loop().time() - metrics.start_time,
                "concurrent_sessions": concurrent_sessions._value.get(),
                "environment": settings.environment,
                "voice_config": settings.voice_pipeline_config,
            }
        )

    app = web.Application()
    app.router.add_get("/health", health)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 8081)
    await site.start()
    logger.info("Health check server running on http://0.0.0.0:8081/health")


def validate_configuration():
    """Validate required configuration (non-blocking)"""
    errors = []

    # Check required API keys only (skip network checks to avoid blocking)
    if not settings.deepgram_api_key:
        errors.append("DEEPGRAM_API_KEY is required")
    if not settings.cartesia_api_key:
        errors.append("CARTESIA_API_KEY is required")
    if not settings.livekit_api_key or settings.livekit_api_key == "devkey":
        logger.warning("LIVEKIT_API_KEY should be set for production")

    # Network connectivity will be checked when first connection is made
    # No need to block initialization with synchronous socket checks

    if errors:
        for error in errors:
            logger.error(f"Configuration error: {error}")
        return False

    logger.info("✅ API keys validated successfully")
    return True


async def main():
    """Enhanced main entry point with monitoring and health checks"""

    logger.info("=" * 50)
    logger.info("Enhanced Voice Agent Worker Starting")
    logger.info(f"Environment: {settings.environment}")
    logger.info("Voice Stack: Deepgram + Cartesia + LiveKit")
    logger.info(f"Target Latency: {settings.target_total_latency_ms}ms")
    logger.info("=" * 50)

    # Validate configuration
    if not validate_configuration():
        logger.error("Configuration validation failed. Exiting.")
        sys.exit(1)

    # Start Prometheus metrics server (non-blocking)
    if settings.enable_metrics:
        try:
            start_http_server(9091)
            logger.info("Prometheus metrics available at http://localhost:9091/metrics")
        except Exception as e:
            logger.warning(f"Could not start Prometheus server: {e}")

    # Health check server will be started after worker is initialized
    # to avoid blocking during process pool initialization

    # Log voice pipeline configuration
    logger.info("Voice Pipeline Configuration:")
    for key, value in settings.voice_pipeline_config.items():
        logger.info(f"  {key}: {value}")

    # Create worker options
    worker_options = create_worker_options()

    # Set up graceful shutdown
    def signal_handler(sig, frame):
        logger.info(f"Received signal {sig}. Shutting down gracefully...")
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        # Run the worker
        logger.info("Starting LiveKit agent worker...")
        await cli.run_app(worker_options)
    except KeyboardInterrupt:
        logger.info("Worker stopped by user")
    except Exception as e:
        logger.error(f"Worker failed: {e}")
        metrics.record_error("worker_crash")
        sys.exit(1)


if __name__ == "__main__":
    # Note: cli.run_app() manages its own event loop, don't use asyncio.run()

    logger.info("=" * 50)
    logger.info("Enhanced Voice Agent Worker Starting")
    logger.info(f"Environment: {settings.environment}")
    logger.info("Voice Stack: Deepgram + Cartesia + LiveKit")
    logger.info(f"Target Latency: {settings.target_total_latency_ms}ms")
    logger.info("=" * 50)

    # Validate configuration (non-blocking checks only)
    if not validate_configuration():
        logger.error("Configuration validation failed. Exiting.")
        sys.exit(1)

    # Start Prometheus metrics server (non-blocking)
    if settings.enable_metrics:
        try:
            start_http_server(9091)
            logger.info("Prometheus metrics available at http://localhost:9091/metrics")
        except Exception as e:
            logger.warning(f"Could not start Prometheus server: {e}")

    # Log voice pipeline configuration
    logger.info("Voice Pipeline Configuration:")
    for key, value in settings.voice_pipeline_config.items():
        logger.info(f"  {key}: {value}")

    # Create worker options
    worker_options = create_worker_options()

    # Run the worker (cli.run_app manages its own event loop)
    logger.info("Starting LiveKit agent worker...")
    cli.run_app(worker_options)
