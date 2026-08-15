# Service Level Objectives

Targets, the metric that measures each, and — stated plainly — whether the
number is **observed** or merely **intended**. An SLO with no backing metric
is a slogan, so each row names the Prometheus series that proves or disproves
it, or says that none exists yet.

Status vocabulary:

- **measured** — a metric exists and is emitted in production
- **bounded** — enforced structurally (a timeout), but the real distribution
  is not observed
- **unmeasured** — no instrumentation; the number is an intention

## Latency

| Objective | Target | Status | Metric |
|---|---|---|---|
| Utterance → first nudge | p95 < 2s | **measured** | `first_nudge_seconds` |
| Utterance → any nudge, per agent | p95 < 12s (LLM agents) | **measured** | `nudge_end_to_end_seconds{agent,nudge_type}` |
| Dispatch queue wait | p95 < 1s | **measured** | `dispatch_queue_wait_seconds` |
| WebSocket fan-out | < 50ms | **measured** (test) | `tests/benchmarks/test_ws_fanout.py` |
| RAG query | p95 < 3s | **measured** | `rag_query_duration_seconds` |
| Upload → API response | < 1s | bounded | processing is enqueued, not inline |
| Document processing | < 5min typical | unmeasured | job duration not histogrammed |

`first_nudge_seconds` is the honest version of the "time to first insight"
claim. The older statement rested on the activation agent's 2s *timeout*,
which bounds agent execution only — it excluded the POST, the queue hop,
persistence and WS delivery. The metric now covers the whole chain.

## Correctness & quality

| Objective | Target | Status | Metric |
|---|---|---|---|
| Tenant isolation | zero cross-owner reads | **enforced** | `tests/unit/test_auth_security.py`, owner filters at 4 layers |
| Deterministic agent quality | ≥ floors in `evals/baselines.json` | **gated** | eval harness, CI-blocking |
| Retrieval lift vs naive RAG | MRR lift ≥ 0.0333 | **gated** | `retrieval` suite |
| Groundedness detection recall | ≥ 0.90 | **gated** | `groundedness` suite |
| Groundedness false alarms | ≤ 0.10 (ceiling) | **gated** | `groundedness` suite |
| Transcription accuracy (WER) | undefined | **unmeasured** | needs a labelled audio corpus |

## Availability & durability

| Objective | Target | Status | Notes |
|---|---|---|---|
| API availability | undefined | **unmeasured** | single instance, no HA, no LB |
| Graph consistency lag | < 10 min | **measured** | `/health` → `kg_outbox.oldest_pending_age_seconds` |
| Known graph divergence | zero | **measured** | `/health` → `kg_outbox.graph_diverged` |
| Job durability | no silent loss | **enforced** | Arq persists to Redis; `on_job_failure` logs exhaustion |
| RPO | undefined | **unmeasured** | no scheduled production backup — ADR-008 |
| RTO | undefined | **unmeasured** | restore procedure tested weekly; production restore untimed |

## Cost

| Objective | Target | Status | Metric |
|---|---|---|---|
| Cost per meeting | known per meeting | **measured** | `GET /api/v1/meetings/{id}/cost` |
| Typical meeting-hour cost | characterized | **unmeasured** | no representative meeting measured — see `scripts/characterize-cost.py` |
| Silent utterance cost | $0 | **enforced** | deterministic gates (ADR-010) |

## Alerting

Rules live in `infrastructure/local/alerts.yml`, mounted into Prometheus at
`/etc/prometheus/alerts.yml`. Every rule corresponds to a row above that is
**measured** — nothing here alerts on an `unmeasured` target, because a rule
whose metric does not exist can never fire while looking like coverage.

Validate after editing:

```bash
docker run --rm -v "$PWD/infrastructure/local/alerts.yml:/a.yml:ro" \
  --entrypoint promtool prom/prometheus:latest check rules /a.yml
```

| Alert | Severity | Fires when |
|---|---|---|
| `KnowledgeGraphDiverged` | critical | any outbox entry permanently failed |
| `KnowledgeGraphLagging` | warning | oldest pending write > 10 min |
| `FirstNudgeSlow` | warning | first-nudge p95 > 2s for 15m |
| `DispatchQueueStarved` | critical | queue wait p95 > 5s (worker not draining) |
| `LLMNudgeSlow` | warning | LLM-agent nudge p95 > 12s |
| `RAGQuerySlow` | warning | RAG p95 > 3s |
| `CircuitBreakerOpen` | warning | calls rejected without being attempted |
| `ExternalAPIErrorRate` | warning | provider error rate > 25% |
| `EmbeddingCacheIneffective` | warning | hit rate < 30% for 30m (cost control) |
| `APIDown` / `HTTPErrorRate` | critical | scrape failing / 5xx > 5% |

## Error budget policy

There is no error-budget policy yet, and inventing one before availability is
measured would be theatre. The honest sequencing is:

1. Measure availability (needs the HA work in ADR-008's neighbourhood).
2. Set an availability SLO from observed baseline, not aspiration.
3. Then define an error budget and what burning it forbids.

## How to check these right now

```bash
curl -s localhost:8000/health | jq '{status, queues, kg_outbox, circuit_breakers}'
curl -s localhost:8000/metrics | grep -E 'first_nudge|nudge_end_to_end|dispatch_queue_wait'
uv run python -m evals.run --suites deterministic --gate

# Put real load through the latency SLOs and read the histograms back
uv run python scripts/loadtest.py --meetings 5 --utterances 40

# Graph replication health, and how to act on divergence
curl -s localhost:8000/api/v1/admin/kg-outbox -H "Authorization: Bearer $TOKEN" | jq
```
