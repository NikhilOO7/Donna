# ADR-003: Observability Stack Design

## Status
Accepted

## Context
The system makes calls to 4+ external APIs (OpenAI, Deepgram, Cartesia, Qdrant) and runs background document processing tasks. Without structured observability, debugging production issues requires reading unstructured log files and guessing at request flow.

For a demo/interview context, demonstrating production-grade observability signals engineering maturity.

## Decision

### Structured Logging (structlog)
- **Why structlog over loguru**: structlog integrates with Python's stdlib logging (so third-party library logs are captured), produces machine-parseable JSON, and supports context variables natively via `structlog.contextvars`.
- Every log entry includes: `timestamp`, `log_level`, `logger_name`, `request_id`, and any bound context.
- Development uses `ConsoleRenderer` (colored, human-readable). Production uses `JSONRenderer`.

### Request-ID Propagation
- Every incoming request gets a UUID (from `X-Request-ID` header or generated).
- The ID is bound into `structlog.contextvars` so ALL downstream log calls include it automatically - no explicit passing required.
- The ID is returned in the response `X-Request-ID` header for client-side correlation.

### Prometheus Metrics
- Exposed at `GET /metrics` in Prometheus exposition format.
- Key metrics: HTTP request count/latency (by method, path, status), document processing duration, RAG query latency, external API call count/latency (by service), active voice sessions.
- Enables Grafana dashboards and alerting without application changes.

### Circuit Breaker States in Health Check
- `GET /health` includes `circuit_breakers` field showing the state (CLOSED/OPEN/HALF_OPEN) of each external service's circuit breaker.
- Operations teams can see at a glance which external dependencies are healthy.

## Consequences
- **Positive**: Any request can be traced end-to-end via request_id. Log aggregation pipelines (ELK, Datadog) can ingest JSON logs directly.
- **Positive**: Prometheus metrics enable SLA monitoring and capacity planning.
- **Negative**: structlog adds ~1ms overhead per log call (negligible for our latency budget).
- **Negative**: `/metrics` endpoint should be protected in production (not currently behind auth).
