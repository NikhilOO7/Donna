"""
Meeting realtime hub.

In-memory pub/sub keyed by meeting_id. Routes/agents call
``meeting_hub.broadcast(meeting_id, msg)`` to push events to every
WebSocket subscribed to that meeting. Currently used for live nudge
delivery and utterance fan-out so the UI doesn't need to poll.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict, Set

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class MeetingHub:
    """Per-meeting fan-out registry."""

    def __init__(self) -> None:
        self._connections: Dict[str, Set[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, meeting_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections.setdefault(meeting_id, set()).add(websocket)
        logger.info(
            f"[Hub] meeting={meeting_id} subscribed "
            f"(total={len(self._connections.get(meeting_id, set()))})"
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
        """Send a JSON message to every WebSocket subscribed to meeting_id.

        Safe to call from background tasks; silently drops dead sockets.
        """
        conns = list(self._connections.get(meeting_id, set()))
        if not conns:
            return

        payload = json.dumps(message, default=str)
        dead: list[WebSocket] = []
        for ws in conns:
            try:
                await ws.send_text(payload)
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
