"""
Meeting Voice Worker.

A LiveKit Agent that auto-joins meeting rooms (named ``meeting-<uuid>``),
subscribes to every participant's audio track, streams audio to Deepgram
for transcription, and POSTs each final utterance to the backend's
``/api/v1/meetings/{id}/utterances`` endpoint.

Two additional capabilities (relative to the original demo-grade
worker):

* **Resilience** — POSTs to the backend retry with exponential backoff
  on transient failures; the Deepgram websocket is wrapped in a
  reconnect loop that survives transient drops while the meeting is
  still live.
* **TTS playback** — subscribes to the per-meeting Redis channel
  ``meeting:<id>:speak``. Any text published to that channel is
  synthesized via Cartesia and pushed back into the LiveKit room as
  a published audio track, so an AI voice can speak inside the
  meeting (e.g. to summarize a logged decision aloud).

Run with::

    uv run python -m apps.workers.meeting_voice_worker dev
"""

from __future__ import annotations

import asyncio
import json
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
import numpy as np  # noqa: E402
import redis.asyncio as aioredis  # noqa: E402
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

# Backoff parameters (seconds). Capped so the worker doesn't sit forever
# if the backend is permanently down.
_POST_INITIAL_BACKOFF = 0.5
_POST_MAX_BACKOFF = 8.0
_POST_MAX_ATTEMPTS = 5

_DEEPGRAM_RECONNECT_BACKOFF = 1.0
_DEEPGRAM_MAX_BACKOFF = 15.0

# Cartesia output format used for the TTS → LiveKit pipeline.
_TTS_SAMPLE_RATE = 24000
_TTS_CHANNELS = 1


def _meeting_id_from_room(room_name: str) -> Optional[str]:
    """Extract meeting UUID from room name pattern ``meeting-<uuid>``."""
    if not room_name or not room_name.startswith("meeting-"):
        return None
    return room_name[len("meeting-") :]


# ---------------------------------------------------------------------------
# Resilient POST helper
# ---------------------------------------------------------------------------


async def _post_utterance(meeting_id: str, speaker: str, text: str) -> None:
    """POST the final transcript to the backend with retry + backoff.

    Retries on connection errors, timeouts, and 5xx responses. 4xx
    responses are considered final (bad request, auth) and not retried.
    """
    url = f"{BACKEND_URL}/api/v1/meetings/{meeting_id}/utterances"
    headers = {}
    if settings.api_key:
        headers["X-API-Key"] = settings.api_key

    backoff = _POST_INITIAL_BACKOFF
    for attempt in range(1, _POST_MAX_ATTEMPTS + 1):
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    url,
                    json={"speaker": speaker, "text": text},
                    headers=headers,
                )
            if 200 <= response.status_code < 300:
                logger.info(
                    f"[{meeting_id[:8]}] utterance posted (speaker={speaker}, "
                    f"len={len(text)}, attempt={attempt})"
                )
                return
            if 400 <= response.status_code < 500:
                # Don't retry client errors — fixing them needs config change
                logger.warning(
                    f"Backend rejected utterance (no retry): "
                    f"{response.status_code} {response.text[:200]}"
                )
                return
            logger.warning(
                f"Backend 5xx on utterance POST (attempt {attempt}): "
                f"{response.status_code}"
            )
        except (httpx.RequestError, asyncio.TimeoutError) as e:
            logger.warning(f"Utterance POST transport error (attempt {attempt}): {e}")
        except Exception as e:
            logger.warning(f"Utterance POST unexpected error: {e}")
            return

        if attempt < _POST_MAX_ATTEMPTS:
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, _POST_MAX_BACKOFF)

    logger.error(
        f"Giving up on utterance after {_POST_MAX_ATTEMPTS} attempts "
        f"(speaker={speaker})"
    )


# ---------------------------------------------------------------------------
# Deepgram transcription loop with reconnect
# ---------------------------------------------------------------------------


