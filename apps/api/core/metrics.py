"""
Prometheus metrics for the Voice Document Intelligence system.

Exposes request latencies, document processing stats, external API call
metrics, and business-level gauges.
"""

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

# ---------------------------------------------------------------------------
# HTTP request metrics
# ---------------------------------------------------------------------------
HTTP_REQUESTS_TOTAL = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "path", "status"],
)
HTTP_REQUEST_DURATION = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds",
    ["method", "path"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

# ---------------------------------------------------------------------------
# Document processing metrics
# ---------------------------------------------------------------------------
DOCUMENT_PROCESSING_DURATION = Histogram(
    "document_processing_duration_seconds",
    "Time to process a document end-to-end",
    ["processing_method"],
    buckets=(0.5, 1.0, 5.0, 10.0, 30.0, 60.0, 120.0),
)
DOCUMENTS_TOTAL = Gauge(
    "documents_total",
    "Total documents by processing status",
    ["status"],
)

# ---------------------------------------------------------------------------
# RAG / query metrics
# ---------------------------------------------------------------------------
RAG_QUERY_DURATION = Histogram(
    "rag_query_duration_seconds",
    "RAG query processing latency",
    buckets=(0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0),
)

# ---------------------------------------------------------------------------
# External API call metrics
# ---------------------------------------------------------------------------
EXTERNAL_API_CALLS_TOTAL = Counter(
    "external_api_calls_total",
    "Calls to external APIs",
    ["service", "status"],
)
EXTERNAL_API_DURATION = Histogram(
    "external_api_duration_seconds",
    "External API call latency",
    ["service"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)

# ---------------------------------------------------------------------------
# Voice session metrics
# ---------------------------------------------------------------------------
VOICE_SESSIONS_ACTIVE = Gauge(
    "voice_sessions_active",
    "Currently active voice sessions",
)

# ---------------------------------------------------------------------------
# Cache metrics
# ---------------------------------------------------------------------------
CACHE_HITS = Counter("cache_hits_total", "Cache hits", ["cache_name"])
CACHE_MISSES = Counter("cache_misses_total", "Cache misses", ["cache_name"])


def metrics_response():
    """Generate Prometheus metrics response bytes."""
    return generate_latest()


def metrics_content_type():
    """Return the Prometheus content type header value."""
    return CONTENT_TYPE_LATEST
