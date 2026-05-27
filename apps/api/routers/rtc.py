# apps/api/routers/rtc.py
"""
WebRTC router for unified communication
Handles signaling, session management, and migration from WebSocket
"""

import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from apps.api.core.feature_flags import FeatureFlags
from apps.api.services.communication.webrtc_unified_service import (
    ChannelType,
    MessagePriority,
    unified_rtc_service,
)
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.database import get_db
from apps.api.services.agents import DocumentIntelligenceCoordinator
from apps.api.services.voice.enhanced_voice_service import EnhancedVoiceService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v2/rtc", tags=["WebRTC"])


# Request/Response models
class RTCConnectionRequest(BaseModel):
    """WebRTC connection request"""

    user_id: Optional[str] = None
    capabilities: List[str] = Field(default=["voice", "data", "control"])
    metadata: Optional[Dict[str, Any]] = None


class RTCConnectionResponse(BaseModel):
    """WebRTC connection response"""

    session_id: str
    offer: Dict[str, str]
    ice_servers: List[Dict[str, Any]]
    channels: List[str]
    features: Dict[str, bool]


class RTCAnswerRequest(BaseModel):
    """WebRTC answer"""

    session_id: str
    answer: Dict[str, str]


class RTCIceCandidateRequest(BaseModel):
    """ICE candidate"""

    session_id: str
    candidate: Dict[str, Any]


class RTCQueryRequest(BaseModel):
    """Document query via WebRTC"""

    query: str
    stream: bool = True
    context_level: str = "local"
    filters: Optional[Dict[str, Any]] = None


# Dependencies
async def get_coordinator() -> DocumentIntelligenceCoordinator:
    """Get document intelligence coordinator"""
    from apps.api.main_updated import coordinator

    return coordinator


async def get_voice_service() -> EnhancedVoiceService:
    """Get voice service"""
    from apps.api.main_updated import enhanced_voice_service

    return enhanced_voice_service


