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
from typing import Any, Dict, Optional

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class MeetingHub:
    """Per-meeting fan-out registry with cross-replica Redis pub/sub."""

    CHANNEL = "meeting:events"

    def __init__(self) -> None:
        # meeting_id -> {websocket: {'role': str, 'name': str|None}}
        self._connections: Dict[str, Dict[WebSocket, Dict[str, Any]]] = {}
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
                        envelope["meeting_id"], envelope["payload"]
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

    async def connect(
        self,
        meeting_id: str,
        websocket: WebSocket,
        role: str = "leader",
        my_name: str | None = None,
    ) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections.setdefault(meeting_id, {})[websocket] = {
                "role": role,
                "name": my_name,
            }
        await self._ensure_listener()
        logger.info(
            f"[Hub] meeting={meeting_id} subscribed role={role} "
            f"(local={len(self._connections.get(meeting_id, {}))})"
        )

    async def disconnect(self, meeting_id: str, websocket: WebSocket) -> None:
        async with self._lock:
            conns = self._connections.get(meeting_id)
            if conns and websocket in conns:
                conns.pop(websocket, None)
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
        await self._deliver_local(meeting_id, message)

    # -- Internal ----------------------------------------------------------

    @staticmethod
    def _visible_to(payload: Dict[str, Any], meta: Dict[str, Any]) -> bool:
        """Per-connection visibility — the server-side privacy boundary.

        Leaders see every event. Participants see everything EXCEPT
        unshared nudges: only pinned (shared-board) nudges and activation
        nudges addressed to them personally are delivered.
        """
        if meta.get("role") != "participant":
            return True
        if payload.get("type") != "nudge_created":
            return True
        nudge = payload.get("nudge") or {}
        if nudge.get("pinned_at"):
            return True
        if nudge.get("type") == "activation":
            person = ((nudge.get("source_data") or {}).get("person") or "").lower()
            name = (meta.get("name") or "").lower()
            return bool(name) and person == name
        return False

    async def _deliver_local(self, meeting_id: str, payload: Dict[str, Any]) -> None:
        """Send a payload to this replica's sockets, filtered per connection."""
        conns = dict(self._connections.get(meeting_id, {}))
        if not conns:
            return

        payload_str = json.dumps(payload, default=str)
        dead: list[WebSocket] = []
        for ws, meta in conns.items():
            if not self._visible_to(payload, meta):
                continue
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
                        live.pop(ws, None)
                    if not live:
                        self._connections.pop(meeting_id, None)


meeting_hub = MeetingHub()
