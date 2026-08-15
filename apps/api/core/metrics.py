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

# Voice pipeline latency. Buckets straddle the sub-200ms perceived-latency target
# (config.target_*_latency_ms) so the histogram quantiles directly answer "are we
# under 200ms?". `stage` is one of: stt, tts, llm, end_to_end.
VOICE_LATENCY_SECONDS = Histogram(
    "voice_latency_seconds",
    "Voice pipeline latency by stage",
    ["stage"],
    buckets=(0.05, 0.08, 0.1, 0.15, 0.2, 0.3, 0.5, 1.0, 2.0),
)


def observe_voice_latency(stage: str, latency_ms: float) -> None:
    """Record a voice-pipeline stage latency (milliseconds) into Prometheus.

    Single choke-point so the voice services and workers all report the same way.
    `stage`: "stt" | "tts" | "llm" | "end_to_end".
    """
    VOICE_LATENCY_SECONDS.labels(stage=stage).observe(max(latency_ms, 0.0) / 1000.0)


# ---------------------------------------------------------------------------
# Cache metrics
# ---------------------------------------------------------------------------
CACHE_HITS = Counter("cache_hits_total", "Cache hits", ["cache_name"])
CACHE_MISSES = Counter("cache_misses_total", "Cache misses", ["cache_name"])


# ---------------------------------------------------------------------------
# End-to-end nudge latency
# ---------------------------------------------------------------------------
# The "< 2s to first insight" claim was structural, not observed: the 2s
# activation timeout bounds AGENT EXECUTION, but the number a user actually
# experiences also includes the utterance POST, the queue hop, state loading,
# persistence and WS delivery — a chain that had never been timed end to end.
#
# The clock starts when the utterance is accepted (the first moment the system
# knows the words exist) and stops when each nudge is broadcast. Bucketed
# around the budgets in the architecture book: 2s first-insight, 12s LLM.
NUDGE_END_TO_END_SECONDS = Histogram(
    "nudge_end_to_end_seconds",
    "Utterance accepted -> nudge broadcast, per agent",
    ["agent", "nudge_type"],
    buckets=(0.1, 0.25, 0.5, 1.0, 2.0, 4.0, 8.0, 12.0, 20.0, 30.0, 60.0),
)

# Time from utterance acceptance to the FIRST nudge of a dispatch cycle —
# the number that corresponds to "time to first insight".
FIRST_NUDGE_SECONDS = Histogram(
    "first_nudge_seconds",
    "Utterance accepted -> first nudge of that dispatch cycle",
    buckets=(0.1, 0.25, 0.5, 1.0, 2.0, 4.0, 8.0, 12.0, 20.0, 30.0, 60.0),
)

# ---------------------------------------------------------------------------
# Knowledge-graph replication (outbox)
# ---------------------------------------------------------------------------
# Postgres→Neo4j divergence used to be invisible: a failed sync logged
# "KG sync skipped" and the graph fell permanently behind. These make the
# backlog and any permanent failure alertable rather than merely loggable.
KG_OUTBOX_PENDING = Gauge(
    "donna_kg_outbox_pending",
    "Outbox entries waiting to be applied to Neo4j",
)
KG_OUTBOX_FAILED = Gauge(
    "donna_kg_outbox_failed",
    "Outbox entries that exhausted retries — Postgres and Neo4j disagree",
)
KG_OUTBOX_OLDEST_PENDING = Gauge(
    "donna_kg_outbox_oldest_pending_seconds",
    "Age of the oldest pending outbox entry (replication lag)",
)


# How long a dispatch job waited in the queue before a worker picked it up.
# Separates "the agents were slow" from "nothing was consuming the queue" —
# the two look identical in end-to-end latency alone.
DISPATCH_QUEUE_WAIT_SECONDS = Histogram(
    "dispatch_queue_wait_seconds",
    "Utterance accepted -> dispatch cycle started",
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 15.0, 60.0),
)


def metrics_response():
    """Generate Prometheus metrics response bytes."""
    return generate_latest()


def metrics_content_type():
    """Return the Prometheus content type header value."""
    return CONTENT_TYPE_LATEST
