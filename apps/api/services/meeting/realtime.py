"""
Meeting realtime hub.

Fans meeting events (nudges, utterances) out to every WebSocket
subscribed to a meeting — *across replicas*. A nudge produced by the
dispatcher on replica B must reach a client connected to replica A, so
delivery goes through a Redis pub/sub channel:

    broadcast()  ──PUBLISH──►  Redis "meeting:events"  ──┐
                                                         │ (every replica
    connect()    ──SUBSCRIBE─►  listener ──► local WS ◄──┘  is subscribed)

When Redis is unavailable the hub degrades to in-process delivery
(single-replica dev/demo still works), keyed exactly as before.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict, Optional, Set

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class MeetingHub:
    """Per-meeting fan-out registry with cross-replica Redis pub/sub."""

    CHANNEL = "meeting:events"

    def __init__(self) -> None:
        self._connections: Dict[str, Set[WebSocket]] = {}
        self._lock = asyncio.Lock()
        self._redis = None
        self._redis_checked = False
        self._listener_task: Optional[asyncio.Task] = None

    # -- Redis plumbing ----------------------------------------------------

    async def _get_redis(self):
        """Lazily fetch the shared Redis client (cached)."""
        if self._redis is not None:
            return self._redis
        if self._redis_checked:
            return None
        self._redis_checked = True
        try:
            from apps.api.core.connections import get_redis_client

            self._redis = await get_redis_client()
        except Exception as e:
            logger.warning(f"[Hub] Redis unavailable, local-only fan-out: {e}")
            self._redis = None
        return self._redis

    async def _ensure_listener(self) -> None:
        """Start the cross-replica subscription once per process."""
        if self._listener_task is not None:
            return
        r = await self._get_redis()
        if r is None:
            return
        async with self._lock:
            if self._listener_task is None:
                self._listener_task = asyncio.create_task(self._listen())
                logger.info("[Hub] Redis pub/sub fan-out enabled")

    async def _listen(self) -> None:
        r = self._redis
        try:
            pubsub = r.pubsub()
            await pubsub.subscribe(self.CHANNEL)
            async for msg in pubsub.listen():
                if msg.get("type") != "message":
                    continue
                try:
                    envelope = json.loads(msg["data"])
                    await self._deliver_local(
                        envelope["meeting_id"],
                        json.dumps(envelope["payload"], default=str),
                    )
                except Exception as e:
                    logger.debug(f"[Hub] listener decode error: {e}")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning(f"[Hub] listener stopped, falling back to local: {e}")
            self._listener_task = None
            self._redis = None  # future broadcasts deliver locally

    # -- Public API --------------------------------------------------------

    async def connect(self, meeting_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections.setdefault(meeting_id, set()).add(websocket)
        await self._ensure_listener()
        logger.info(
            f"[Hub] meeting={meeting_id} subscribed "
            f"(local={len(self._connections.get(meeting_id, set()))})"
        )

    async def disconnect(self, meeting_id: str, websocket: WebSocket) -> None:
        async with self._lock:
            conns = self._connections.get(meeting_id)
            if conns and websocket in conns:
                conns.remove(websocket)
                if not conns:
                    self._connections.pop(meeting_id, None)
        logger.info(f"[Hub] meeting={meeting_id} unsubscribed")

    async def broadcast(self, meeting_id: str, message: Dict[str, Any]) -> None:
        """Publish a meeting event to all replicas (or deliver locally if
        Redis is down). Safe to call from background tasks."""
        r = await self._get_redis()
        if r is not None:
            try:
                await r.publish(
                    self.CHANNEL,
                    json.dumps(
                        {"meeting_id": meeting_id, "payload": message}, default=str
                    ),
                )
                return
            except Exception as e:
                logger.debug(f"[Hub] publish failed, local delivery: {e}")

        # Fallback: deliver directly to this replica's sockets
        await self._deliver_local(meeting_id, json.dumps(message, default=str))

    # -- Internal ----------------------------------------------------------

    async def _deliver_local(self, meeting_id: str, payload_str: str) -> None:
        """Send an already-serialized payload to this replica's sockets."""
        conns = list(self._connections.get(meeting_id, set()))
        if not conns:
            return

        dead: list[WebSocket] = []
        for ws in conns:
            try:
                await ws.send_text(payload_str)
            except Exception as e:
                logger.debug(f"[Hub] dropping dead socket: {e}")
                dead.append(ws)

        if dead:
            async with self._lock:
                live = self._connections.get(meeting_id)
                if live:
                    for ws in dead:
                        live.discard(ws)
                    if not live:
                        self._connections.pop(meeting_id, None)


meeting_hub = MeetingHub()
