# apps/workers/voice_agent_worker.py
"""
Voice Agent Worker - Production implementation with Deepgram Nova-3 + Cartesia Sonic + LiveKit
Full implementation with contextual embeddings and document intelligence
"""

import asyncio
import logging
import signal
import sys
import time
from pathlib import Path
from typing import Any, Dict

import aiohttp
from aiohttp import web
from prometheus_client import Counter, Gauge, Histogram, start_http_server

# Add the project root to Python path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from livekit.agents import cli

from apps.api.core.config import settings
from apps.api.core.connections import (
    get_qdrant_client,
    get_redis_client,
    init_qdrant,
    init_redis,
    init_storage,
)
from apps.api.core.database import init_db
from apps.api.services.voice.enhanced_livekit_service import create_worker_options

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.log_level, "INFO"),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("voice_agent.log"),
    ],
)

logger = logging.getLogger("voice-agent-worker")

# Prometheus metrics
session_counter = Counter("voice_sessions_total", "Total number of voice sessions")
error_counter = Counter("voice_errors_total", "Total number of errors", ["error_type"])
latency_histogram = Histogram(
    "voice_latency_seconds", "Voice pipeline latency", ["component"]
)
concurrent_sessions = Gauge(
    "voice_concurrent_sessions", "Number of concurrent sessions"
)
tokens_processed = Counter(
    "voice_tokens_processed_total", "Total tokens processed", ["model"]
)
embeddings_generated = Counter(
    "embeddings_generated_total", "Total embeddings generated", ["level"]
)


class MetricsCollector:
    """Collect and expose metrics for monitoring"""

    def __init__(self):
        self.start_time = asyncio.get_event_loop().time()
        self._active_sessions = {}

    def record_session_start(self, session_id: str):
        session_counter.inc()
        concurrent_sessions.inc()
        self._active_sessions[session_id] = time.time()
        logger.info(
            f"Session started: {session_id}, active sessions: {len(self._active_sessions)}"
        )

    def record_session_end(self, session_id: str):
        concurrent_sessions.dec()
        if session_id in self._active_sessions:
            duration = time.time() - self._active_sessions[session_id]
            latency_histogram.labels(component="session").observe(duration)
            del self._active_sessions[session_id]
        logger.info(
            f"Session ended: {session_id}, active sessions: {len(self._active_sessions)}"
        )

    def record_error(self, error_type: str):
        error_counter.labels(error_type=error_type).inc()
        logger.error(f"Error recorded: {error_type}")

    def record_latency(self, component: str, duration: float):
        latency_histogram.labels(component=component).observe(duration)

    def record_tokens(self, model: str, count: int):
        tokens_processed.labels(model=model).inc(count)

    def record_embedding(self, level: str):
        embeddings_generated.labels(level=level).inc()


# Global metrics collector
metrics = MetricsCollector()


async def health_check_server():
    """Run a health check server for monitoring"""

    async def health(request):
        """Health check endpoint"""
        health_status = await check_system_health()

        return web.json_response(
            {
                "status": health_status["status"],
                "uptime": asyncio.get_event_loop().time() - metrics.start_time,
                "concurrent_sessions": len(metrics._active_sessions),
                "environment": settings.environment,
                "services": health_status["services"],
                "voice_config": {
                    "stt": "deepgram_nova3",
                    "tts": "cartesia_sonic",
                    "infrastructure": "livekit",
                },
            }
        )

    async def metrics_endpoint(request):
        """Prometheus metrics endpoint"""
        from prometheus_client import generate_latest

        return web.Response(body=generate_latest(), content_type="text/plain")

    app = web.Application()
    app.router.add_get("/health", health)
    app.router.add_get("/metrics", metrics_endpoint)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 8081)
    await site.start()
    logger.info("Health check server running on http://0.0.0.0:8081/health")


async def check_system_health() -> Dict[str, Any]:
    """Check health of all dependent services"""
    services_health = {}
    overall_status = "healthy"

    # Check Deepgram
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://api.deepgram.com/v1/projects",
                headers={"Authorization": f"Token {settings.deepgram_api_key}"},
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                services_health["deepgram"] = (
                    "healthy" if resp.status == 200 else "unhealthy"
                )
    except Exception as e:
        services_health["deepgram"] = "unhealthy"
        overall_status = "degraded"
        logger.error(f"Deepgram health check failed: {e}")

    # Check Cartesia
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://api.cartesia.ai/health",
                headers={"X-API-Key": settings.cartesia_api_key},
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                services_health["cartesia"] = (
                    "healthy" if resp.status == 200 else "unhealthy"
                )
    except Exception as e:
        services_health["cartesia"] = "unhealthy"
        overall_status = "degraded"
        logger.error(f"Cartesia health check failed: {e}")

    # Check LiveKit
    try:
        import socket

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        result = sock.connect_ex(("localhost", 7880))
        sock.close()
        services_health["livekit"] = "healthy" if result == 0 else "unhealthy"
    except Exception as e:
        services_health["livekit"] = "unhealthy"
        overall_status = "degraded"
        logger.error(f"LiveKit health check failed: {e}")

    # Check Redis
    try:
        redis_client = await get_redis_client()
        await redis_client.ping()
        services_health["redis"] = "healthy"
    except Exception as e:
        services_health["redis"] = "unhealthy"
        overall_status = "degraded"
        logger.error(f"Redis health check failed: {e}")

    # Check Qdrant
    try:
        await get_qdrant_client()
        # Simple check - adjust based on your Qdrant setup
        services_health["qdrant"] = "healthy"
    except Exception as e:
        services_health["qdrant"] = "unhealthy"
        overall_status = "degraded"
        logger.error(f"Qdrant health check failed: {e}")

    return {"status": overall_status, "services": services_health}


