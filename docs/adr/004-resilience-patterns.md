# ADR-004: Resilience Patterns for External API Calls

## Status
Accepted

## Context
The system depends on multiple external APIs (OpenAI for embeddings/chat, Deepgram for STT, Cartesia for TTS, Qdrant for vector search). Any of these can experience:
- Transient network failures
- Rate limiting (429 responses)
- Service outages
- Slow responses under load

Without resilience patterns, a single external API failure cascades through the entire system - a voice query hangs indefinitely, document processing fails silently, or the API returns 500s.

## Decision
We implement a **unified resilience decorator** (`@resilient_call`) in `apps/api/core/resilience.py` that combines three patterns:

### 1. Retry with Exponential Backoff (tenacity)
- Max 3 attempts per call
- Backoff: 1s, 2s, 4s (exponential, capped at 10s)
- Only retries on transient errors: `TimeoutError`, `ConnectionError`, `OSError`
- Does NOT retry on `CircuitOpenError` or application-level errors (400s)

### 2. Circuit Breaker (custom state machine)
- **CLOSED** (normal): Failures counted. After 5 consecutive failures, transitions to OPEN.
- **OPEN** (rejecting): All calls immediately raise `CircuitOpenError`. After 30s recovery timeout, transitions to HALF_OPEN.
- **HALF_OPEN** (probing): One trial call allowed. Success closes the circuit; failure re-opens it.
- Each external service has its own independent breaker (registered globally).

### 3. Timeout per Call
- Default 30s timeout via `asyncio.wait_for()`
- Prevents indefinite hangs on slow external responses

### Instrumentation
- Every call records Prometheus metrics: `external_api_calls_total` (counter with service/status labels) and `external_api_duration_seconds` (histogram).
- Circuit breaker states are exposed in `GET /health` response.

### Why tenacity over backoff
Both libraries are available. tenacity was chosen because it supports async natively, composes with our circuit breaker pattern, and provides `before_sleep_log` for structured logging of retry attempts.

## Consequences
- **Positive**: External API failures are isolated per-service. OpenAI being down doesn't affect Qdrant queries.
- **Positive**: Transient failures (network blips, rate limits) are handled transparently.
- **Positive**: Prometheus metrics enable alerting on failure rate spikes.
- **Negative**: Circuit breaker adds latency to the first call after recovery (HALF_OPEN probe).
- **Negative**: The 30s recovery timeout is a fixed value; adaptive recovery would be more sophisticated but adds complexity.