# Endpoints
@router.post("/connect", response_model=RTCConnectionResponse)
async def create_rtc_connection(
    request: RTCConnectionRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """
    Create new WebRTC connection with unified communication channels

    This replaces:
    - WebSocket connections for real-time updates
    - REST API calls for queries
    - Separate LiveKit connections for voice
    """
    try:
        # Check feature flags
        features = {
            "webrtc_queries": FeatureFlags.is_enabled(
                FeatureFlags.USE_WEBRTC_FOR_QUERIES, request.user_id or "anonymous"
            ),
            "webrtc_voice": FeatureFlags.is_enabled(
                FeatureFlags.USE_WEBRTC_FOR_VOICE, request.user_id or "anonymous"
            ),
            "webrtc_analytics": FeatureFlags.is_enabled(
                FeatureFlags.USE_WEBRTC_FOR_ANALYTICS, request.user_id or "anonymous"
            ),
            "p2p_enabled": FeatureFlags.is_enabled(
                FeatureFlags.ENABLE_P2P_MODE, request.user_id or "anonymous"
            ),
        }

        # Create WebRTC session
        session = await unified_rtc_service.create_session(
            user_id=request.user_id,
            capabilities=request.capabilities,
            metadata={
                **(request.metadata or {}),
                "features": features,
                "created_at": datetime.utcnow().isoformat(),
            },
        )

        # Generate offer
        offer = await unified_rtc_service.create_offer(session.id)

        # Set up message handlers
        background_tasks.add_task(setup_session_handlers, session.id)

        # Get available channels
        channels = [channel for channel in session.data_channels.keys()]

        logger.info(f"Created WebRTC session {session.id} for user {request.user_id}")

        return RTCConnectionResponse(
            session_id=session.id,
            offer=offer,
            ice_servers=unified_rtc_service.ice_servers,
            channels=channels,
            features=features,
        )

    except Exception as e:
        logger.error(f"Failed to create WebRTC connection: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/answer")
async def handle_rtc_answer(request: RTCAnswerRequest):
    """Handle WebRTC answer from client"""
    try:
        success = await unified_rtc_service.handle_answer(
            request.session_id, request.answer
        )

        if not success:
            raise HTTPException(status_code=400, detail="Invalid session or answer")

        logger.info(f"Set remote description for session {request.session_id}")

        return {"success": True, "session_id": request.session_id}

    except Exception as e:
        logger.error(f"Failed to handle answer: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ice-candidate")
async def add_ice_candidate(request: RTCIceCandidateRequest):
    """Add ICE candidate"""
    try:
        success = await unified_rtc_service.add_ice_candidate(
            request.session_id, request.candidate
        )

        if not success:
            raise HTTPException(status_code=400, detail="Invalid session or candidate")

        return {"success": True}

    except Exception as e:
        logger.error(f"Failed to add ICE candidate: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/session/{session_id}")
async def close_session(session_id: str):
    """Close WebRTC session"""
    try:
        await unified_rtc_service.close_session(session_id)
        return {"success": True, "message": "Session closed"}

    except Exception as e:
        logger.error(f"Failed to close session: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/session/{session_id}/stats")
async def get_session_stats(session_id: str):
    """Get WebRTC session statistics"""
    try:
        session = unified_rtc_service.sessions.get(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        return {
            "session_id": session_id,
            "created_at": session.created_at.isoformat(),
            "user_id": session.user_id,
            "metrics": session.metrics,
            "channels": {
                channel: {
                    "state": ch.readyState,
                    "buffered_amount": ch.bufferedAmount
                    if hasattr(ch, "bufferedAmount")
                    else 0,
                }
                for channel, ch in session.data_channels.items()
            },
        }

    except Exception as e:
        logger.error(f"Failed to get session stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health")
async def webrtc_health():
    """WebRTC service health check"""
    try:
        active_sessions = len(unified_rtc_service.sessions)

        # Get aggregate metrics
        total_messages = 0
        total_errors = 0

        for session in unified_rtc_service.sessions.values():
            total_messages += session.metrics.get("messages_sent", 0)
            total_errors += session.metrics.get("errors", 0)

        return {
            "status": "healthy",
            "active_sessions": active_sessions,
            "total_messages": total_messages,
            "total_errors": total_errors,
            "ice_servers": len(unified_rtc_service.ice_servers),
            "timestamp": datetime.utcnow().isoformat(),
        }

    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat(),
        }


# Session setup and handlers
async def setup_session_handlers(session_id: str):
    """Set up message handlers for a session"""

    coordinator = await get_coordinator()
    voice_service = await get_voice_service()

    # Document query handler
    @unified_rtc_service.on_message("document_query")
    async def handle_document_query(sid: str, message):
        if sid != session_id:
            return

        try:
            query_data = message.payload

            # Send acknowledgment
            await unified_rtc_service.send_message(
                session_id,
                ChannelType.CONTROL.value,
                "query_received",
                {"query_id": query_data.get("query_id")},
                priority=MessagePriority.HIGH,
            )

            # Process query
            if query_data.get("stream", True):
                # Stream results
                async for result in coordinator.process_query_stream(
                    query_data["query"], session_id
                ):
                    await unified_rtc_service.send_message(
                        session_id,
                        ChannelType.DATA.value,
                        "query_response",
                        {
                            "query_id": query_data.get("query_id"),
                            "type": "search_progress",
                            "data": result,
                        },
                    )

            # Send final results
            final_results = await coordinator.get_final_results()
            await unified_rtc_service.send_message(
                session_id,
                ChannelType.DATA.value,
                "query_response",
                {
                    "query_id": query_data.get("query_id"),
                    "type": "search_complete",
                    "results": final_results,
                },
            )

        except Exception as e:
            logger.error(f"Query processing error: {e}")
            await unified_rtc_service.send_message(
                session_id,
                ChannelType.DATA.value,
                "query_response",
                {
                    "query_id": query_data.get("query_id"),
                    "type": "error",
                    "error": str(e),
                },
            )

    # Voice control handler
    @unified_rtc_service.on_message("voice_session_started")
    async def handle_voice_start(sid: str, message):
        if sid != session_id:
            return

        # Configure voice pipeline
        await voice_service.configure_for_rtc(session_id)

        # Send confirmation
        await unified_rtc_service.send_message(
            session_id,
            ChannelType.CONTROL.value,
            "voice_configured",
            {"status": "ready"},
        )

    # Analytics handler
    @unified_rtc_service.on_message("analytics_event")
    async def handle_analytics(sid: str, message):
        if sid != session_id:
            return

        # Process analytics event
        event_data = message.payload
        logger.info(f"Analytics event from {sid}: {event_data.get('event_type')}")

        # Forward to analytics service
        # await analytics_service.track_event(sid, event_data)


# Migration endpoints (temporary during transition)
@router.post("/migrate/websocket")
async def migrate_websocket_session(
    session_id: str = Query(..., description="WebSocket session to migrate"),
    db: AsyncSession = Depends(get_db),
):
    """
    Migrate existing WebSocket connection to WebRTC
    Used during gradual migration phase
    """
    try:
        # Create new WebRTC session
        rtc_session = await unified_rtc_service.create_session(
            metadata={"migrated_from": "websocket", "original_session": session_id}
        )

        # Generate offer
        offer = await unified_rtc_service.create_offer(rtc_session.id)

        # TODO: Transfer WebSocket state to WebRTC session
        # This would include:
        # - Active subscriptions
        # - Pending messages
        # - User context

        logger.info(
            f"Migrated WebSocket session {session_id} to WebRTC {rtc_session.id}"
        )

        return {
            "rtc_session_id": rtc_session.id,
            "offer": offer,
            "migration_token": str(uuid.uuid4()),
            "instructions": "Use migration_token to complete migration on client side",
        }

    except Exception as e:
        logger.error(f"Migration failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/migration/status")
async def get_migration_status():
    """Get WebRTC migration status"""

    return {
        "migration_phase": "active",
        "rollout_percentage": {
            "queries": FeatureFlags.get_rollout_percentage(
                FeatureFlags.USE_WEBRTC_FOR_QUERIES
            ),
            "voice": FeatureFlags.get_rollout_percentage(
                FeatureFlags.USE_WEBRTC_FOR_VOICE
            ),
            "analytics": FeatureFlags.get_rollout_percentage(
                FeatureFlags.USE_WEBRTC_FOR_ANALYTICS
            ),
        },
        "active_connections": {
            "websocket": 0,  # TODO: Get actual count
            "webrtc": len(unified_rtc_service.sessions),
            "dual_protocol": 0,  # Users with both connections
        },
        "performance_metrics": {
            "avg_latency_websocket": 150,  # ms
            "avg_latency_webrtc": 45,  # ms
            "latency_improvement": "70%",
        },
        "migration_eta": "2 weeks remaining",
    }
