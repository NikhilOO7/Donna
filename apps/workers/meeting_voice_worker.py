"""
Meeting Voice Worker.

A LiveKit Agent that auto-joins meeting rooms (named ``meeting-<uuid>``),
subscribes to every participant's audio track, streams audio to Deepgram
for transcription, and POSTs each final utterance to the backend's
``/api/v1/meetings/{id}/utterances`` endpoint.

The backend then runs the meeting agent dispatcher (scribe, context,
insight) and produces nudge cards — exactly the same flow as manual
utterance input.

Run with::

    uv run python -m apps.workers.meeting_voice_worker dev
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path
from typing import Optional

# Project root + .env loading (mirrors enhanced_voice_agent_worker.py)
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv  # noqa: E402

env_path = project_root / ".env"
if env_path.exists():
    load_dotenv(env_path)

import httpx  # noqa: E402
from deepgram import (  # noqa: E402
    AsyncListenWebSocketClient,
    DeepgramClient,
    LiveOptions,
    LiveTranscriptionEvents,
)
from livekit import rtc  # noqa: E402
from livekit.agents import AutoSubscribe, JobContext, WorkerOptions, cli  # noqa: E402

from apps.api.core.config import settings  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("meeting-voice-worker")


BACKEND_URL = os.environ.get("BACKEND_URL", f"http://localhost:{settings.api_port}")


def _meeting_id_from_room(room_name: str) -> Optional[str]:
    """Extract meeting UUID from room name pattern ``meeting-<uuid>``."""
    if not room_name or not room_name.startswith("meeting-"):
        return None
    return room_name[len("meeting-") :]


async def _post_utterance(meeting_id: str, speaker: str, text: str) -> None:
    """POST the final transcript to the backend."""
    url = f"{BACKEND_URL}/api/v1/meetings/{meeting_id}/utterances"
    headers = {}
    if settings.api_key:
        headers["X-API-Key"] = settings.api_key

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                url,
                json={"speaker": speaker, "text": text},
                headers=headers,
            )
            if response.status_code >= 400:
                logger.warning(
                    f"Backend rejected utterance: {response.status_code} {response.text[:200]}"
                )
            else:
                logger.info(
                    f"[{meeting_id[:8]}] utterance posted (speaker={speaker}, "
                    f"len={len(text)})"
                )
    except Exception as e:
        logger.warning(f"Failed to POST utterance: {e}")


async def _transcribe_track(
    meeting_id: str,
    track: rtc.Track,
    speaker: str,
) -> None:
    """Open a Deepgram streaming connection for one participant's audio track."""
    if not settings.deepgram_api_key:
        logger.error("DEEPGRAM_API_KEY not set — skipping transcription")
        return

    deepgram = DeepgramClient(settings.deepgram_api_key)
    connection: AsyncListenWebSocketClient = deepgram.listen.asyncwebsocket.v("1")

    async def _on_transcript(_self, result, **_kwargs):
        try:
            if not result or not getattr(result, "is_final", False):
                return
            channel = getattr(result, "channel", None)
            if not channel or not channel.alternatives:
                return
            text = (channel.alternatives[0].transcript or "").strip()
            if not text:
                return
            await _post_utterance(meeting_id, speaker, text)
        except Exception as e:
            logger.warning(f"transcript handler error: {e}")

    async def _on_error(_self, error, **_kwargs):
        logger.warning(f"Deepgram error: {error}")

    connection.on(LiveTranscriptionEvents.Transcript, _on_transcript)
    connection.on(LiveTranscriptionEvents.Error, _on_error)

    options = LiveOptions(
        model=settings.deepgram_model or "nova-2-meeting",
        language=settings.deepgram_language or "en-US",
        smart_format=True,
        interim_results=False,
        punctuate=True,
        sample_rate=48000,
        channels=1,
        encoding="linear16",
    )

    try:
        await connection.start(options)
    except Exception as e:
        logger.error(f"Failed to start Deepgram connection: {e}")
        return

    logger.info(f"[{meeting_id[:8]}] transcribing speaker={speaker}")

    audio_stream = rtc.AudioStream(track)
    try:
        async for event in audio_stream:
            frame = event.frame  # rtc.AudioFrame
            # LiveKit provides PCM frames; Deepgram with linear16 + sample_rate expects raw bytes
            await connection.send(frame.data.tobytes())
    except Exception as e:
        logger.info(f"audio stream ended for {speaker}: {e}")
    finally:
        try:
            await connection.finish()
        except Exception:
            pass
        logger.info(f"[{meeting_id[:8]}] finished transcribing speaker={speaker}")


async def entrypoint(ctx: JobContext):
    """LiveKit Agent entrypoint — runs once per room job."""
    room_name = ctx.room.name
    meeting_id = _meeting_id_from_room(room_name)
    if not meeting_id:
        logger.info(f"Ignoring non-meeting room: {room_name}")
        return

    logger.info(f"=== Meeting voice worker joining room: {room_name} ===")

    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)

    tasks: list[asyncio.Task] = []

    @ctx.room.on("track_subscribed")
    def on_track_subscribed(
        track: rtc.Track,
        publication: rtc.TrackPublication,
        participant: rtc.RemoteParticipant,
    ):
        if track.kind != rtc.TrackKind.KIND_AUDIO:
            return
        speaker = participant.identity or participant.name or "Speaker"
        logger.info(f"Subscribing to audio track from {speaker}")
        task = asyncio.create_task(_transcribe_track(meeting_id, track, speaker))
        tasks.append(task)

    # Also handle anyone already in the room
    for participant in ctx.room.remote_participants.values():
        for publication in participant.track_publications.values():
            track = publication.track
            if track and track.kind == rtc.TrackKind.KIND_AUDIO:
                on_track_subscribed(track, publication, participant)

    # Keep the job alive until disconnect
    await ctx.wait_for_participant()
    logger.info(f"Meeting voice worker exiting room: {room_name}")


if __name__ == "__main__":
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            api_key=settings.livekit_api_key,
            api_secret=settings.livekit_api_secret,
            ws_url=settings.livekit_url,
        )
    )
