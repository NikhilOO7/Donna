# apps/api/routers/voice.py
"""Voice API endpoints — LiveKit token issuance + service health.

The voice pipeline itself runs in a separate worker process
(``apps/workers/meeting_voice_worker.py``); these endpoints only hand out
room tokens and report configuration/connectivity status.
"""

import json
import logging
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict

from fastapi import APIRouter, HTTPException
from livekit import api
from livekit.api import LiveKitAPI

from apps.api.core.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/voice", tags=["voice"])


@router.get("/token")
async def get_voice_token(
    room_name: str = "document-chat", participant_name: str = "user"
) -> Dict[str, Any]:
    """Get a LiveKit token for voice chat (creates the room if needed)."""
    try:
        logger.info(
            f"Token requested for room: {room_name}, participant: {participant_name}"
        )

        session_id = str(uuid.uuid4())

        lk_api = LiveKitAPI(
            settings.livekit_url, settings.livekit_api_key, settings.livekit_api_secret
        )
        try:
            # Create room if it doesn't exist
            try:
                await lk_api.room.get_room(api.GetRoomRequest(room=room_name))
            except Exception:
                await lk_api.room.create_room(
                    api.CreateRoomRequest(
                        name=room_name,
                        empty_timeout=300,
                        max_participants=10,
                        metadata=json.dumps(
                            {
                                "session_id": session_id,
                                "created_by": participant_name,
                                "created_at": datetime.utcnow().isoformat(),
                            }
                        ),
                    )
                )
                logger.info(f"Created new room: {room_name}")
        finally:
            await lk_api.aclose()

        token = api.AccessToken(settings.livekit_api_key, settings.livekit_api_secret)
        token.with_identity(participant_name)
        token.with_name(participant_name)
        token.with_grants(
            api.VideoGrants(
                room_join=True,
                room=room_name,
                can_subscribe=True,
                can_publish=True,
                can_publish_data=True,
            )
        )
        token.with_attributes({"session_id": session_id})
        token.with_ttl(timedelta(hours=2))

        return {
            "token": token.to_jwt(),
            "url": settings.livekit_client_url,
            "room_name": room_name,
            "session_id": session_id,
        }

    except Exception as e:
        logger.error(f"Failed to generate token: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Failed to generate voice token: {str(e)}"
        )


@router.get("/health")
async def voice_health_check() -> Dict[str, Any]:
    """Health check for voice services."""
    health_status: Dict[str, Any] = {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "services": {
            "livekit": "unknown",
            "deepgram": "configured" if settings.deepgram_api_key else "not_configured",
            "cartesia": "configured" if settings.cartesia_api_key else "not_configured",
            "openai": "configured" if settings.openai_api_key else "not_configured",
        },
    }

    try:
        lk_api = LiveKitAPI(
            settings.livekit_url, settings.livekit_api_key, settings.livekit_api_secret
        )
        try:
            rooms = await lk_api.room.list_rooms(api.ListRoomsRequest())
            health_status["services"]["livekit"] = "healthy"
            health_status["livekit_rooms"] = len(rooms.rooms)
        finally:
            await lk_api.aclose()
    except Exception as e:
        health_status["services"]["livekit"] = f"unhealthy: {str(e)}"
        health_status["status"] = "degraded"

    # Voice-worker liveness. The worker is a separate process with no HTTP
    # surface: if it dies, meetings keep looking healthy while transcription
    # silently stops. It stamps a Redis heartbeat every 10s with a 30s TTL,
    # so an absent key means it has missed ~3 beats or is not running.
    worker: Dict[str, Any] = {"status": "unknown"}
    try:
        import json as _json
        import time as _time

        from apps.api.core.connections import get_redis_client

        redis = await get_redis_client()
        raw = await redis.get("worker:voice:heartbeat")
        if not raw:
            worker = {
                "status": "down",
                "detail": (
                    "no heartbeat in the last 30s — the voice worker is not "
                    "running; meetings will receive no transcription"
                ),
            }
            health_status["status"] = "degraded"
        else:
            beat = _json.loads(raw)
            age = round(_time.time() - float(beat.get("ts", 0)), 1)
            worker = {
                "status": "healthy",
                "heartbeat_age_seconds": age,
                "active_rooms": beat.get("active_rooms", 0),
                "rooms": beat.get("rooms", []),
            }
    except Exception as e:
        worker = {"status": "unknown", "detail": f"heartbeat unreadable: {e}"}

    health_status["voice_worker"] = worker
    return health_status


@router.get("/debug/rooms")
async def debug_list_rooms() -> Dict[str, Any]:
    """Debug endpoint: list active LiveKit rooms with participants."""
    try:
        lk_api = LiveKitAPI(
            settings.livekit_url, settings.livekit_api_key, settings.livekit_api_secret
        )
        try:
            rooms_response = await lk_api.room.list_rooms(api.ListRoomsRequest())

            rooms_info = []
            for room in rooms_response.rooms:
                participants = await lk_api.room.list_participants(
                    api.ListParticipantsRequest(room=room.name)
                )
                rooms_info.append(
                    {
                        "name": room.name,
                        "sid": room.sid,
                        "num_participants": room.num_participants,
                        "creation_time": room.creation_time,
                        "metadata": json.loads(room.metadata) if room.metadata else {},
                        "participants": [
                            {
                                "identity": p.identity,
                                "name": p.name,
                                "state": p.state,
                                "is_publisher": p.permission.can_publish,
                                "tracks": len(p.tracks),
                            }
                            for p in participants.participants
                        ],
                    }
                )
        finally:
            await lk_api.aclose()

        return {
            "total_rooms": len(rooms_info),
            "rooms": rooms_info,
            "timestamp": datetime.utcnow().isoformat(),
        }

    except Exception as e:
        logger.error(f"Failed to list rooms: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to list rooms: {str(e)}")
