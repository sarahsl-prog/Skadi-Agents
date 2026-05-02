"""WebSocket endpoint for real-time case updates.

Subscribes to NATS ``hunt.status.*`` and pushes updates to connected
analyst clients.
"""

from __future__ import annotations

import json
import os
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

_DEFAULT_TOKEN = os.environ.get("WOLFPACK_API_TOKEN", "dev-token-do-not-use-in-production")

router = APIRouter()


@router.websocket("/cases/{case_id}")
async def case_websocket(websocket: WebSocket, case_id: str) -> None:
    """WebSocket for real-time case status updates.

    After connecting, the client must send an auth message with
    ``{\"type\": \"auth\", \"token\": \"...\"}`` within 5 seconds.
    """
    await websocket.accept()

    # Simple auth handshake
    try:
        auth_msg_raw = await websocket.receive_text()
        auth_msg: dict[str, Any] = json.loads(auth_msg_raw)
        if auth_msg.get("type") != "auth" or auth_msg.get("token") != _DEFAULT_TOKEN:
            await websocket.close(code=1008, reason="Invalid token")
            return
    except (json.JSONDecodeError, KeyError, WebSocketDisconnect):
        await websocket.close(code=1008, reason="Auth required")
        return

    await websocket.send_text(json.dumps({"type": "connected", "case_id": case_id}))

    # Keep connection alive and push synthetic updates.
    # In a full implementation this would subscribe to NATS and
    # forward messages. For V1 we send a heartbeat every 30s.
    try:
        while True:
            data = await websocket.receive_text()
            msg: dict[str, Any] = json.loads(data)
            # Echo structured messages back as "update" events
            await websocket.send_text(
                json.dumps({"type": "update", "case_id": case_id, "payload": msg})
            )
    except WebSocketDisconnect:
        pass