def validate_configuration() -> bool:
    """Validate required configuration"""
    errors = []

    # Check required API keys
    if not settings.deepgram_api_key:
        errors.append("DEEPGRAM_API_KEY is required")
    if not settings.cartesia_api_key:
        errors.append("CARTESIA_API_KEY is required")
    if not settings.openai_api_key:
        errors.append("OPENAI_API_KEY is required")
    if not settings.livekit_api_key or settings.livekit_api_key == "devkey":
        errors.append("LIVEKIT_API_KEY should be set for production")
    if not settings.livekit_api_secret or settings.livekit_api_secret == "secret":
        errors.append("LIVEKIT_API_SECRET should be set for production")

    # Check service URLs
    if not settings.livekit_url:
        errors.append("LIVEKIT_URL is required")

    # Voice configuration
    voice_config_errors = []
    if not hasattr(settings, "voice_pipeline_config"):
        voice_config_errors.append("voice_pipeline_config not found in settings")
    else:
        required_configs = [
            "vad_threshold",
            "silence_duration_ms",
            "min_speech_duration_ms",
        ]
        for config in required_configs:
            if config not in settings.voice_pipeline_config:
                voice_config_errors.append(f"Missing {config} in voice_pipeline_config")

    if voice_config_errors:
        errors.extend(voice_config_errors)

    if errors:
        for error in errors:
            logger.error(f"Configuration error: {error}")
        return False

    return True


async def initialize_services():
    """Initialize all required services"""
    logger.info("Initializing services...")

    try:
        # Initialize database
        logger.info("Initializing database...")
        await init_db()

        # Initialize Redis
        logger.info("Initializing Redis...")
        await init_redis()

        # Initialize Qdrant
        logger.info("Initializing Qdrant...")
        await init_qdrant()

        # Initialize storage (MinIO)
        logger.info("Initializing storage...")
        await init_storage()

        logger.info("All services initialized successfully")
        return True

    except Exception as e:
        logger.error(f"Service initialization failed: {e}")
        return False


async def graceful_shutdown(signal_received):
    """Handle graceful shutdown"""
    logger.info(f"Received signal {signal_received}, shutting down gracefully...")

    # Close active sessions
    for session_id in list(metrics._active_sessions.keys()):
        metrics.record_session_end(session_id)

    # Add any cleanup tasks here
    logger.info("Graceful shutdown complete")


async def main():
    """Enhanced main entry point with monitoring and health checks"""

    logger.info("=" * 60)
    logger.info("Document Intelligence Voice Agent Worker Starting")
    logger.info(f"Environment: {settings.environment}")
    logger.info("Voice Stack: Deepgram Nova-3 + Cartesia Sonic + LiveKit")
    logger.info(f"Log Level: {settings.log_level}")
    logger.info("=" * 60)

    # Validate configuration
    if not validate_configuration():
        logger.error("Configuration validation failed. Exiting.")
        sys.exit(1)

    # Initialize services
    if not await initialize_services():
        logger.error("Service initialization failed. Exiting.")
        sys.exit(1)

    # Start Prometheus metrics server
    if settings.enable_metrics:
        start_http_server(9091)
        logger.info("Prometheus metrics available at http://localhost:9091/metrics")

    # Start health check server
    await health_check_server()

    # Check system health
    health_status = await check_system_health()
    logger.info(f"System health check: {health_status}")

    if health_status["status"] == "unhealthy":
        logger.error("System health check failed. Some services are unavailable.")
        sys.exit(1)

    # Log voice pipeline configuration
    logger.info("Voice Pipeline Configuration:")
    if hasattr(settings, "voice_pipeline_config"):
        for key, value in settings.voice_pipeline_config.items():
            logger.info(f"  {key}: {value}")

    # Create worker options
    worker_options = create_worker_options()

    # Set up graceful shutdown
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(
            sig, lambda s=sig: asyncio.create_task(graceful_shutdown(s))
        )

    try:
        # Log startup complete
        logger.info("Starting LiveKit agent worker...")
        logger.info(f"Accepting connections on: {settings.livekit_url}")
        logger.info("Voice Agent Worker is ready for connections!")

        # Run the worker
        await cli.run_app(worker_options)

    except KeyboardInterrupt:
        logger.info("Worker stopped by user")
    except Exception as e:
        logger.error(f"Worker failed: {e}")
        metrics.record_error("worker_crash")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
