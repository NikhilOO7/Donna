# Architecture Decision Records

One file per decision that would be expensive to reverse, in the standard
form: **Context → Decision → Consequences → Revisit when**.

That last section is the one that matters and the one usually omitted. A
technology choice with no stated failure condition is a preference that got
promoted to a decision without an election — so every ADR from 005 onward
names the observation that would mean the bet has gone bad.

Fuller narrative treatment of all of these lives in
`DONNA_DEMO_PRESENTATION.html` (the complete engineering book); these records
keep the rationale greppable next to the code.

| ADR | Decision | Status |
|-----|----------|--------|
| [001](001-contextual-embeddings.md) | Three-level contextual embedding architecture | Accepted |
| [002](002-voice-pipeline-choices.md) | Voice pipeline technology choices | Accepted |
| [003](003-observability-stack.md) | Observability stack design | Accepted |
| [004](004-resilience-patterns.md) | Resilience patterns for external API calls | Accepted |
| [005](005-modular-monolith.md) | Modular monolith + workers, not microservices | Accepted |
| [006](006-redis-five-roles.md) | One Redis for cache, locks, pub/sub, queue, counters | Accepted |
| [007](007-neo4j-optional.md) | Neo4j as an optional enhancer, never a dependency | Accepted — **open pending acceptance data** |
| [008](008-backup-and-restore.md) | Backup/restore tooling + scheduled drill | Accepted — partially implemented |
| [009](009-transactional-outbox.md) | Transactional outbox for Postgres→Neo4j | Accepted |
| [010](010-deterministic-gates.md) | Free deterministic gate before every LLM call | Accepted |
| [011](011-split-job-queues.md) | Split job queues by latency class | Accepted |
| [012](012-groundedness-checking.md) | Deterministic groundedness over an LLM judge | Accepted |
| [013](013-never-speak-ungrounded.md) | Never speak an ungrounded fact-check aloud | Accepted |

## Writing a new one

Copy the shape of [009](009-transactional-outbox.md). Keep it short. The test
of a good ADR is whether someone who disagrees with the decision can tell,
from the record alone, what evidence would change your mind.
