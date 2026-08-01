# LinkedIn post — copy below the line

---

One missing character shipped a feature that silently did nothing for its entire life.

A regex \b can't sit between a space and a "$". So my fact-checking agent — built to verify money claims in live meetings — never matched a single one. Every test was green.

My eval harness caught it in its first 30 seconds. Along with two more bugs, same morning.

I've spent the last months building Donna: an AI meeting collaborator that preps before, listens during, and remembers after. 19 agents, 4 pipelines, 10 containers. Somewhere along the way it stopped being a product project and became a course in AI infrastructure.

The 5 lessons I'd hand any team building agents:

1️⃣ Evals are unit tests for intelligence.
Golden datasets, metric floors, gated in CI. My fact-check recall was 0.73 and nobody knew. Now a prompt tweak that makes the product dumber fails the build exactly like a broken function.

2️⃣ Measure retrieval. The fancy technique lost.
Contextual embeddings — the approach everyone's excited about — scored 0.58 MRR on my benchmark. Naive dense RAG scored 0.845. The technique everyone skips past (fusing with BM25) won at 0.929. That lift is now a CI gate too.

3️⃣ Never let a barrier make fast agents slow.
My first dispatcher used asyncio.gather: a 200ms "your expertise is needed" nudge waited behind a 20-second web search. Nine agents now stream with per-agent timeouts — every insight lands the moment it's ready. The barrier was the bug.

4️⃣ A typical utterance through 9 agents costs $0.
Free deterministic gates in front of every model call. gpt-4o-mini for extraction, gpt-4o only where prose is the product. Every call metered per-meeting in micro-USD. You can't price a product on costs you don't measure.

5️⃣ The scariest bugs don't crash.
Pydantic v2 silently ignored my env= config — production mode had never actually applied. A cache key without "who is asking" was one deploy from leaking answers across tenants. Both found by tests that assert outcomes, not absence of errors.

The thread through all five: a claim without a gate regresses silently.

Ship the measurement with the feature.

(Full breakdown in the carousel 👇 — real numbers, real bugs, real diagrams.)

#AIEngineering #LLM #RAG #AIInfrastructure #MLOps

---

## Posting notes
- Attach `donna-carousel.pdf` as a LinkedIn *document* for the swipeable carousel,
  or upload the six PNGs (1080×1350, LinkedIn's preferred 4:5) as a multi-image post.
- The first two lines are the hook shown above the fold — don't add anything before them.
- Best engagement windows: Tue–Thu mornings. Reply to early comments fast; the
  algorithm rewards first-hour conversation.
- If someone asks for depth in comments, the war-story details make perfect replies.