async def _transcribe_track(
    meeting_id: str,
    track: rtc.Track,
    speaker: str,
) -> None:
    """Stream one participant's audio to Deepgram, reconnecting on drops.

    Holds an audio buffer between reconnects so a brief Deepgram outage
    doesn't lose data once the websocket is back up.
    """
    if not settings.deepgram_api_key:
        logger.error("DEEPGRAM_API_KEY not set — skipping transcription")
        return

    deepgram = DeepgramClient(settings.deepgram_api_key)
    audio_stream = rtc.AudioStream(track)
    audio_iter = aiter(audio_stream)

    reconnect_backoff = _DEEPGRAM_RECONNECT_BACKOFF
    pending_frame: Optional[bytes] = None

    while True:
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
            logger.warning(
                f"Deepgram connect failed (backing off {reconnect_backoff}s): {e}"
            )
            await asyncio.sleep(reconnect_backoff)
            reconnect_backoff = min(reconnect_backoff * 2, _DEEPGRAM_MAX_BACKOFF)
            continue

        logger.info(
            f"[{meeting_id[:8]}] transcribing speaker={speaker} (reconnect={reconnect_backoff != _DEEPGRAM_RECONNECT_BACKOFF})"
        )
        reconnect_backoff = _DEEPGRAM_RECONNECT_BACKOFF  # reset on success

        stream_ended = False
        try:
            # If we have a frame left over from a prior disconnect, send it first
            if pending_frame is not None:
                try:
                    await connection.send(pending_frame)
                except Exception:
                    pass
                pending_frame = None

            async for event in audio_iter:
                frame = event.frame
                raw = frame.data.tobytes()
                try:
                    await connection.send(raw)
                except Exception as send_err:
                    pending_frame = raw
                    logger.info(
                        f"Deepgram send failed mid-stream, reconnecting: {send_err}"
                    )
                    break
        except StopAsyncIteration:
            stream_ended = True
        except Exception as e:
            logger.info(f"audio stream loop ended for {speaker}: {e}")
            stream_ended = True
        finally:
            try:
                await connection.finish()
            except Exception:
                pass

        if stream_ended:
            logger.info(f"[{meeting_id[:8]}] audio stream ended for speaker={speaker}")
            return
        # Otherwise we broke out of the send loop — reconnect


# ---------------------------------------------------------------------------
# TTS playback (Cartesia → LiveKit room)
# ---------------------------------------------------------------------------


async def _synthesize_and_publish(
    text: str,
    audio_source: rtc.AudioSource,
) -> None:
    """Call Cartesia, slice the PCM stream into AudioFrames, push to room."""
    if not settings.cartesia_api_key:
        logger.warning("[TTS] CARTESIA_API_KEY not set — skipping playback")
        return

    try:
        from cartesia import AsyncCartesia
    except Exception as e:
        logger.warning(f"[TTS] cartesia SDK not importable: {e}")
        return

    client = AsyncCartesia(api_key=settings.cartesia_api_key)
    try:
        audio_bytes = await client.tts.bytes(
            model_id="sonic-2",
            transcript=text,
            voice_id=getattr(settings, "cartesia_voice_id", None)
            or "a0e99841-438c-4a64-b679-ae501e7d6091",  # Cartesia "Barbershop Man"
            output_format={
                "container": "raw",
                "encoding": "pcm_s16le",
                "sample_rate": _TTS_SAMPLE_RATE,
            },
            language="en",
        )
    except Exception as e:
        logger.warning(f"[TTS] Cartesia call failed: {e}")
        return
    finally:
        try:
            await client.close()
        except Exception:
            pass

    if not audio_bytes:
        return

    # Push as 20ms frames (480 samples at 24kHz mono) for steady playback
    samples_per_frame = _TTS_SAMPLE_RATE // 50  # 20ms
    pcm = np.frombuffer(audio_bytes, dtype=np.int16)
    total = len(pcm)
    logger.info(f"[TTS] publishing {total} samples ({total / _TTS_SAMPLE_RATE:.2f}s)")

    for offset in range(0, total, samples_per_frame):
        chunk = pcm[offset : offset + samples_per_frame]
        if len(chunk) == 0:
            break
        frame = rtc.AudioFrame.create(
            sample_rate=_TTS_SAMPLE_RATE,
            num_channels=_TTS_CHANNELS,
            samples_per_channel=len(chunk),
        )
        np.copyto(np.frombuffer(frame.data, dtype=np.int16), chunk)
        try:
            await audio_source.capture_frame(frame)
        except Exception as e:
            logger.warning(f"[TTS] capture_frame failed mid-stream: {e}")
            return


