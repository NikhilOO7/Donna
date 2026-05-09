# apps/api/services/voice/__init__.py
# Enhanced version of your existing voice routes
from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from fastapi.responses import JSONResponse
from livekit import api
from typing import Dict, Any, Optional, List
import logging
import json
import uuid
from datetime import datetime, timedelta

from ...core.config import settings

logger = logging.getLogger(__name__)

router = APIRouter()

# Track active rooms and sessions
active_rooms: Dict[str, Dict[str, Any]] = {}

@router.post("/create-room")
async def create_voice_room(
    room_name: Optional[str] = None,
    participant_name: str = "User",
    enable_transcription: bool = True,
    audio_settings: Optional[Dict[str, bool]] = None
) -> Dict[str, Any]:
    """Create a LiveKit room for voice interaction with enhanced features"""
    
    try:
        # Generate room name if not provided
        if not room_name:
            room_name = f"doc-intelligence-{uuid.uuid4().hex[:8]}"
        
        session_id = str(uuid.uuid4())
        
        # Default audio settings for optimal quality
        if audio_settings is None:
            audio_settings = {
                "echo_cancellation": True,
                "noise_suppression": True, 
                "auto_gain_control": True
            }
        
        # Create LiveKit room service
        room_service = api.RoomService(
            settings.livekit_url,
            settings.livekit_api_key,
            settings.livekit_api_secret
        )
        
        # Create room with enhanced configuration
        room = await room_service.create_room(
            api.CreateRoomRequest(
                name=room_name,
                empty_timeout=300,  # 5 minutes
                max_participants=10,
                metadata=json.dumps({
                    "session_id": session_id,
                    "created_by": participant_name,
                    "created_at": datetime.utcnow().isoformat(),
                    "enable_transcription": enable_transcription,
                    "audio_settings": audio_settings,
                    "voice_stack": {
                        "stt": "deepgram_nova3",
                        "tts": "cartesia_sonic",
                        "llm": settings.openai_model
                    }
                })
            )
        )
        
        logger.info(f"Created room: {room_name} with session: {session_id}")
        
        # Generate participant access token
        token = api.AccessToken(
            settings.livekit_api_key,
            settings.livekit_api_secret
        )
        
        token.with_identity(participant_name)
        token.with_name(participant_name)
        token.with_grants(api.VideoGrants(
            room_join=True,
            room=room_name,
            can_subscribe=True,
            can_publish=True,
            can_publish_data=True,
            can_update_metadata=True
        ))
        
        # Add session metadata to token
        token.with_attributes({
            "session_id": session_id,
            "role": "participant",
            "deepgram_enabled": str(enable_transcription),
            "audio_settings": json.dumps(audio_settings)
        })
        
        # Set token expiration (2 hours)
        token.with_ttl(timedelta(hours=2))
        
        jwt_token = token.to_jwt()
        
        # Track room in memory
        active_rooms[room_name] = {
            "session_id": session_id,
            "created_at": datetime.utcnow(),
            "participant_name": participant_name,
            "participants": [participant_name],
            "enable_transcription": enable_transcription,
            "audio_settings": audio_settings,
            "agent_connected": False
        }
        
        return {
            "room_name": room_name,
            "token": jwt_token,
            "url": settings.livekit_url,
            "participant_name": participant_name,
            "session_id": session_id,
            "audio_config": {
                "sample_rate": 24000,  # Optimal for Cartesia
                "channels": 1,
                "echo_cancellation": audio_settings["echo_cancellation"],
                "noise_suppression": audio_settings["noise_suppression"],
                "auto_gain_control": audio_settings["auto_gain_control"]
            },
            "voice_stack": {
                "stt": {
                    "provider": "deepgram",
                    "model": settings.deepgram_model,
                    "language": settings.deepgram_language
                },
                "tts": {
                    "provider": "cartesia", 
                    "model": settings.cartesia_model,
                    "voice_id": settings.cartesia_voice_id
                }
            }
        }
        
    except Exception as e:
        logger.error(f"Failed to create voice room: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create room: {str(e)}")

