# ADR-002: Voice Pipeline Technology Choices

## Status
Accepted

## Context
The system requires real-time voice interaction with document intelligence. Users speak queries, the system processes them against the document corpus, and responds with synthesized speech. The pipeline must achieve <200ms perceived latency for natural conversation flow.

Key constraints:
- Must support WebRTC for browser-based voice
- Must handle concurrent voice sessions
- STT accuracy must be >95% for professional/technical vocabulary
- TTS must sound natural, not robotic

## Decision
We selected a three-component voice stack:

1. **Deepgram Nova-3** (STT) - Chosen over OpenAI Whisper for its streaming capability and <150ms latency. Whisper requires full utterance completion before transcription; Deepgram supports real-time interim results enabling faster response initiation.

2. **Cartesia Sonic-2** (TTS) - Chosen over OpenAI TTS and ElevenLabs for its streaming SSE support and low first-byte latency (~100ms). OpenAI TTS does not support streaming. ElevenLabs has higher latency and cost.

3. **LiveKit** (WebRTC infrastructure) - Chosen over raw WebRTC or Twilio for its open-source agent framework, built-in plugin ecosystem (deepgram, cartesia, silero plugins), and room-based session management. LiveKit agents run as separate worker processes, enabling horizontal scaling.

4. **Silero VAD** (Voice Activity Detection) - Lightweight ONNX model running locally. Detects speech start/end to avoid sending silence to STT, reducing API costs and latency.

## Consequences
- **Positive**: Sub-200ms pipeline achievable (Deepgram ~100ms + LLM streaming + Cartesia ~80ms).
- **Positive**: LiveKit plugin ecosystem means STT/TTS/VAD are plug-and-play configurable.
- **Positive**: Voice workers scale independently from the API server.
- **Negative**: Three external API dependencies (Deepgram, Cartesia, OpenAI for LLM) - each is a failure point, mitigated by circuit breakers (see ADR-004).
- **Negative**: LiveKit server is an additional infrastructure component to manage.
