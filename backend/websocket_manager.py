"""
WebSocket manager: tracks active connections per analysis_id and broadcasts
structured progress messages to all listening clients.

Usage in routes:
    from websocket_manager import ws_manager
    await ws_manager.send_progress(analysis_id, "Collecting Droplets...", stage=4)
"""
import json
import logging
from typing import Dict, List

from fastapi import WebSocket
from starlette.websockets import WebSocketState

logger = logging.getLogger(__name__)

TOTAL_STAGES = 13


class WebSocketManager:
    def __init__(self) -> None:
        # analysis_id → list of connected WebSocket clients
        self._connections: Dict[str, List[WebSocket]] = {}

    async def connect(self, analysis_id: str, websocket: WebSocket) -> None:
        """Accept a new WebSocket connection and register it."""
        await websocket.accept()
        self._connections.setdefault(analysis_id, []).append(websocket)
        logger.debug(f"WS connected for analysis {analysis_id} "
                     f"(total={len(self._connections[analysis_id])})")

    def disconnect(self, analysis_id: str, websocket: WebSocket) -> None:
        """Remove a WebSocket from the registry."""
        conns = self._connections.get(analysis_id, [])
        if websocket in conns:
            conns.remove(websocket)
        if not conns:
            self._connections.pop(analysis_id, None)
        logger.debug(f"WS disconnected for analysis {analysis_id}")

    async def send_progress(
        self,
        analysis_id: str,
        message: str,
        stage: int,
        status: str = "running",
    ) -> None:
        """
        Broadcast a progress update to all clients watching analysis_id.

        Payload shape:
            {
              "stage": 4,
              "total_stages": 12,
              "progress_pct": 33,
              "message": "Collecting Droplets...",
              "status": "running"
            }
        """
        if analysis_id not in self._connections:
            return  # no listeners — fire-and-forget is intentional

        payload = json.dumps({
            "stage": stage,
            "total_stages": TOTAL_STAGES,
            "progress_pct": round((stage / TOTAL_STAGES) * 100),
            "message": message,
            "status": status,
        })

        await self._broadcast(analysis_id, payload)

    async def send_error(self, analysis_id: str, message: str) -> None:
        """Broadcast a terminal error event."""
        payload = json.dumps({
            "stage": 0,
            "total_stages": TOTAL_STAGES,
            "progress_pct": 0,
            "message": message,
            "status": "failed",
        })
        await self._broadcast(analysis_id, payload)

    async def _broadcast(self, analysis_id: str, payload: str) -> None:
        """Send payload to every live connection; prune dead sockets."""
        conns = self._connections.get(analysis_id, [])
        dead: List[WebSocket] = []

        for ws in list(conns):
            try:
                if ws.client_state == WebSocketState.CONNECTED:
                    await ws.send_text(payload)
                else:
                    dead.append(ws)
            except Exception as exc:
                logger.debug(f"WS send failed for {analysis_id}: {exc}")
                dead.append(ws)

        for ws in dead:
            self.disconnect(analysis_id, ws)


# Module-level singleton — imported by main.py and reused across requests
ws_manager = WebSocketManager()
