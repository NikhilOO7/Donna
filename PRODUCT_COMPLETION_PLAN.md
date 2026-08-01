# Donna — Product Completion Plan

> Grounded task inventory to finish the product, based on a full code audit (2026-07-30)
> compared against the Donna/AUO vision ("Donna - You are AUO, a proactive meeting
> collaborator.pdf") and `MEETING_ASSISTANT_ROADMAP.md`.
>
> **Status baseline:** the core loop works end-to-end — create meeting → Exa research →
> live transcript + 5 nudge agents → summary + email. This plan covers everything between
> that vertical slice and the finished product.

---

# Part 1 — Audit findings (what this plan is based on)

Three parallel code audits (meeting features · voice/realtime pipeline · RAG/intelligence
stack) were run against the full repo and compared with the PDF vision. Tasks in Part 2
reference these findings.

## Completion scorecard vs the PDF vision

| Area | PDF / AUO vision | Est. done | State |
|---|---|---|---|
| Foundation (docs, RAG, KG, infra) | Document intelligence + knowledge layer | ~85% | Strong; a few integrity issues (C1, C2) |
| DURING meeting — core intelligence | Live transcript + proactive nudges | ~60% | Working & well-engineered; last-mile UI gaps (A2–A5) |
| AFTER meeting | Summary, decisions w/ quotes, exports, memory | ~60% | Summary + email done; quotes, action items, calendar, memory read-back missing |
| BEFORE meeting | Conversational prep, prep cards, agenda, roles | ~35% | Only the research pipeline; the entire prep experience is unbuilt (Workstream D) |
| AUO intelligence foundation | Monitoring, re-scans, overnight research, email-in, learning | ~15% | One-shot user-triggered research only (Workstream H) |
| Team / collaboration layer | Leader/participant, shared board, canvas | ~0% | Absent (Workstream G) |
| Voice presence | Donna listens *and* speaks/converses | ~40% | Listening pipeline solid; speaking has no caller, conversational agent undeployed (E6, I1) |

## What is DONE and verified working

- **Proactive nudge engine (the product's core):** every final utterance fans out to 5 agents
  in parallel under a Redis distributed lock (`apps/api/services/meeting/agent_dispatcher.py`) —
  scribe (decision detection), context (RAG w/ table/image re-ranking), insight (research match),
  fact-check (Exa verification), knowledge-graph (Neo4j 1–2 hop traversal). No wake word — genuinely
  proactive, matching the PDF's "During meeting: agent → RAG → Nudges" flow.
- **Pre-meeting web research:** 4-stage pipeline (`apps/api/services/research/pipeline.py`) —
  topic extraction → parallel Exa search → tier-1/2/3 credibility classification → executive
  synthesis. Implements AUO's "built from multiple cross-referenced sources."
- **Document intelligence:** upload → layout analysis → GPT table normalization → EasyOCR+Vision
  image extraction → section-aware chunking + spaCy NER → Qdrant + PostgreSQL, with entities and
  relationships mirrored to Neo4j, and a per-meeting subgraph (decisions/actions/topics) synced
  after each meeting.
- **Post-meeting:** structured summary agent, `Decision.source_nudge_id` lineage (AI surfaced X →
  decision Y), Postmark HTML email delivery.
- **Realtime plumbing:** per-participant LiveKit → Deepgram streaming STT with reconnect backoff;
  transcript persistence with row-locked appends; meeting WebSocket with Redis pub/sub cross-replica
  fan-out and in-process fallback (`apps/api/services/meeting/realtime.py`).
- **Production engineering:** DI container, circuit breakers, rate limiting, structured logging with
  request-ID propagation, `/metrics`, Alembic, multi-tenant ownership enforced down into Qdrant
  filters and Neo4j, Arq queue with fallback, CI (ruff + migration drift + ~70 tests).

## Where the implementation is BETTER than the PDF's plan — keep as-is

The PDF's technical plan was OpenAI Realtime + Assistants API + Supabase + n8n + ComfyUI. What was
built is architecturally stronger:

1. **Cost-gated agents** — regex pre-filters (decision keywords, numeric-claim patterns) before any
   LLM call, plus per-claim/per-meeting Redis cooldowns. The PDF's design would pay an LLM on every utterance.
2. **Production backend the plan never mentioned** — resilience, observability, multi-tenancy,
   migrations, CI (list above).
3. **Knowledge-graph nudges** — Neo4j multi-hop traversal mid-conversation; the PDF only had "Supabase Vectors."
4. **Speaker attribution via LiveKit participant identity** (one Deepgram stream per track) — simpler
   and more reliable than the PDF's voice-enrollment flow for the common one-mic-per-person case.
5. **Decision→nudge lineage** (`source_nudge_id`) — cleaner traceability primitive than the plan's
   loose "traceability metadata."
6. **Fail-soft dispatch** — `asyncio.gather(return_exceptions=True)`; one agent failing never kills
   the batch; UI degrades to heartbeat polling if the socket drops.

## Critical findings — where the repo oversells itself

| # | Finding | Task |
|---|---|---|
| 1 | `POST /api/v1/query` 500s on any search hit — enhanced path subscripts a dataclass (`enhanced_livekit_service.py:190-215`) | A1 |
| 2 | "3-level contextual embeddings" is **one** concatenated embedding duplicated across 4 Qdrant collections; global context is a hardcoded "No related documents found" stub; the weighted merge re-ranks identical vectors | C1 |
| 3 | `llamaindex_service.py` never imports LlamaIndex (raw OpenAI + Qdrant); dependency declared, unused | B6 |
| 4 | CrewAI 5-agent system is constructed at startup but **never executes** — zero callers; docs count them in "15 specialized agents" | B1, A8 |
| 5 | ~3,000+ lines dead/unimportable: `rtc.py` (3 broken imports), `enhanced_voice_service.py` (754 lines, unloadable — only place with diarization), duplicate unmounted routers, orphaned frontend components, duplicate worker launchers | B2–B5, B7 |
| 6 | Doc drift: README claims Deepgram nova-3 (actual: `nova-2-meeting`); half of `voice.py` endpoints broken or returning stub/zero data; roadmap + demo script describe unbuilt features as built | A7, A8 |
| 7 | `docker-compose` voice-worker container starts and exits — CMD targets a module with no `__main__`, image lacks `apps/workers/` | A6 |

## Built but disconnected (last-mile gaps — cheapest wins)

| Finding | Task |
|---|---|
| Nudge `source_data` (doc IDs, URLs, KG paths) stored + sent over WS, but dropped by the UI and omitted from `GET /nudges` — users see "via fact_check_agent," never the source | A2 |
| Dismiss button never renders (`onDismiss` not passed); no persistence → also blocks any learning loop | A3 |
| Action items generated by the summary LLM but thrown away (`action_items=[]` hardcoded at 3 call sites) | A4 |
| `Decision.context` exists but no verbatim conversation quote is ever captured (PDF marked this CRITICAL) | A5 |
| Donna never speaks — full TTS path (`/speak` → Redis → worker → Cartesia) has **no caller** | E6 |
| Complete voice-assistant UI (`VoiceInterface.tsx`, visualizer + listening/thinking/speaking states — effectively the PDF's orb) never rendered; its conversational agent worker is correct code with no runnable deployment | I1 |
| Mid-meeting RAG endpoint (`POST /{id}/query`) works and logs to transcript, but has no UI panel | E7 |
| Interim transcripts disabled (`interim_results=False`) → sentence-granular, not word-by-word | E4 |

## Absent entirely (zero code found)

- The PDF's literal "You are Donna" structured prep JSON (`role`, `meeting_type`, `meeting_goal`,
  `agenda_items`, `risks_or_tensions`, `confidence_notes`) — zero hits repo-wide → D2
- Conversational onboarding, prep cards, smart-fill, pre-reads → D3, D5, D7
- Agenda model (agenda is a free-text field), participant roles/expertise → D1, D6
- Meeting-scoped documents (knowledge base is global per owner) → D4
- Leader/participant separation, shared board, canvas, pin, tags → G1–G5, E2, E3
- Continuous monitoring / re-scans, scheduled or overnight research, inbound email
  (`research@donna.app`), calendar integration, "Act Now / Watch" urgency, blind-spot
  suggestions, learning from engagement → Workstream H
- Agenda tracking, meeting-flow awareness, activation nudges (expertise matching) → E1, E8, E9
- True diarization / voice registration; calendar/CRM export → E5, F2
- Visual insight generation (n8n + ComfyUI) → deferred

## AUO pillar mapping

| AUO pillar | Status |
|---|---|
| **Breadth** — "Scan wide. Stay sharp." (monitor landscape, learn priorities, Act Now/Watch) | ~10% — one-shot research only; no monitoring, no urgency ranking, no priority learning (H1–H3, H6) |
| **Context** — "Set the lens." (tell it what you're working on, blind spots, activity at a glance) | ~40% — meeting description drives research topics; no blind-spot suggestions, no signal-activity view (H7) |
| **Reasoning** — "Trace the claim. Know the why." (sourced, cross-checked, challenge in real time) | ~60% — tiering + fact-check + rationale sentences exist server-side; attribution dropped in UI (A2); Ask-Donna panel unbuilt (E7); no re-scan (H2) |
| **Team layer** — "Invite the team. Multiply the signal." | ~0% — Workstream G + H6 |

---

# Part 2 — Task inventory

**Priority scale:** P0 = broken/misleading, fix first · P1 = core product gaps · P2 = differentiators · P3 = vision items
**Effort scale:** S = <½ day · M = 1–2 days · L = 3–5 days · XL = 1–2 weeks

---

## Milestone map

| Milestone | Workstreams | Outcome | Rough effort |
|---|---|---|---|
| **M1 — Harden & finish what exists** | A, B, C | No 500s, no dead code, nudges show sources, action items persist, docs match reality | ~1 week |
| **M2 — The BEFORE phase** | D | Conversational prep, structured prep JSON, agenda model, meeting-scoped docs, prep cards | ~2 weeks |
| **M3 — DURING/AFTER polish** | E, F | Agenda tracking, pin/dismiss feedback, decision quotes, calendar export, meeting memory | ~1.5 weeks |
| **M4 — Continuous intelligence (AUO core)** | H | Scheduled research, source monitoring, urgency ranking, email-in research | ~2 weeks |
| **M5 — Team layer & voice presence** | G, I | Leader/participant roles, shared board, Donna speaks and converses | ~2–3 weeks |

---

## Workstream A — Correctness & last-mile fixes (P0)

The plumbing for these already exists; each is a disconnect at the final step.

### A1. Fix `/api/v1/query` 500 on any search hit — **P0 / S**
`use_enhanced=True` (the default) routes into `DocumentIntelligenceVoiceAgent.process_voice_query`
→ `search_documents_with_context`, which subscripts `SearchResult` dataclasses
(`result["chunk_id"]`, `apps/api/services/voice/enhanced_livekit_service.py:190-215`).
Dataclasses aren't subscriptable → `TypeError` → HTTP 500 whenever the corpus returns results.
- Fix the attribute access (or route the default path to `ModernRAGService`).
- **Accept:** `POST /api/v1/query` returns 200 with sources on a non-empty corpus; regression test added.

### A2. Surface nudge source attribution in the UI — **P0 / S–M**
`Nudge.source_data` (document_id, source_url, KG path) is persisted and included in the
WebSocket `nudge_created` payload (`agent_dispatcher.py:159`) but is dropped by the frontend
and omitted from `GET /nudges` (`apps/api/routers/meetings.py:424-433`).
- Add `source_data` to the nudges response and to `NudgeCardProps` (`apps/web/components/meeting/NudgeCard.tsx:9-17`).
- Render: source document name + page for `context`, URL + tier for `fact_check`/`insight`, entity path for `knowledge_graph`.
- **Accept:** every nudge card shows a tappable source; this is the AUO "Trace the claim" pillar.

### A3. Wire and persist nudge dismiss — **P0 / M**
The dismiss button only renders when `onDismiss` is passed; `MeetingRoom.tsx:266-272` passes
only `onLogDecision`, so it never renders, and there is no persistence.
- Migration: add `dismissed_at` (and `pinned_at`, see E2) to `nudges`.
- Endpoint: `POST /api/v1/meetings/{id}/nudges/{nudge_id}/dismiss`.
- Pass `onDismiss` from `MeetingRoom`; optimistic-remove card.
- **Accept:** dismissed nudges stay dismissed on refetch; dismissal data is available for the H6 learning loop.

### A4. Persist action items from the summary — **P0 / M**
The summary LLM already generates `action_items`, but `summary_pipeline.py:61-66` stores only
summary/insights/decisions, and `routers/meetings.py:685,696,753` hardcode `action_items=[]`.
- In the summary pipeline, upsert `ActionItem` rows from LLM output (assignee, deadline, description, `decision_id` when inferable).
- Return them from `GET /summary` and include in the summary email.
- **Accept:** action items appear in the UI and email without manual POSTs.

### A5. Capture verbatim decision-trigger quotes — **P0 / M**
`Decision.context` and `source_nudge_id` exist, but nothing stores the conversation quote —
flagged CRITICAL in the PDF ("leadership can see the conversation/quotes of the triggers").
- When the scribe emits a `decision_prompt`, attach the triggering utterance(s) (last N verbatim lines) to the nudge `source_data`.
- When the user clicks "Log Decision", copy those quotes into `Decision.context`.
- Render quotes in the decision panel and post-meeting summary.
- **Accept:** every logged decision shows who said what, verbatim, with timestamps.

### A6. Fix the `voice-worker` container — **P0 / S**
`docker-compose.yml` (voice-worker service) runs `python -m apps.api.services.voice.enhanced_livekit_service`,
a module with no `__main__`; the image doesn't even copy `apps/workers/`. The container starts and exits.
- Point CMD at `apps.workers.meeting_voice_worker`; include `apps/workers/` in the image.
- **Accept:** `docker compose up voice-worker` produces a connected LiveKit agent.

### A7. Repair or remove broken `voice.py` endpoints — **P0 / M**
`POST /create-room`, `GET /room/{name}/status`, `DELETE /room/{name}` use `api.RoomService`,
which doesn't exist in the installed SDK; `GET /session/{id}/transcript` and `/metrics` read
in-memory state that lives in a different process (always empty/zero).
- Fix room endpoints to use `LiveKitAPI` (as `/token` does) or delete them.
- Delete the stub transcript/metrics/WS endpoints or back them with Redis-shared state.
- Remove the shadowed duplicate `GET /api/v1/voice/token` in `main.py:1160-1177`.
- **Accept:** every mounted endpoint either works or is gone.

### A8. Fix documentation drift — **P0 / S**
- README claims Deepgram "nova-3"; configured model is `nova-2-meeting`.
- Docs claim "15 specialized agents"; 5 (the CrewAI tree) never execute — recount after B1.
- `MEETING_ASSISTANT_ROADMAP.md` and `DEMO_SCRIPT.md` describe unbuilt features as built; annotate or trim.
- **Accept:** a reviewer reading the docs finds nothing the code contradicts.

---

## Workstream B — Dead code removal (P0–P1, do alongside A)

~3,000+ lines of unreachable or unimportable code inflate the repo and contradict the docs.
Deleting is recommended over wiring — none of it is on the product's critical path.

### B1. Remove the CrewAI agent tree — **P0 / M**
`apps/api/services/agents/` (document/query/context/voice/analytics agents, coordinator, crew_setup)
is constructed at startup (`main.py:153-154`, paying boot cost) but has zero callers.
- Delete the package, remove from the DI container, drop the `crewai` dependency.
- Salvage first: `analytics_agent.py` knowledge-gap detection ideas (→ H7), `voice_agent.py` barge-in pattern (→ I3).
- **Accept:** boot time drops; agent count in docs matches reality (10 live agents).

### B2. Remove the WebRTC/rtc stack — **P0 / S**
`apps/api/routers/rtc.py` (unmounted; imports `feature_flags`, `webrtc_unified_service`, `main_updated` —
none exist) and `apps/api/services/communication/unified_rtc_service.py` (650 lines; `aiortc`/`aioredis` not installed).
- Delete both, plus `main_updated.txt`.

### B3. Remove the unloadable voice service — **P0 / S**
`apps/api/services/voice/enhanced_voice_service.py` (754 lines) cannot import (silero, removed
livekit-agents APIs). It is also the **only** place with diarization config — extract that
config reference into a comment/issue for E5 before deleting.

### B4. Remove duplicate unmounted routers — **P0 / S**
`apps/api/services/document/__init__.py` (~420-line second document router) and
`apps/api/services/voice/__init__.py` (~422-line third voice router) execute on package import
but are never mounted. Replace with plain re-export `__init__` files.

### B5. Frontend orphan sweep — **P1 / S**
Never-rendered components: `MeetingDetail.tsx`, `ChatInterface.tsx`, `VoiceInterface.tsx`,
`DocumentUpload.tsx`, `DocumentList.tsx`.
- Keep `ChatInterface` (reused in D3) and `VoiceInterface` (reused in I1); delete or wire the rest.

### B6. Dependency & model cleanup — **P1 / S**
- `llama-index-core` declared, never imported → remove; rename `services/rag/llamaindex_service.py` → `rag_service.py`.
- `ContextualEmbedding` table: declared, never read/written → drop (migration).
- NetworkX `build_graph`/`query_graph` legacy paths in `knowledge_graph_service.py:456-518` → remove.
- TigerGraph settings in `config.py:83-88` with no implementation → remove.
- Voyage embedding plumbing that is silently ignored (`use_voyage` param unused) → remove or implement (see C1).

### B7. Consolidate workers — **P1 / S**
`apps/worker/` (singular) holds only a Dockerfile; `apps/workers/` (plural) holds the code, including
two near-duplicate conversational launchers (`voice_agent_worker.py` has a broken
`asyncio.run` + `cli.run_app` double-loop). Keep one launcher, one directory, fix the loop bug.

---

## Workstream C — RAG & embedding integrity (P1)

The retrieval layer works but doesn't do what its names claim. Make it honest, then make it better.

### C1. Make 3-level embeddings real — or simplify honestly — **P1 / L**
Today: local/document/global context strings are concatenated into **one** OpenAI embedding,
duplicated across 4 Qdrant collections; global context is a hardcoded
`"No related documents found"` stub (`contextual_processor.py:955-959`); the weighted
multi-collection merge re-ranks identical vectors.
- **Option 1 (recommended, matches the pitch):** generate three genuinely distinct embeddings
  (local window / document metadata / global via a related-docs vector query), store each in its
  collection, keep the weighted merge.
- **Option 2:** collapse to one `_unified` collection, delete the merge machinery, update docs.
- **Accept:** either the levels are real (retrieval-relevance benchmark in `tests/benchmarks/` shows the merge beating single-vector) or the claim is gone.

### C2. Real citations in RAG sources — **P1 / M**
`sources[]` carries only `document_id`, `chunk_id`, 200-char excerpt, score. Filename, page
number, and `section_path` exist in chunk metadata but aren't surfaced
(`llamaindex_service.py:201-219,450-484`).
- Add filename/page/section to source objects; render in chat + nudge UIs ("Q3_Report.pdf, p. 12 §Budget").
- **Accept:** every RAG answer names its documents the way the PDF's nudge mockups do ("Source: Q3 UX Research Report – Page 12").

### C3. Response-level confidence — **P1 / S**
`QueryResponse` has no confidence field; nudges have `relevance_score` but RAG answers don't.
- Add a confidence score (e.g., top-source similarity blended with source agreement) to `QueryResponse` and render it.

### C4. Implement the re-ranker — **P2 / M**
`ModernRAGService._rerank_results` is a no-op sort (`llamaindex_service.py:354-368`).
Add a real re-rank (LLM listwise or cross-encoder) behind a setting, measured by the existing
retrieval benchmark before/after.

---

## Workstream D — The BEFORE phase: meeting prep (P1, the biggest vision gap)

Zero code exists for the PDF's entire prep experience — the origin of the product
("alignment before the meeting"). The PDF hands us the exact prompt contract.

### D1. Agenda data model — **P1 / M** *(prerequisite for D2, D5, E1)*
"Agenda" is currently a free-text description field.
- Migration: `agenda_items (id, meeting_id FK, position, title, duration_minutes, status[pending|active|covered|skipped], notes, created_at)`.
- CRUD nested under meetings; editable list UI in meeting setup (replace the free-text-only box in `CreateMeetingModal.tsx`).
- **Accept:** meetings have ordered, structured agenda items; description remains for context.

### D2. Structured meeting-prep agent (the literal "You are Donna" prompt) — **P1 / M**
Implement the PDF's contract, currently absent repo-wide:
```json
{ "role": "...", "meeting_type": "...", "meeting_goal": "...",
  "agenda_items": ["..."], "risks_or_tensions": ["..."], "confidence_notes": "..." }
```
- `apps/api/services/meeting/prep_agent.py`: user's free-text/voice lines → structured prep JSON
  (gpt-4o-mini, few-shot from the PDF's examples, structured output).
- `POST /api/v1/meetings/prep` (works pre-creation) and "smart-fill" into the create-meeting form:
  prep output pre-populates title, agenda items (→ D1), and a new `meeting_type`/`meeting_goal` on `Meeting`.
- Show `risks_or_tensions` + `confidence_notes` as review cards the user confirms/edits (the PDF's HITL step).
- **Accept:** typing "prepping a session with engineers to ship the component on time, I'm in product design" yields an editable, pre-filled meeting.

### D3. Conversational onboarding flow — **P1 / L**
The PDF's flow: choose Standard Setup / Conversational Setup / Upload Transcript; conversational
mode shows live transcript left, incrementally-built agenda preview right, Confirm & Send.
- New setup page/modal with the three entry modes; conversational mode = chat loop over D2's agent
  with incremental agenda preview (reuse the orphaned `ChatInterface.tsx` as the base).
- Voice input variant can wait for I1; text-first is fine for V1.
- **Accept:** a meeting can be fully configured through conversation, with visual confirmation before creation.

### D4. Meeting-scoped documents — **P1 / M**
"Meeting materials" UI (`KnowledgeBaseStep.tsx`) actually uploads to one global per-owner
knowledge base; `Document` has no meeting link.
- Migration: `meeting_documents (meeting_id, document_id)` join table (documents stay shareable across meetings).
- Upload-from-meeting attaches automatically; `ContextAgent` boosts (not filters) chunks from attached documents.
- **Accept:** the meeting room shows "materials for this meeting"; context nudges prefer them.

### D5. Prep cards — **P1 / M–L**
The research brief exists but there is no digestible pre-meeting prep surface.
- `apps/api/services/meeting/prep_cards.py`: compose cards from research brief + attached docs +
  agenda + (once G1 exists) attendee roles: *Meeting goal · Agenda w/ time · Key research findings
  (tiered sources) · Risks & tensions · Open questions*.
- Store on the meeting; render as a card deck in the BEFORE step; regenerate on demand.
- **Accept:** "Review prep" shows cards a leader could skim in 2 minutes; each research card cites tier + source.

### D6. Participant profiles (role & expertise) — **P2 / M** *(prerequisite for E9, G-series)*
`attendees` is `[{email}]`; `User` has no role/expertise.
- Migration: `meeting_participants (meeting_id, user_id/email, role[leader|participant], expertise_areas JSONB, goals TEXT)`.
- Capture during setup/onboarding; used by role-aware prep (D5), activation nudges (E9), and the team layer (G).

### D7. Pre-read generation & sending — **P2 / M**
"Generate pre-reads" from prep cards → HTML email to attendees via existing Postmark service
(template alongside `meeting_summary.html`); optional PDF attachment later.

---

## Workstream E — DURING-meeting enhancements (P1–P2)

### E1. Agenda-tracking agent — **P1 / M–L** *(needs D1)*
The PDF's "agenda tracking nudges": a 6th dispatcher agent embedding recent utterances against
agenda-item titles → marks items active/covered; time-based nudges ("20 min on item 1 of 4; item 3 uncovered").
Agenda progress bar in `MeetingRoom`. Cheap pre-check: only run every N utterances.

### E2. Pin nudges — **P1 / S** *(pairs with A3)*
`pinned_at` column, pin endpoint, pin button on cards, "Pinned" filter tab in the nudge rail —
the PDF's Pinned Insights view. Pinned nudges get prominence in the summary prompt.

### E3. Nudge tags — **P2 / S**
`tags JSONB` on nudges; generator agents emit 1–3 topical tags; render as chips; filter by tag.
(The PDF's insight cards all carry tags like `#UX #Research #Q3`.)

### E4. Interim (word-by-word) transcripts — **P2 / M**
`interim_results=False` today (`meeting_voice_worker.py:198-207`) → sentence-granular updates.
Enable interims + `utterance_end_ms`; stream partials over the existing WS as a distinct
`utterance_partial` event; render ghost-text that solidifies on final. Keep finals as the only
dispatcher trigger (cost control unchanged).

### E5. Optional diarization for shared-mic rooms — **P2 / M**
Per-track attribution collapses two people on one laptop into one speaker. Add
`diarize=true` Deepgram option per meeting ("conference-room mode") mapping `words[].speaker`
to `Speaker 1/2/...` labels the user can rename. (Config reference preserved from B3.)

### E6. Donna speaks: proactive TTS — **P2 / M**
The full path exists (`POST /{id}/speak` → Redis `meeting:{id}:speak` → worker → Cartesia) but
has **no caller**.
- Dispatcher calls `speak` for nudges with `relevance_score ≥ threshold` (default high, e.g. fact-check contradictions and decision prompts only).
- Leader controls: voice on/off toggle + threshold in `MeetingRoom`; rate-limit (max 1 spoken nudge / 2 min).
- **Accept:** with voice enabled, a contradicted claim produces a short spoken interjection; UI shows "Donna is speaking".

### E7. Mid-meeting "Ask Donna" panel — **P1 / S–M**
`POST /{id}/query` already does conversation-aware RAG and appends Q&A to the transcript
(`routers/meetings.py:922,967-972`) — there's just no UI. Add an input + threaded answers with
C2 citations in the meeting room (the PDF's "Ask AUO" side panel).

### E8. Meeting-flow awareness — **P3 / L**
Talk-time balance per speaker, long-silence detection, phase model (opening/discussion/wrap-up),
"5 minutes left, no decision logged yet" nudge. Data already exists in utterance timestamps + speakers.

### E9. Activation nudges (expertise matching) — **P3 / L** *(needs D6 + G1)*
The PDF's private "YOUR EXPERTISE NEEDED" cards: match current topic against a participant's
expertise, pair with **external** context only (research/fact-check output, never internal data),
deliver privately to that participant (needs G2's per-user delivery). `[I can contribute] [Not relevant]`
feedback feeds H6.

---

## Workstream F — AFTER-meeting completion (P1–P2)

### F1. Decision & action-item lifecycle — **P1 / S–M**
Status toggles (pending → in_progress → done) exist in the models but not the UI. Add controls
in the summary view + a cross-meeting "Open items" view on the dashboard.

### F2. Calendar export — **P2 / M**
No calendar integration of any kind exists. Cheapest credible step: generate `.ics` attachments
(follow-up meeting + action-item deadlines) on the summary email. Full Google/Outlook OAuth sync
is a separate P3 item (H5 covers the read side).

### F3. Assignee follow-up emails — **P2 / S–M**
Per-assignee task list email via existing Postmark service ("You own 3 action items from
Q2 Vendor Selection"), triggered from the summary view.

### F4. Meeting memory read-back — **P1 / M–L**
`sync_meeting_to_neo4j` writes Meeting→Decision/Action/Topic subgraphs, but `kg_query_agent`
matches only `:Entity` nodes — past decisions are never surfaced in later meetings.
- Extend KG queries (and/or ContextAgent) to match prior Meeting/Decision nodes:
  *"In the March meeting, the team decided to delay launch 2 weeks"* — the roadmap's `context` nudge type, still unbuilt.
- Embed past summaries/decisions into Qdrant so semantic recall works too.
- **Accept:** re-discussing a settled topic triggers a nudge citing the earlier meeting and decision.

---

## Workstream G — Team & collaboration layer (P2–P3)

Entirely absent today (no roles, no shared board, no canvas, single-user meetings). This is both
the PDF's "Meeting Leader Driven Model" and AUO's "Invite the team. Multiply the signal."

### G1. Leader/participant roles on meetings — **P2 / M** *(needs D6)*
Leader = creator by default. Role-gate the mutating endpoints (start/end, research, summary,
log-decision) — currently any owner-match can do everything.

### G2. Per-role realtime delivery + shared board — **P2 / L**
`MeetingHub` broadcasts every event to every socket. Add per-user channels: leader gets the full
nudge feed; participants get only leader-shared nudges. `shared_at` column + share button (leader)
+ minimal participant view (shared board: transcript + shared nudges only, distraction-free per the PDF).

### G3. Linkable meeting routes — **P1 / S–M** *(do early — prerequisite for any multi-user use)*
The whole app is two pages with `useState` selection; meetings aren't linkable. Add
`/meetings/[id]` (Next.js dynamic route), move timeline there, keep dashboard as the list.

### G4. Invites & multi-user auth flow — **P3 / L**
Attendee emails → invite links → join meeting as participant (auth exists; invite/join flow doesn't).

### G5. Canvas mode — **P3 / XL, defer**
The PDF's Miro-style infinite canvas of insight cards with spatial clustering. Big build, low
proof-of-value until G2 exists. Interim: the Pinned view (E2) is the poor-man's canvas.

---

## Workstream H — Continuous intelligence: the AUO foundation (P2–P3)

Everything here is absent. This workstream is what turns "meeting research on demand" into
AUO's "Scan wide. Stay sharp."

### H1. Scheduled research runs — **P2 / M**
All research is user-triggered; Arq has no cron. Add `cron_jobs` to
`apps/workers/job_worker.py`: nightly (e.g. 4 AM) re-run of the research pipeline for meetings
scheduled within 48h without a fresh brief. Requires flipping `use_job_queue` on (see J3).
- **Accept:** create a meeting for Thursday, wake up Wednesday to a ready research brief.

### H2. Source monitoring & change detection — **P3 / L**
Store cited source URLs + content hash/summary at research time; scheduled re-crawl (Exa
re-fetch), diff meaningfully changed sources → "what changed since your brief" delta section +
email. This is AUO's "re-scans and flags changes automatically" (theirs: ~20 min; ours: start daily).

### H3. Urgency ranking — "Act Now / Watch" — **P2 / S–M**
Research findings and nudges carry scores but no urgency semantics. Add an `urgency` field
(act_now | watch) set by the synthesis/validation agents (recency × tier × relevance); badge
in `ResearchBriefView` and on nudge cards; sort Act Now first.

### H4. Inbound email research requests — **P3 / L**
The PDF's `research@donna.app` flow. Outbound Postmark exists; inbound doesn't.
- Postmark inbound webhook route → sender verification against registered users → intent
  classification (research question / pre-read / urgent fact-check) → link to calendar meeting
  if referenced → enqueue research job → confirmation email (<1 min) → results email (immediate
  for urgent, else next H1 run).

### H5. Calendar ingestion — **P3 / L**
Google Calendar (OAuth) read: upcoming meetings auto-create Donna meetings with
title/description/attendees, feeding H1 auto-research. (Write-back/export lives in F2.)

### H6. Learning loop from feedback — **P3 / M–L** *(needs A3 + E2)*
No feedback signal is captured today. Once dismiss/pin/log-decision persist:
per-owner, per-nudge-type acceptance stats (Redis/Postgres) → modulate agent thresholds
(mute nudge types a user always dismisses, lower the floor for types they pin). Heuristics
first; no ML needed for V1. This is AUO's "learns from how your team engages."

### H7. Blind-spot suggestions — **P3 / M**
"Suggested topics you didn't know to watch": after research, one extra synthesis call proposing
2–3 adjacent topics (from source content + KG neighborhood) the user didn't ask about, rendered
as addable chips. (Salvage the knowledge-gap ideas from the deleted `analytics_agent.py`, B1.)

---

## Workstream I — Voice presence (P2–P3)

### I1. Deploy the conversational voice agent — **P2 / L**
The modern livekit-agents `AgentSession` (STT+LLM+TTS+VAD) in
`enhanced_livekit_service.py:586-671` is correct but has no runnable deployment, and its UI
(`VoiceInterface.tsx`, with visualizer + listening/thinking/speaking states) is never rendered.
- One launcher (post-B7, with the asyncio double-loop bug fixed), containerized (post-A6).
- Wire `VoiceInterface` into the meeting room ("Talk to Donna") or a docs-chat page.
- Give the agent the RAG tool (the `@function_tool` decorators in `livekit_service.py:129-192`
  are commented out and return placeholders — implement against `ModernRAGService`).
- **Accept:** you can ask Donna a question aloud mid-meeting and get a spoken, document-grounded answer.

### I2. Listening indicator in the meeting UI — **P2 / S**
No orb/waveform/status exists; the only signal audio is flowing is the mic button color.
Add a compact listening/processing indicator fed by WS activity + mic state (full orb aesthetic
can ride on `VoiceInterface`'s BarVisualizer).

### I3. Barge-in handling — **P3 / M** *(needs E6/I1)*
Stop TTS playback when a human speaks (VAD-triggered cancel of the Redis-speak consumer;
pattern exists in the dead `voice_agent.py:358-369` — salvage before B1 deletes it).

---

## Workstream J — Testing, ops & data integrity (parallel)

### J1. E2E happy-path test — **P1 / M**
No test covers upload → research → utterance → nudges → summary. Add an integration test with
mocked OpenAI/Exa/Postmark exercising the real DB + dispatcher + WS hub
(extend `scripts/seed_meeting_demo.py` into an assertion suite).

### J2. Pipeline unit tests — **P1 / M**
Research pipeline (topic→search→validate→synthesize) and summary pipeline are untested; mock the
external calls, verify tier classification, brief persistence, action-item upsert (A4), Neo4j sync.

### J3. Turn on the job queue in production compose — **P2 / S**
`use_job_queue=False` default silently falls back to in-process `BackgroundTasks` (lost on
restart, no retries). Enable Arq in docker-compose, add a failed-job log/DLQ table; keep the
fallback for bare-metal dev.

### J4. WebSocket load sanity — **P2 / S–M**
Benchmark `MeetingHub` fan-out with ~50 sockets + Redis pub/sub across 2 replicas; assert
utterance→nudge broadcast latency budget.

### J5. Retrieval-relevance regression gate — **P2 / S**
`tests/benchmarks/` has a retrieval eval corpus; wire it into CI as a non-blocking report so
C1/C4 changes are measured, not vibes.

---

## Explicitly deferred (revisit after M4)

| Item | Why deferred |
|---|---|
| Canvas mode (G5) | XL build; Pinned view covers the core need until the team layer ships |
| Visual insight generation (n8n + ComfyUI from the PDF) | Different infra stack; unclear value for decision-support core |
| CRM export | No target CRM identified; email + .ics cover follow-ups |
| ~20-minute re-scan cadence (AUO parity) | Daily monitoring (H2) first; tighten cadence when sources/costs justify |
| Voice registration / speaker enrollment | Per-track attribution + optional diarization (E5) covers the real cases |
| ML-based nudge ranking | H6 heuristics first; need feedback volume before models |

---

## Suggested execution order (first two weeks)

1. **Day 1–2:** A1, A6, A8, B2, B3, B4 (fixes + fast deletions)
2. **Day 3–5:** A2, A3, A4, A5 (last-mile nudge/summary wiring) + B1, B6, B7
3. **Day 6–8:** G3 (routes), E7 (Ask Donna panel), C2/C3 (citations + confidence), J1
4. **Day 9–12:** D1 + D2 (agenda model + prep agent) — start of M2
5. **Then:** D3–D5 to complete the BEFORE phase, followed by E1/E2 and F4.

*Last updated: 2026-07-30 · Supersedes the task lists in `MEETING_ASSISTANT_ROADMAP.md` (kept for architecture reference).*


---

# Part 3 — Production readiness (founder view, updated 2026-07-31)

Status after the July 30–31 build sprint: every interactive surface in the PDF now exists
(auth → homepage → 3 setup modes → voice wizard → orb → live meeting with 6 agents →
research reports → summaries with receipts). 136 tests green, Docker stack boots clean.
What follows is the honest founder-level gap analysis between "impressive demo" and
"software teams pay for."

## The three hard truths

1. **Donna is single-player; the thesis is multiplayer.** The founding insight is
   cross-functional *alignment* — but roles, invites, shared board, and private nudge
   delivery are 0% built. Until two people can sit in the same Donna meeting, the product
   demos the vision without testing it.
2. **The retention loop is missing.** What makes Donna sticky is compounding value:
   meeting memory that resurfaces ("in March you decided…"), nudge ranking that learns
   from pin/dismiss, research that refreshes itself. We now *capture* the feedback signals
   but nothing consumes them. One-shot research + live cards are replicable; the loop is
   the moat.
3. **Unit economics are unmeasured.** Every utterance fans out to 6 agents; cost per
   meeting-hour is unknown. Pre-checks bound it, but pricing, margins, and the free-tier
   design all depend on a number we don't have.

## Production readiness phases

### P0 — Trustworthy single-player (~2–3 weeks) → ship to 5–10 design partners
- Flip `REQUIRE_AUTH=true` (+ worker API key); verify every endpoint owner-scoped
- Linkable `/meetings/[id]` routes (G3); structured agenda model (D1); meeting-scoped docs (D4)
- **Cost instrumentation**: per-meeting token/cost metric, per-tenant rollup — the pricing input
- Ops floor: Sentry (or similar), uptime alerts, Postgres backups, staging env, Arq queue on (J3), E2E test in CI (J1)
- Graceful LLM-outage UX (the credits incident showed errors surface raw)
- Instrument the metrics that matter: nudge acceptance rate (pin+act ÷ shown), meetings/user/week, summary opens

### P1 — The compounding loop (~3–4 weeks) → retention drivers
- Meeting memory read-back (F4): past decisions resurface in live meetings
- Learning from feedback (H6): per-user nudge-type thresholds from pin/dismiss data
- Scheduled research (H1) + urgency ranking (H3): briefs that are fresh without being asked
- Calendar read (H5): meetings appear in Donna automatically — kills the cold-start

### P2 — Multiplayer, the actual wedge (~4–6 weeks)
- Invites + leader/participant roles (G1, G4); per-user WebSocket delivery + shared board (G2)
- Activation nudges become *private* (their PDF design); canvas becomes shared
- This phase is where the Harvard-thesis promise gets its first real test

### P3 — Presence & reach (opportunistic)
- Donna speaks (E6 threshold-gated TTS), conversational voice agent deployed (I1), diarization (E5)
- Email-in research (H4), visual insights, blind-spot suggestions (H7)

### Continuous — trust posture
- Data retention/deletion controls, encryption-at-rest story, audit logging
- Self-host packaging as the enterprise wedge (the compose stack is a real asset here)
- SOC2 path once design partners convert

## Risk register

| Risk | Exposure | Mitigation |
|---|---|---|
| LLM cost per live meeting | Pricing/margin unknown | P0 instrumentation before any pricing talk |
| Transcription quality on real rooms | Demo uses typed input | Field-test the voice worker early with partners |
| Single LLM provider (OpenAI) | Full outage = dark product | Provider abstraction + degraded mode |
| Recording consent / privacy objections | Blocks enterprise pilots | Consent UX in the wizard; self-host story |
| Multiplayer complexity underestimated | P2 slips | Scope shared-board V1 to read-only participant view |

---

# Part 4 — Completion ledger (2026-07-31, end of sprint)

Everything below shipped since this plan was written. Remaining open items are
listed at the end.

## Shipped from the task inventory

- **Workstream A (all)** — /query fixed & tenant-scoped, nudge sources rendered,
  dismiss/pin persisted, action items persisted from summary, decision trigger
  quotes captured, voice-worker container fixed, voice router cleaned, docs synced.
- **Workstream B (all)** — CrewAI tree, rtc stack, unloadable voice service,
  duplicate routers, orphan components, dead launcher (`voice_agent_worker.py`),
  llama-index dependency all removed; `llamaindex_service.py` → `rag_service.py`.
- **Workstream C** — C1 true 3-level embeddings; C2 citations (`build_citation`);
  C3 response confidence (top-score × source agreement, rendered in UI);
  C4 hybrid re-ranker (vector + lexical overlap + entity hits).
- **Workstream D** — D1 structured agenda (JSON items with status); D2 prep agent
  (the literal "You are Donna" contract); D3 conversational setup; D4
  meeting-scoped documents; D5 prep surface (research brief + discuss); D6
  attendee expertise; D7 pre-read email.
- **Workstream E** — E1 agenda-tracking agent (LLM-free lexical coverage +
  progress WS + uncovered-items nudges); E2 pin; E3 tags (derived + explicit);
  E4 interim word-by-word transcripts (ghost text); E5 conference diarization;
  E6 Donna speaks (threshold + cooldown + leader toggle); E7 Ask-Donna panel;
  E9 activation nudges (private delivery). E8 meeting-flow awareness remains open.
- **Workstream F** — F1 decision/action lifecycle (PATCH + UI toggles + dashboard
  open-items view); F2 .ics export (summary attachment + download endpoint);
  F3 assignee follow-up emails; F4 memory read-back (memory agent + indexer).
- **Workstream G** — G1 leader/participant roles; G2 per-connection WS privacy +
  shared board; G3 linkable /meetings/[id] routes; G4 invite emails (+ .ics).
  G5 canvas shipped (drag + server-synced positions).
- **Workstream H** — H1 scheduled research cron; H2 stale-brief refresh (24h);
  H3 urgency ranking (act_now/watch badges); H6 learned-mute feedback loop;
  H7 blind-spot suggested topics. H4 (email-in) and H5 (calendar OAuth read)
  remain open — both need external service configuration.
- **Workstream I** — I1 conversational voice agent deployed (assistant-worker);
  I2 listening indicators; I3 barge-in (TTS yields to human speech).
- **Workstream J** — J1 E2E lifecycle test (in CI); J2 pipeline unit tests;
  J3 job queue on in compose (+ doc processing moved off the API); J5 benchmarks
  exist under tests/benchmarks. J4 (WS load benchmark) remains open.

## Architecture upgrades beyond the plan

- Streaming dispatcher (`asyncio.as_completed`, per-agent timeouts, burst
  coalescing, short-lived DB sessions) — see `docs/ARCHITECTURE.md`.
- Model tiering (fast/smart/vision) across all ~18 LLM call sites + per-meeting
  cost metering (`GET /{id}/cost`).
- Redis embedding cache (float32-packed, owner-scoped RAG response cache).
- MCP server (`apps/mcp_server/`) — Donna's knowledge as cited tools.
- Pydantic env aliases modernized; Qdrant `query_points` API; Python 3.13
  toolchain targets.

## Closed in the follow-up sprint (2026-07-31, later)

- **E8 meeting-flow awareness** — FlowAgent (9th live agent, LLM-free):
  Postgres-aggregated talk-time shares streamed as a live meter,
  dominance nudges, "30 minutes and no decision logged" pace nudges.
- **H4 inbound email research** — `POST /api/v1/integrations/email/inbound`
  (Postmark webhook, token-gated): registered sender → research-request
  meeting → pipeline enqueued → confirmation email with the meeting link.
  Ship step: point Postmark's inbound stream at the URL + set
  `POSTMARK_INBOUND_TOKEN`.
- **H5 Google Calendar ingestion** — OAuth consent → refresh token on the
  user → `POST /integrations/google/sync` imports the next 7 days of events
  as meetings (deduped by `external_event_id`); sidebar Connect/Sync button.
  Ship step: create the OAuth client and set `GOOGLE_CLIENT_ID/SECRET`.
- **J4 WS load benchmark** — `tests/benchmarks/test_ws_fanout.py`: 50-socket
  fan-out asserts the <50ms budget + privacy filtering under load.

## Still open

| Item | Blocker |
|---|---|
| Full canvas multiplayer cursors / visual insight generation | deferred by design |
| LLM features live | OpenAI credits exhausted — add billing |

## Eval harness (2026-07-31, follow-up)

Production-style evaluation shipped in `evals/`: versioned golden datasets,
suite registry with requirement-based skipping, committed metric floors
gated in CI + pytest, per-run JSON artifacts (git SHA + timestamp).
First run immediately caught three real gate bugs (currency claims never
matched, "consider it done" missed, "we should…" over-firing) — fixed and
locked in by the baselines.
