# apps/api/services/communication/webrtc_unified_service.py
"""
Unified WebRTC Service - Core implementation for Voice Document Intelligence System
Handles all communication types through a single WebRTC connection
"""

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

import aioredis
from aiortc import (
    RTCDataChannel,
    RTCIceCandidate,
    RTCPeerConnection,
    RTCSessionDescription,
)
from prometheus_client import Counter, Gauge, Histogram

from apps.api.core.config import settings
from apps.api.core.connections import get_redis_client

logger = logging.getLogger(__name__)

# Metrics
rtc_connections_total = Counter(
    "rtc_connections_total", "Total WebRTC connections created"
)
rtc_active_connections = Gauge(
    "rtc_active_connections", "Currently active WebRTC connections"
)
rtc_message_latency = Histogram(
    "rtc_message_latency_seconds", "Message delivery latency", ["channel"]
)
rtc_messages_total = Counter(
    "rtc_messages_total", "Total messages sent", ["channel", "type"]
)
rtc_errors_total = Counter("rtc_errors_total", "Total WebRTC errors", ["error_type"])


class ChannelType(Enum):
    """WebRTC data channel types"""

    CONTROL = "control"  # Reliable, ordered control messages
    DATA = "data"  # Reliable, ordered data transfer
    ANALYTICS = "analytics"  # Unreliable, unordered analytics
    REALTIME = "realtime"  # Unreliable, ordered real-time updates


class MessagePriority(Enum):
    """Message priority levels"""

    LOW = 0
    NORMAL = 1
    HIGH = 2
    CRITICAL = 3


@dataclass
class ChannelConfig:
    """Data channel configuration"""

    ordered: bool = True
    max_retransmits: Optional[int] = None
    max_packet_life_time: Optional[int] = None
    protocol: str = ""
    negotiated: bool = False
    id: Optional[int] = None


@dataclass
class RTCMessage:
    """Structured message for WebRTC communication"""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    type: str = ""
    channel: str = ""
    payload: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)
    priority: MessagePriority = MessagePriority.NORMAL
    require_ack: bool = False
    retry_count: int = 0


@dataclass
class RTCSession:
    """WebRTC session information"""

    id: str
    peer_connection: RTCPeerConnection
    data_channels: Dict[str, RTCDataChannel] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)
    user_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    message_queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    pending_acks: Dict[str, RTCMessage] = field(default_factory=dict)
    metrics: Dict[str, Any] = field(default_factory=dict)