async def _tts_subscriber(
    meeting_id: str,
    audio_source: rtc.AudioSource,
    stop_event: asyncio.Event,
) -> None:
    """Listen on Redis ``meeting:<id>:speak`` and synthesize each payload."""
    redis_url = settings.redis_url
    try:
        r = aioredis.from_url(redis_url, decode_responses=True)
        await r.ping()
    except Exception as e:
        logger.warning(f"[TTS] Redis unavailable, TTS disabled: {e}")
        return

    channel_name = f"meeting:{meeting_id}:speak"
    pubsub = r.pubsub()
    try:
        await pubsub.subscribe(channel_name)
        logger.info(f"[TTS] subscribed to {channel_name}")
    except Exception as e:
        logger.warning(f"[TTS] subscribe failed: {e}")
        await r.close()
        return

    try:
        while not stop_event.is_set():
            try:
                msg = await asyncio.wait_for(
                    pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0),
                    timeout=2.0,
                )
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.info(f"[TTS] pubsub poll error (reconnecting): {e}")
                await asyncio.sleep(1.0)
                continue
            if not msg:
                continue
            try:
                payload = (
                    json.loads(msg["data"])
                    if isinstance(msg["data"], str)
                    else msg["data"]
                )
                text = (
                    (payload or {}).get("text", "").strip()
                    if isinstance(payload, dict)
                    else str(payload)
                )
                if not text:
                    continue
                await _synthesize_and_publish(text, audio_source)
            except Exception as e:
                logger.warning(f"[TTS] failed to handle speak message: {e}")
    finally:
        try:
            await pubsub.unsubscribe(channel_name)
            await pubsub.close()
            await r.close()
        except Exception:
            pass
        logger.info(f"[TTS] unsubscribed from {channel_name}")


# ---------------------------------------------------------------------------
# LiveKit Agent entrypoint
# ---------------------------------------------------------------------------


async def entrypoint(ctx: JobContext):
    """LiveKit Agent entrypoint — runs once per room job."""
    room_name = ctx.room.name
    meeting_id = _meeting_id_from_room(room_name)
    if not meeting_id:
        logger.info(f"Ignoring non-meeting room: {room_name}")
        return

    logger.info(f"=== Meeting voice worker joining room: {room_name} ===")

    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)

    # --- TTS output track (so the bot can speak back) ---
    audio_source = rtc.AudioSource(
        sample_rate=_TTS_SAMPLE_RATE, num_channels=_TTS_CHANNELS
    )
    tts_track = rtc.LocalAudioTrack.create_audio_track(
        "meeting-assistant-voice", audio_source
    )
    try:
        await ctx.room.local_participant.publish_track(tts_track)
        logger.info(f"[TTS] published output track in {room_name}")
    except Exception as e:
        logger.warning(f"[TTS] publish_track failed (TTS disabled): {e}")

    tts_stop = asyncio.Event()
    tts_task = asyncio.create_task(_tts_subscriber(meeting_id, audio_source, tts_stop))

    stt_tasks: list[asyncio.Task] = []

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
        stt_tasks.append(task)

    # Catch participants already in the room when we joined
    for participant in ctx.room.remote_participants.values():
        for publication in participant.track_publications.values():
            track = publication.track
            if track and track.kind == rtc.TrackKind.KIND_AUDIO:
                on_track_subscribed(track, publication, participant)

    try:
        await ctx.wait_for_participant()
    finally:
        tts_stop.set()
        try:
            await asyncio.wait_for(tts_task, timeout=2.0)
        except Exception:
            pass
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
