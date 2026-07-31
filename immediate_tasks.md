Partially done — the caveats a user would hit
Voice: Donna listens well (per-participant streams) but never speaks — the TTS path exists with no trigger; the conversational voice agent has no deployment; the wizard verifies mics, it doesn't acoustically recognize speakers.
Activation nudges: live, but keyword-matched (v1) and delivered to the shared feed — the PDF's design is private delivery, which needs the team layer.
Structure debt: meeting type and agenda live as description text, not data (blocks agenda tracking); canvas positions are per-browser, not shared; nudge feedback is captured but nothing learns from it yet; embeddings are still one vector marketed as three levels.
Hardening: API-side auth enforcement is still off (UI requires login, raw API doesn't); meetings aren't linkable URLs; job queue defaults to in-process.
Not started — and it's exactly the moat
The unbuilt items are not random leftovers; they're the AUO differentiators: continuous monitoring/re-scans, scheduled research, urgency ranking, calendar ingestion, email-in research, learning from team engagement, and the entire team layer (roles, invites, shared board). Today's one-shot research + live cards are impressive but replicable; the compounding loop and multiplayer are what a competitor can't copy from a demo video.

The three hard truths
Donna is single-player; your thesis is multiplayer. The Harvard-interviews insight — cross-functional misalignment — cannot be tested until two people share a meeting. That's 0% built.
The retention loop is missing. Memory that resurfaces past decisions, ranking that learns from pins/dismissals, briefs that refresh themselves — the signals are now captured, but nothing consumes them. This is what makes week-4 usage higher than week-1.
Unit economics are unmeasured. Six agents per utterance; cost per meeting-hour is unknown. You cannot price, design a free tier, or pitch margins without that number.
The production plan
P0 — Trustworthy single-player (2–3 wks): enforce auth server-side, linkable meeting URLs, structured agenda + meeting-scoped docs, per-meeting cost instrumentation, error tracking + alerts + backups + staging, E2E test in CI, graceful LLM-outage UX. Then put it in front of 5–10 design partners and instrument nudge acceptance rate, meetings/user/week, summary opens.
P1 — The compounding loop (3–4 wks): meeting memory read-back, feedback-driven nudge tuning, scheduled research + Act-Now/Watch urgency, calendar read (kills cold-start).
P2 — Multiplayer (4–6 wks): invites, leader/participant roles, per-user delivery, shared board, private activation nudges. This is where the thesis gets tested — scope participant view read-only to de-risk.
P3 — Presence & reach: Donna speaks, voice conversations, diarization, email-in, visuals.
Continuous: consent UX, retention/deletion controls, the self-host story as your enterprise wedge, SOC2 path when partners convert.