@router.post("/join-room/{room_name}")
async def join_voice_room(
    room_name: str,
    participant_name: str = "User"
) -> Dict[str, Any]:
    """Join an existing voice room - enhanced version"""
    
    try:
        # Check if room exists
        if room_name not in active_rooms:
            raise HTTPException(status_code=404, detail="Room not found")
        
        room_info = active_rooms[room_name]
        
        # Generate token for new participant
        token = api.AccessToken(
            settings.livekit_api_key,
            settings.livekit_api_secret
        )
        
        token.with_identity(participant_name)
        token.with_name(participant_name)
        token.with_grants(api.VideoGrants(
            room_join=True,
            room=room_name,
            can_subscribe=True,
            can_publish=True,
            can_publish_data=True
        ))
        
        token.with_attributes({
            "session_id": room_info["session_id"],
            "role": "participant"
        })
        
        token.with_ttl(timedelta(hours=2))
        jwt_token = token.to_jwt()
        
        # Update participant list
        if participant_name not in room_info["participants"]:
            room_info["participants"].append(participant_name)
        
        return {
            "room_name": room_name,
            "token": jwt_token,
            "url": settings.livekit_url,
            "participant_name": participant_name,
            "session_id": room_info["session_id"]
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to join voice room: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to join room: {str(e)}")

@router.get("/rooms")
async def list_active_rooms() -> Dict[str, Any]:
    """List active voice rooms with enhanced information"""
    
    try:
        room_service = api.RoomService(
            settings.livekit_url,
            settings.livekit_api_key,
            settings.livekit_api_secret
        )
        
        rooms = await room_service.list_rooms(api.ListRoomsRequest())
        
        room_list = []
        for room in rooms.rooms:
            # Get additional info from our tracking
            local_info = active_rooms.get(room.name, {})
            
            # Get participants
            participants = await room_service.list_participants(
                api.ListParticipantsRequest(room=room.name)
            )
            
            # Check if agent is connected
            agent_connected = any(
                p.identity.startswith("agent") 
                for p in participants.participants
            )
            
            room_list.append({
                "name": room.name,
                "creation_time": room.creation_time,
                "num_participants": room.num_participants,
                "max_participants": room.max_participants,
                "metadata": json.loads(room.metadata) if room.metadata else {},
                "session_id": local_info.get("session_id"),
                "agent_connected": agent_connected,
                "enable_transcription": local_info.get("enable_transcription", True),
                "duration_seconds": (
                    datetime.utcnow() - local_info["created_at"]
                ).total_seconds() if "created_at" in local_info else 0
            })
        
        return {
            "rooms": room_list,
            "total": len(room_list),
            "active_sessions": len([r for r in room_list if r["agent_connected"]])
        }
        
    except Exception as e:
        logger.error(f"Failed to list rooms: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to list rooms: {str(e)}")

@router.get("/room/{room_name}/status")
async def get_room_status(room_name: str) -> Dict[str, Any]:
    """Get detailed status of a voice room"""
    
    try:
        room_service = api.RoomService(
            settings.livekit_url,
            settings.livekit_api_key,
            settings.livekit_api_secret
        )
        
        # Get room info
        try:
            room = await room_service.get_room(api.GetRoomRequest(room=room_name))
        except Exception:
            raise HTTPException(status_code=404, detail="Room not found")
        
        # Get participants
        participants = await room_service.list_participants(
            api.ListParticipantsRequest(room=room_name)
        )
        
        # Get local tracking info
        local_info = active_rooms.get(room_name, {})
        
        # Check agent status
        agent_info = None
        for p in participants.participants:
            if p.identity.startswith("agent"):
                agent_info = {
                    "connected": True,
                    "identity": p.identity,
                    "joined_at": p.joined_at,
                    "tracks": len(p.tracks)
                }
                break
        
        return {
            "room_name": room_name,
            "is_active": True,
            "session_id": local_info.get("session_id"),
            "participant_count": len(participants.participants),
            "participants": [
                {
                    "identity": p.identity,
                    "name": p.name,
                    "joined_at": p.joined_at,
                    "is_speaking": p.is_speaking
                }
                for p in participants.participants
            ],
            "agent": agent_info or {"connected": False},
            "metadata": json.loads(room.metadata) if room.metadata else {},
            "created_at": local_info.get("created_at", datetime.utcnow()).isoformat(),
            "duration_seconds": (
                datetime.utcnow() - local_info.get("created_at", datetime.utcnow())
            ).total_seconds()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get room status: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get room status: {str(e)}")

@router.delete("/room/{room_name}")
async def delete_voice_room(
    room_name: str,
    background_tasks: BackgroundTasks
) -> Dict[str, Any]:
    """Delete a voice room and cleanup resources"""
    
    try:
        room_service = api.RoomService(
            settings.livekit_url,
            settings.livekit_api_key,
            settings.livekit_api_secret
        )
        
        # Delete the room
        await room_service.delete_room(api.DeleteRoomRequest(room=room_name))
        
        # Remove from tracking
        session_id = None
        if room_name in active_rooms:
            session_id = active_rooms[room_name].get("session_id")
            del active_rooms[room_name]
        
        logger.info(f"Deleted room: {room_name}")
        
        # Schedule any cleanup tasks
        if session_id:
            background_tasks.add_task(cleanup_session_data, session_id)
        
        return {
            "message": f"Room '{room_name}' deleted successfully",
            "room_name": room_name,
            "session_id": session_id
        }
        
    except Exception as e:
        logger.error(f"Failed to delete room: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete room: {str(e)}")

@router.get("/health")
async def voice_health_check() -> Dict[str, Any]:
    """Enhanced health check for voice services"""
    
    health_status = {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "services": {
            "livekit": "unknown",
            "deepgram": "configured" if settings.deepgram_api_key else "not_configured",
            "cartesia": "configured" if settings.cartesia_api_key else "not_configured", 
            "openai": "configured" if settings.openai_api_key else "not_configured"
        },
        "configuration": {
            "deepgram_model": settings.deepgram_model,
            "cartesia_model": settings.cartesia_model,
            "cartesia_voice": settings.cartesia_voice_id,
            "target_latency_ms": settings.target_total_latency_ms
        },
        "active_rooms": len(active_rooms),
        "room_details": [
            {
                "name": name,
                "session_id": info.get("session_id"),
                "participants": len(info.get("participants", [])),
                "agent_connected": info.get("agent_connected", False),
                "duration_minutes": (
                    datetime.utcnow() - info.get("created_at", datetime.utcnow())
                ).total_seconds() / 60
            }
            for name, info in active_rooms.items()
        ]
    }
    
    # Check LiveKit connection
    try:
        room_service = api.RoomService(
            settings.livekit_url,
            settings.livekit_api_key,
            settings.livekit_api_secret
        )
        
        # Test connection by listing rooms
        rooms = await room_service.list_rooms(api.ListRoomsRequest())
        health_status["services"]["livekit"] = "healthy"
        health_status["livekit_rooms"] = len(rooms.rooms)
        
    except Exception as e:
        health_status["services"]["livekit"] = f"unhealthy: {str(e)}"
        health_status["status"] = "degraded"
    
    return health_status

# Background task for cleanup
async def cleanup_session_data(session_id: str):
    """Cleanup session data after room deletion"""
    logger.info(f"Cleaning up session data for: {session_id}")
    # Add any additional cleanup logic here
    # e.g., save transcripts, update database, etc.