class UnifiedWebRTCService:
    """
    Unified WebRTC service for all communication types
    Replaces WebSocket, REST, and separate voice channels
    """

    # Channel configurations
    CHANNEL_CONFIGS = {
        ChannelType.CONTROL: ChannelConfig(
            ordered=True,
            max_retransmits=None,  # Unlimited retransmits (reliable)
            protocol="control-v1",
        ),
        ChannelType.DATA: ChannelConfig(
            ordered=True, max_retransmits=3, protocol="data-v1"
        ),
        ChannelType.ANALYTICS: ChannelConfig(
            ordered=False,
            max_packet_life_time=5000,  # 5 seconds
            protocol="analytics-v1",
        ),
        ChannelType.REALTIME: ChannelConfig(
            ordered=True,
            max_packet_life_time=1000,  # 1 second
            protocol="realtime-v1",
        ),
    }

    def __init__(self):
        self.sessions: Dict[str, RTCSession] = {}
        self.redis_client: Optional[aioredis.Redis] = None
        self.message_handlers: Dict[str, List[Callable]] = {}
        self.ice_servers = self._configure_ice_servers()

        # Message processing
        self._message_processor_task: Optional[asyncio.Task] = None
        self._health_monitor_task: Optional[asyncio.Task] = None

        # Performance settings
        self.max_message_size = 16 * 1024  # 16KB
        self.message_batch_size = 10
        self.message_batch_timeout = 0.05  # 50ms

    def _configure_ice_servers(self) -> List[Dict[str, Any]]:
        """Configure STUN/TURN servers"""
        servers = [
            {"urls": ["stun:stun.l.google.com:19302"]},
            {"urls": ["stun:stun1.l.google.com:19302"]},
        ]

        # Add TURN servers if configured
        if hasattr(settings, "turn_servers") and settings.turn_servers:
            servers.extend(
                [
                    {
                        "urls": settings.turn_servers,
                        "username": settings.turn_username,
                        "credential": settings.turn_credential,
                    }
                ]
            )

        return servers

    async def initialize(self):
        """Initialize the service"""
        try:
            # Connect to Redis for pub/sub
            self.redis_client = await get_redis_client()

            # Start background tasks
            self._message_processor_task = asyncio.create_task(
                self._process_message_queues()
            )
            self._health_monitor_task = asyncio.create_task(
                self._monitor_connection_health()
            )

            logger.info("UnifiedWebRTCService initialized successfully")

        except Exception as e:
            logger.error(f"Failed to initialize WebRTC service: {e}")
            raise

    async def create_session(
        self,
        user_id: Optional[str] = None,
        capabilities: List[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> RTCSession:
        """Create a new WebRTC session with all channels"""

        session_id = str(uuid.uuid4())

        # Create peer connection
        pc = RTCPeerConnection(
            configuration={
                "iceServers": self.ice_servers,
                "iceCandidatePoolSize": 10,
                "bundlePolicy": "max-bundle",
                "rtcpMuxPolicy": "require",
            }
        )

        # Create session
        session = RTCSession(
            id=session_id, peer_connection=pc, user_id=user_id, metadata=metadata or {}
        )

        # Set up ICE connection state monitoring
        @pc.on("iceconnectionstatechange")
        async def on_ice_state_change():
            logger.info(
                f"ICE connection state: {pc.iceConnectionState} for session {session_id}"
            )

            if pc.iceConnectionState == "failed":
                await self._handle_connection_failure(session_id)
            elif pc.iceConnectionState == "disconnected":
                await self._handle_disconnection(session_id)

        # Create data channels based on capabilities
        if not capabilities or "data" in capabilities:
            await self._create_data_channels(session)

        # Store session
        self.sessions[session_id] = session
        rtc_connections_total.inc()
        rtc_active_connections.inc()

        logger.info(f"Created WebRTC session {session_id} for user {user_id}")

        return session

    async def _create_data_channels(self, session: RTCSession):
        """Create all data channels for the session"""

        for channel_type, config in self.CHANNEL_CONFIGS.items():
            # Create data channel
            channel = session.peer_connection.createDataChannel(
                channel_type.value,
                ordered=config.ordered,
                maxRetransmits=config.max_retransmits,
                maxPacketLifeTime=config.max_packet_life_time,
                protocol=config.protocol,
                negotiated=config.negotiated,
                id=config.id,
            )

            # Set up event handlers
            @channel.on("open")
            async def on_open(ch=channel, ct=channel_type):
                logger.info(f"Data channel {ct.value} opened for session {session.id}")
                await self._handle_channel_open(session.id, ct.value)

            @channel.on("close")
            async def on_close(ch=channel, ct=channel_type):
                logger.info(f"Data channel {ct.value} closed for session {session.id}")
                await self._handle_channel_close(session.id, ct.value)

            @channel.on("message")
            async def on_message(message, ch=channel, ct=channel_type):
                await self._handle_channel_message(session.id, ct.value, message)

            # Store channel
            session.data_channels[channel_type.value] = channel

    async def create_offer(self, session_id: str) -> Dict[str, str]:
        """Create WebRTC offer"""

        session = self.sessions.get(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")

        # Create offer
        offer = await session.peer_connection.createOffer()
        await session.peer_connection.setLocalDescription(offer)

        return {"type": offer.type, "sdp": offer.sdp}

    async def handle_answer(self, session_id: str, answer: Dict[str, str]) -> bool:
        """Handle WebRTC answer from client"""

        session = self.sessions.get(session_id)
        if not session:
            return False

        try:
            # Set remote description
            await session.peer_connection.setRemoteDescription(
                RTCSessionDescription(sdp=answer["sdp"], type=answer["type"])
            )

            logger.info(f"Set remote description for session {session_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to set remote description: {e}")
            rtc_errors_total.labels(error_type="answer_failed").inc()
            return False

    async def add_ice_candidate(
        self, session_id: str, candidate: Dict[str, Any]
    ) -> bool:
        """Add ICE candidate"""

        session = self.sessions.get(session_id)
        if not session:
            return False

        try:
            ice_candidate = RTCIceCandidate(
                component=candidate.get("component", 1),
                foundation=candidate.get("foundation", ""),
                ip=candidate.get("ip", ""),
                port=candidate.get("port", 0),
                priority=candidate.get("priority", 0),
                protocol=candidate.get("protocol", ""),
                type=candidate.get("type", ""),
                sdpMLineIndex=candidate.get("sdpMLineIndex"),
                sdpMid=candidate.get("sdpMid"),
            )

            await session.peer_connection.addIceCandidate(ice_candidate)
            return True

        except Exception as e:
            logger.error(f"Failed to add ICE candidate: {e}")
            return False

    async def send_message(
        self,
        session_id: str,
        channel: str,
        message_type: str,
        payload: Any,
        priority: MessagePriority = MessagePriority.NORMAL,
        require_ack: bool = False,
    ) -> bool:
        """Send message through WebRTC data channel"""

        session = self.sessions.get(session_id)
        if not session:
            return False

        # Create message
        message = RTCMessage(
            type=message_type,
            channel=channel,
            payload=payload,
            priority=priority,
            require_ack=require_ack,
        )

        # Queue message for processing
        await session.message_queue.put((priority.value, message))

        # Track metrics
        rtc_messages_total.labels(channel=channel, type=message_type).inc()

        return True

    async def broadcast(
        self,
        channel: str,
        message_type: str,
        payload: Any,
        target_sessions: Optional[List[str]] = None,
        exclude_sessions: Optional[List[str]] = None,
    ):
        """Broadcast message to multiple sessions"""

        sessions = target_sessions or list(self.sessions.keys())

        # Filter excluded sessions
        if exclude_sessions:
            sessions = [s for s in sessions if s not in exclude_sessions]

        # Send to all target sessions
        tasks = []
        for session_id in sessions:
            if session_id in self.sessions:
                tasks.append(
                    self.send_message(
                        session_id,
                        channel,
                        message_type,
                        payload,
                        priority=MessagePriority.NORMAL,
                    )
                )

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _process_message_queues(self):
        """Background task to process message queues"""

        while True:
            try:
                # Process each session's queue
                for session_id, session in list(self.sessions.items()):
                    await self._process_session_queue(session)

                # Small delay to prevent busy loop
                await asyncio.sleep(0.01)

            except Exception as e:
                logger.error(f"Error in message processor: {e}")
                await asyncio.sleep(1)

    async def _process_session_queue(self, session: RTCSession):
        """Process messages for a single session"""

        messages_to_send = []
        deadline = time.time() + self.message_batch_timeout

        # Collect messages up to batch size or timeout
        while (
            len(messages_to_send) < self.message_batch_size and time.time() < deadline
        ):
            try:
                priority, message = await asyncio.wait_for(
                    session.message_queue.get(), timeout=self.message_batch_timeout
                )
                messages_to_send.append(message)
            except asyncio.TimeoutError:
                break

        # Send collected messages
        for message in messages_to_send:
            await self._send_message_internal(session, message)

    async def _send_message_internal(self, session: RTCSession, message: RTCMessage):
        """Internal method to send a single message"""

        channel = session.data_channels.get(message.channel)
        if not channel or channel.readyState != "open":
            logger.warning(
                f"Channel {message.channel} not ready for session {session.id}"
            )
            return

        try:
            # Serialize message
            message_data = json.dumps(
                {
                    "id": message.id,
                    "type": message.type,
                    "payload": message.payload,
                    "timestamp": message.timestamp.isoformat(),
                    "require_ack": message.require_ack,
                }
            )

            # Check message size
            if len(message_data) > self.max_message_size:
                # Split large messages
                await self._send_chunked_message(channel, message_data)
            else:
                # Send directly
                channel.send(message_data)

            # Track pending acknowledgments
            if message.require_ack:
                session.pending_acks[message.id] = message

                # Set timeout for acknowledgment
                asyncio.create_task(self._ack_timeout(session.id, message.id, 5.0))

            # Update metrics
            with rtc_message_latency.labels(channel=message.channel).time():
                pass

        except Exception as e:
            logger.error(f"Failed to send message: {e}")
            rtc_errors_total.labels(error_type="send_failed").inc()

    async def _handle_channel_message(
        self, session_id: str, channel: str, raw_message: str
    ):
        """Handle incoming message from data channel"""

        try:
            # Parse message
            data = json.loads(raw_message)

            # Handle acknowledgments
            if data.get("type") == "ack":
                await self._handle_acknowledgment(session_id, data.get("ack_id"))
                return

            # Create RTCMessage
            message = RTCMessage(
                id=data.get("id", str(uuid.uuid4())),
                type=data.get("type", ""),
                channel=channel,
                payload=data.get("payload", {}),
                timestamp=datetime.fromisoformat(
                    data.get("timestamp", datetime.now().isoformat())
                ),
            )

            # Send acknowledgment if required
            if data.get("require_ack"):
                await self._send_acknowledgment(session_id, channel, message.id)

            # Process message
            await self._dispatch_message(session_id, message)

        except json.JSONDecodeError:
            logger.error(f"Invalid JSON message received: {raw_message[:100]}")
        except Exception as e:
            logger.error(f"Error handling message: {e}")

    async def _dispatch_message(self, session_id: str, message: RTCMessage):
        """Dispatch message to registered handlers"""

        # Get handlers for message type
        handlers = self.message_handlers.get(message.type, [])

        # Execute handlers
        for handler in handlers:
            try:
                await handler(session_id, message)
            except Exception as e:
                logger.error(f"Handler error for message type {message.type}: {e}")

    def on_message(self, message_type: str, handler: Callable):
        """Register message handler"""

        if message_type not in self.message_handlers:
            self.message_handlers[message_type] = []

        self.message_handlers[message_type].append(handler)

    async def _monitor_connection_health(self):
        """Monitor health of all connections"""

        while True:
            try:
                for session_id, session in list(self.sessions.items()):
                    # Get connection stats
                    stats = await self._get_connection_stats(session)

                    # Update session metrics
                    session.metrics.update(stats)

                    # Check connection health
                    if stats.get("connection_state") == "failed":
                        await self._handle_connection_failure(session_id)
                    elif stats.get("rtt", 0) > 500:  # High latency
                        logger.warning(
                            f"High RTT detected for session {session_id}: {stats['rtt']}ms"
                        )

                # Check every 5 seconds
                await asyncio.sleep(5)

            except Exception as e:
                logger.error(f"Error in health monitor: {e}")
                await asyncio.sleep(10)

    async def _get_connection_stats(self, session: RTCSession) -> Dict[str, Any]:
        """Get WebRTC connection statistics"""

        try:
            stats = await session.peer_connection.getStats()

            processed_stats = {
                "connection_state": session.peer_connection.connectionState,
                "ice_connection_state": session.peer_connection.iceConnectionState,
                "signaling_state": session.peer_connection.signalingState,
                "rtt": 0,
                "packet_loss": 0,
                "jitter": 0,
                "bytes_sent": 0,
                "bytes_received": 0,
            }

            # Process raw stats
            for stat in stats.values():
                if stat.type == "candidate-pair" and stat.state == "succeeded":
                    processed_stats["rtt"] = stat.get("currentRoundTripTime", 0) * 1000
                elif stat.type == "inbound-rtp":
                    processed_stats["packet_loss"] = stat.get("packetsLost", 0)
                    processed_stats["jitter"] = stat.get("jitter", 0)
                elif stat.type == "transport":
                    processed_stats["bytes_sent"] = stat.get("bytesSent", 0)
                    processed_stats["bytes_received"] = stat.get("bytesReceived", 0)

            return processed_stats

        except Exception as e:
            logger.error(f"Failed to get connection stats: {e}")
            return {}

    async def close_session(self, session_id: str):
        """Close WebRTC session"""

        session = self.sessions.get(session_id)
        if not session:
            return

        try:
            # Close all data channels
            for channel in session.data_channels.values():
                if channel.readyState == "open":
                    channel.close()

            # Close peer connection
            await session.peer_connection.close()

            # Remove session
            del self.sessions[session_id]
            rtc_active_connections.dec()

            logger.info(f"Closed WebRTC session {session_id}")

        except Exception as e:
            logger.error(f"Error closing session: {e}")

    async def shutdown(self):
        """Shutdown the service"""

        logger.info("Shutting down UnifiedWebRTCService")

        # Cancel background tasks
        if self._message_processor_task:
            self._message_processor_task.cancel()
        if self._health_monitor_task:
            self._health_monitor_task.cancel()

        # Close all sessions
        for session_id in list(self.sessions.keys()):
            await self.close_session(session_id)

        # Close Redis connection
        if self.redis_client:
            self.redis_client.close()
            await self.redis_client.wait_closed()


# Singleton instance
unified_rtc_service = UnifiedWebRTCService()
