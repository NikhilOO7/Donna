# apps/api/routers/voice.py
"""
Enhanced Voice API endpoints for document intelligence chat
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    WebSocket,
    WebSocketDisconnect,
)
from livekit import api
from livekit.api import LiveKitAPI
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.config import settings
from apps.api.core.database import get_db

# from apps.api.models.voice_session import VoiceSession, VoiceSessionCreate  # TODO: Create this model if needed
from apps.api.services.voice.enhanced_livekit_service import EnhancedVoiceService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/voice", tags=["voice"])


# Request/Response Models
class CreateRoomRequest(BaseModel):
    participant_name: str = Field(default="User", description="Name of the participant")
    room_name: Optional[str] = Field(default=None, description="Custom room name")
    metadata: Dict[str, Any] = Field(
        default_factory=dict, description="Additional metadata"
    )
    enable_transcription: bool = Field(
        default=True, description="Enable real-time transcription"
    )
    audio_settings: Dict[str, bool] = Field(
        default_factory=lambda: {
            "echo_cancellation": True,
            "noise_suppression": True,
            "auto_gain_control": True,
        }
    )


class CreateRoomResponse(BaseModel):
    room_name: str
    token: str
    url: str
    participant_name: str
    session_id: str
    expires_at: datetime


class RoomStatusResponse(BaseModel):
    room_name: str
    is_active: bool
    participant_count: int
    agent_connected: bool
    duration_seconds: float
    metadata: Dict[str, Any]


class TranscriptResponse(BaseModel):
    session_id: str
    transcript: List[Dict[str, Any]]
    summary: Optional[str] = None
    action_items: List[str] = []
    key_decisions: List[str] = []


class VoiceMetricsResponse(BaseModel):
    session_id: str
    metrics: Dict[str, float]
    quality_score: float
    recommendations: List[str]


# Service instance
# Note: With the new AgentSession API, voice agent runs in worker process
# The voice_service is optional here and mainly used for legacy endpoints
try:
    voice_service = EnhancedVoiceService()
except Exception as e:
    logger.warning(f"EnhancedVoiceService initialization failed: {e}")
    logger.warning(
        "Some legacy voice endpoints may not work, but token generation will work fine"
    )
    voice_service = None

# Room management
active_rooms: Dict[str, Dict[str, Any]] = {}


@router.get("/token")
async def get_voice_token(
    room_name: str = "document-chat", participant_name: str = "user"
) -> Dict[str, Any]:
    """Get a LiveKit token for voice chat (simplified endpoint for frontend)"""

    try:
        logger.info(
            f"🎤 Token requested for room: {room_name}, participant: {participant_name}"
        )

        # Create room via LiveKit API
        lk_api = LiveKitAPI(
            settings.livekit_url, settings.livekit_api_key, settings.livekit_api_secret
        )

        # Generate session ID
        session_id = str(uuid.uuid4())

        # Create room if it doesn't exist
        try:
            await lk_api.room.get_room(api.GetRoomRequest(room=room_name))
            logger.info(f"✅ Room {room_name} already exists")
        except Exception:
            # Room doesn't exist, create it
            room_options = api.CreateRoomRequest(
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
            await lk_api.room.create_room(room_options)
            logger.info(f"✅ Created new room: {room_name}")

        # Generate participant token
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

        # Set expiration (2 hours)
        token.with_ttl(timedelta(hours=2))
        jwt_token = token.to_jwt()

        # Store room info
        if room_name not in active_rooms:
            active_rooms[room_name] = {
                "session_id": session_id,
                "created_at": datetime.utcnow(),
                "participants": [participant_name],
                "metadata": {},
                "enable_transcription": True,
            }
            logger.info(f"📝 Registered room {room_name} in active_rooms")

        logger.info(f"✅ Token generated for {participant_name} in room {room_name}")

        return {
            "token": jwt_token,
            "url": settings.livekit_url,
            "room_name": room_name,
            "session_id": session_id,
        }

    except Exception as e:
        logger.error(f"❌ Failed to generate token: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Failed to generate voice token: {str(e)}"
        )


@router.post("/create-room", response_model=CreateRoomResponse)
async def create_voice_room(
    request: CreateRoomRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> CreateRoomResponse:
    """Create a new voice room with enhanced features"""

    try:
        # Generate room name if not provided
        room_name = request.room_name or f"voice-room-{uuid.uuid4().hex[:8]}"
        session_id = str(uuid.uuid4())

        # Create room via LiveKit API
        room_service = api.RoomService(
            settings.livekit_url, settings.livekit_api_key, settings.livekit_api_secret
        )

        # Set room options with enhanced configuration
        room_options = api.CreateRoomRequest(
            name=room_name,
            empty_timeout=300,  # 5 minutes
            max_participants=10,
            metadata=json.dumps(
                {
                    "session_id": session_id,
                    "created_by": request.participant_name,
                    "created_at": datetime.utcnow().isoformat(),
                    "enable_transcription": request.enable_transcription,
                    "audio_settings": request.audio_settings,
                    **request.metadata,
                }
            ),
        )

        # Create the room
        await room_service.create_room(room_options)
        logger.info(f"Created room: {room_name}")

        # Generate participant token with enhanced permissions
        token = api.AccessToken(settings.livekit_api_key, settings.livekit_api_secret)

        token.with_identity(request.participant_name)
        token.with_name(request.participant_name)
        token.with_grants(
            api.VideoGrants(
                room_join=True,
                room=room_name,
                can_subscribe=True,
                can_publish=True,
                can_publish_data=True,
                can_update_metadata=True,
                hidden=False,
                recorder=request.enable_transcription,
            )
        )

        # Add custom attributes
        token.with_attributes(
            {
                "session_id": session_id,
                "role": "participant",
                "audio_settings": json.dumps(request.audio_settings),
            }
        )

        # Set expiration (2 hours)
        expires_at = datetime.utcnow() + timedelta(hours=2)
        token.with_ttl(timedelta(hours=2))

        jwt_token = token.to_jwt()

        # Store room info
        active_rooms[room_name] = {
            "session_id": session_id,
            "created_at": datetime.utcnow(),
            "participants": [request.participant_name],
            "metadata": request.metadata,
            "enable_transcription": request.enable_transcription,
        }

        # Create database session record (TODO: Implement when VoiceSession model is created)
        # session_data = VoiceSessionCreate(
        #     session_id=session_id,
        #     room_name=room_name,
        #     participant_name=request.participant_name,
        #     started_at=datetime.utcnow(),
        #     metadata=request.metadata
        # )

        # Store in database (implement based on your models)
        # db_session = VoiceSession(**session_data.dict())
        # db.add(db_session)
        # await db.commit()

        # Schedule room cleanup
        background_tasks.add_task(
            cleanup_room,
            room_name=room_name,
            delay_seconds=7200,  # 2 hours
        )

        # Trigger agent to join the room
        background_tasks.add_task(
            trigger_agent_join, room_name=room_name, session_id=session_id
        )

        return CreateRoomResponse(
            room_name=room_name,
            token=jwt_token,
            url=settings.livekit_url,
            participant_name=request.participant_name,
            session_id=session_id,
            expires_at=expires_at,
        )

    except Exception as e:
        logger.error(f"Failed to create voice room: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to create voice room: {str(e)}"
        )


@router.get("/room/{room_name}/status", response_model=RoomStatusResponse)
async def get_room_status(room_name: str) -> RoomStatusResponse:
    """Get detailed status of a voice room"""

    try:
        room_service = api.RoomService(
            settings.livekit_url, settings.livekit_api_key, settings.livekit_api_secret
        )

        # Get room info
        try:
            room = await room_service.get_room(api.GetRoomRequest(room=room_name))

            # Get participants
            participants = await room_service.list_participants(
                api.ListParticipantsRequest(room=room_name)
            )

            # Check if agent is connected
            agent_connected = any(
                p.identity.startswith("agent-") for p in participants.participants
            )

            # Calculate duration
            room_info = active_rooms.get(room_name, {})
            created_at = room_info.get("created_at", datetime.utcnow())
            duration = (datetime.utcnow() - created_at).total_seconds()

            return RoomStatusResponse(
                room_name=room_name,
                is_active=True,
                participant_count=len(participants.participants),
                agent_connected=agent_connected,
                duration_seconds=duration,
                metadata=json.loads(room.metadata) if room.metadata else {},
            )

        except Exception:
            # Room doesn't exist
            return RoomStatusResponse(
                room_name=room_name,
                is_active=False,
                participant_count=0,
                agent_connected=False,
                duration_seconds=0,
                metadata={},
            )

    except Exception as e:
        logger.error(f"Failed to get room status: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to get room status: {str(e)}"
        )


@router.get("/session/{session_id}/transcript", response_model=TranscriptResponse)
async def get_session_transcript(
    session_id: str, include_summary: bool = True, db: AsyncSession = Depends(get_db)
) -> TranscriptResponse:
    """Get transcript and analysis for a voice session"""

    try:
        # Get conversation context from voice service
        if not voice_service:
            raise HTTPException(status_code=503, detail="Voice service not available")

        room_name = None
        for room, info in active_rooms.items():
            if info.get("session_id") == session_id:
                room_name = room
                break

        conversation_contexts = voice_service.doc_agent.conversation_contexts
        if not room_name or room_name not in conversation_contexts:
            raise HTTPException(
                status_code=404, detail="Session not found or no transcript available"
            )

        context = conversation_contexts[room_name]

        # Format transcript
        transcript = []
        for msg in context.messages:
            transcript.append(
                {
                    "speaker": msg["role"],
                    "text": msg["content"],
                    "timestamp": msg["timestamp"],
                }
            )

        # Generate summary if requested
        summary = None
        if include_summary and len(transcript) > 5:
            # Use LLM to generate summary
            summary_prompt = "Summarize this conversation in 2-3 sentences:\n\n"
            summary_prompt += "\n".join(
                [f"{t['speaker']}: {t['text']}" for t in transcript[-10:]]
            )

            # This would call your LLM service
            summary = (
                "Discussion covered document search queries and action item tracking."
            )

        return TranscriptResponse(
            session_id=session_id,
            transcript=transcript,
            summary=summary,
            action_items=context.action_items,
            key_decisions=context.decisions,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get transcript: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to get transcript: {str(e)}"
        )


@router.get("/session/{session_id}/metrics", response_model=VoiceMetricsResponse)
async def get_session_metrics(session_id: str) -> VoiceMetricsResponse:
    """Get performance metrics for a voice session"""

    try:
        # Get metrics from voice service
        if not voice_service:
            raise HTTPException(status_code=503, detail="Voice service not available")

        metrics = voice_service.doc_agent.metrics

        # Calculate quality score
        total_latency = metrics.total_latency
        quality_score = 100.0

        if total_latency > 500:
            quality_score -= 30
        elif total_latency > 300:
            quality_score -= 15
        elif total_latency > 150:
            quality_score -= 5

        # Generate recommendations
        recommendations = []
        if metrics.stt_latency > 100:
            recommendations.append(
                "Consider upgrading to Deepgram Nova-3 for better STT performance"
            )
        if metrics.tts_latency > 50:
            recommendations.append(
                "Cartesia Sonic is optimized - ensure good network connectivity"
            )
        if metrics.rag_latency > 200:
            recommendations.append(
                "Document search latency is high - consider indexing optimization"
            )

        return VoiceMetricsResponse(
            session_id=session_id,
            metrics={
                "vad_latency_ms": metrics.vad_latency,
                "stt_latency_ms": metrics.stt_latency,
                "llm_latency_ms": metrics.llm_latency,
                "tts_latency_ms": metrics.tts_latency,
                "rag_latency_ms": metrics.rag_latency,
                "total_latency_ms": metrics.total_latency,
            },
            quality_score=quality_score,
            recommendations=recommendations,
        )

    except Exception as e:
        logger.error(f"Failed to get metrics: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get metrics: {str(e)}")


@router.delete("/room/{room_name}")
async def delete_voice_room(
    room_name: str,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Delete a voice room and cleanup resources"""

    try:
        room_service = api.RoomService(
            settings.livekit_url, settings.livekit_api_key, settings.livekit_api_secret
        )

        # Delete the room
        await room_service.delete_room(api.DeleteRoomRequest(room=room_name))

        # Cleanup local state
        if room_name in active_rooms:
            active_rooms[room_name]

            # Save final transcript to database
            if voice_service:
                conversation_contexts = voice_service.doc_agent.conversation_contexts
                if room_name in conversation_contexts:
                    conversation_contexts[room_name]
                    # Save to database (implement based on your models)

            del active_rooms[room_name]

            # Cleanup conversation context
            if voice_service:
                conversation_contexts = voice_service.doc_agent.conversation_contexts
                if room_name in conversation_contexts:
                    del conversation_contexts[room_name]

        logger.info(f"Deleted room: {room_name}")

        return {
            "status": "success",
            "message": f"Room '{room_name}' deleted successfully",
            "room_name": room_name,
        }

    except Exception as e:
        logger.error(f"Failed to delete room: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete room: {str(e)}")


@router.websocket("/ws/{room_name}")
async def voice_websocket(websocket: WebSocket, room_name: str):
    """WebSocket endpoint for real-time voice events"""

    await websocket.accept()
    logger.info(f"WebSocket connected for room: {room_name}")

    try:
        # Verify room exists
        if room_name not in active_rooms:
            await websocket.send_json({"type": "error", "message": "Room not found"})
            await websocket.close()
            return

        # Send initial status
        await websocket.send_json(
            {
                "type": "connected",
                "room_name": room_name,
                "session_id": active_rooms[room_name]["session_id"],
            }
        )

        # Handle incoming messages
        while True:
            data = await websocket.receive_json()

            if data.get("type") == "command":
                # Handle commands
                command = data.get("command")

                if command == "get_metrics":
                    if voice_service:
                        metrics = voice_service.doc_agent.metrics
                        await websocket.send_json(
                            {
                                "type": "metrics",
                                "metrics": {
                                    "total_latency_ms": metrics.total_latency,
                                    "stt_latency_ms": metrics.stt_latency,
                                    "tts_latency_ms": metrics.tts_latency,
                                },
                            }
                        )
                    else:
                        await websocket.send_json(
                            {"type": "error", "message": "Voice service not available"}
                        )

                elif command == "get_transcript":
                    if voice_service:
                        conversation_contexts = (
                            voice_service.doc_agent.conversation_contexts
                        )
                        if room_name in conversation_contexts:
                            context = conversation_contexts[room_name]
                            await websocket.send_json(
                                {
                                    "type": "transcript",
                                    "messages": context.messages[
                                        -10:
                                    ],  # Last 10 messages
                                }
                            )
                    else:
                        await websocket.send_json(
                            {"type": "error", "message": "Voice service not available"}
                        )

            elif data.get("type") == "ping":
                await websocket.send_json({"type": "pong"})

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for room: {room_name}")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        await websocket.close()


@router.get("/health")
async def voice_health_check() -> Dict[str, Any]:
    """Health check for voice services"""

    health_status = {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "services": {
            "livekit": "unknown",
            "deepgram": "configured" if settings.deepgram_api_key else "not_configured",
            "cartesia": "configured" if settings.cartesia_api_key else "not_configured",
            "openai": "configured" if settings.openai_api_key else "not_configured",
        },
        "active_rooms": len(active_rooms),
        "active_sessions": len(voice_service.doc_agent.conversation_contexts)
        if voice_service
        else 0,
    }

    # Check LiveKit connection
    try:
        room_service = api.RoomService(
            settings.livekit_url, settings.livekit_api_key, settings.livekit_api_secret
        )
        rooms = await room_service.list_rooms(api.ListRoomsRequest())
        health_status["services"]["livekit"] = "healthy"
        health_status["livekit_rooms"] = len(rooms.rooms)
    except Exception as e:
        health_status["services"]["livekit"] = f"unhealthy: {str(e)}"
        health_status["status"] = "degraded"

    return health_status


@router.get("/debug/rooms")
async def debug_list_rooms() -> Dict[str, Any]:
    """Debug endpoint: List all active rooms with details"""

    try:
        room_service = api.RoomService(
            settings.livekit_url, settings.livekit_api_key, settings.livekit_api_secret
        )

        rooms_response = await room_service.list_rooms(api.ListRoomsRequest())

        rooms_info = []
        for room in rooms_response.rooms:
            # Get participants for each room
            participants = await room_service.list_participants(
                api.ListParticipantsRequest(room=room.name)
            )

            room_info = {
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
            rooms_info.append(room_info)

        return {
            "total_rooms": len(rooms_info),
            "rooms": rooms_info,
            "local_active_rooms": list(active_rooms.keys()),
            "timestamp": datetime.utcnow().isoformat(),
        }

    except Exception as e:
        logger.error(f"Failed to list rooms: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to list rooms: {str(e)}")


@router.get("/debug/sessions")
async def debug_list_sessions() -> Dict[str, Any]:
    """Debug endpoint: List all active voice sessions with conversation context"""

    sessions_info = []

    for room_name, room_data in active_rooms.items():
        session_info = {
            "room_name": room_name,
            "session_id": room_data.get("session_id"),
            "created_at": room_data.get("created_at").isoformat()
            if room_data.get("created_at")
            else None,
            "participants": room_data.get("participants", []),
            "enable_transcription": room_data.get("enable_transcription", False),
            "metadata": room_data.get("metadata", {}),
        }

        # Add conversation context if available
        if voice_service:
            conversation_contexts = voice_service.doc_agent.conversation_contexts
            if room_name in conversation_contexts:
                context = conversation_contexts[room_name]
                session_info["conversation"] = {
                    "message_count": len(context.messages),
                    "last_query": context.last_query,
                    "action_items_count": len(context.action_items),
                    "decisions_count": len(context.decisions),
                    "active_context_level": context.active_context_level,
                    "recent_messages": context.messages[-5:]
                    if context.messages
                    else [],
                }

        sessions_info.append(session_info)

    return {
        "total_sessions": len(sessions_info),
        "sessions": sessions_info,
        "timestamp": datetime.utcnow().isoformat(),
    }


@router.post("/debug/test-audio-flow")
async def debug_test_audio_flow(room_name: str) -> Dict[str, Any]:
    """Debug endpoint: Test audio flow in a specific room"""

    try:
        room_service = api.RoomService(
            settings.livekit_url, settings.livekit_api_key, settings.livekit_api_secret
        )

        # Get room info
        room = await room_service.get_room(api.GetRoomRequest(room=room_name))

        # Get participants
        participants = await room_service.list_participants(
            api.ListParticipantsRequest(room=room_name)
        )

        # Analyze audio flow
        audio_flow = {
            "room": {
                "name": room.name,
                "active": True,
                "num_participants": len(participants.participants),
            },
            "participants": [],
            "agent_status": "not_found",
            "audio_tracks": {"published": 0, "subscribed": 0},
        }

        for p in participants.participants:
            participant_info = {
                "identity": p.identity,
                "name": p.name,
                "is_agent": p.identity.startswith("agent-"),
                "tracks": [],
            }

            for track_pub in p.tracks:
                track_info = {
                    "sid": track_pub.sid,
                    "type": track_pub.type,
                    "source": track_pub.source,
                    "muted": track_pub.muted,
                    "width": track_pub.width,
                    "height": track_pub.height,
                }
                participant_info["tracks"].append(track_info)

                if track_pub.type == 1:  # Audio track
                    audio_flow["audio_tracks"]["published"] += 1

            audio_flow["participants"].append(participant_info)

            if participant_info["is_agent"]:
                audio_flow["agent_status"] = "connected"

        # Check if audio flow is healthy
        has_user_audio = any(
            p["identity"] != "agent" and len(p["tracks"]) > 0
            for p in audio_flow["participants"]
        )

        has_agent = audio_flow["agent_status"] == "connected"

        audio_flow["health"] = {
            "has_user_audio": has_user_audio,
            "has_agent": has_agent,
            "is_healthy": has_user_audio and has_agent,
        }

        return audio_flow

    except Exception as e:
        logger.error(f"Failed to test audio flow: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to test audio flow: {str(e)}"
        )


# Background tasks
async def cleanup_room(room_name: str, delay_seconds: int):
    """Cleanup room after delay"""
    await asyncio.sleep(delay_seconds)

    if room_name in active_rooms:
        try:
            room_service = api.RoomService(
                settings.livekit_url,
                settings.livekit_api_key,
                settings.livekit_api_secret,
            )

            # Check if room is still empty
            participants = await room_service.list_participants(
                api.ListParticipantsRequest(room=room_name)
            )

            if len(participants.participants) == 0:
                await room_service.delete_room(api.DeleteRoomRequest(room=room_name))
                del active_rooms[room_name]
                logger.info(f"Cleaned up empty room: {room_name}")
        except Exception as e:
            logger.error(f"Failed to cleanup room {room_name}: {e}")


async def trigger_agent_join(room_name: str, session_id: str):
    """Trigger the voice agent to join the room"""

    # Wait a moment for the room to be fully created
    await asyncio.sleep(1)

    try:
        # This would trigger your voice agent worker to join
        # For now, we'll just log it
        logger.info(f"Triggering agent to join room: {room_name}")

        # In production, you might send a message to a queue
        # or make an API call to your agent service

    except Exception as e:
        logger.error(f"Failed to trigger agent join: {e}")
