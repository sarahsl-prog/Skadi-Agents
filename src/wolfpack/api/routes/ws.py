"""WebSocket endpoint for real-time case updates.

Subscribes to NATS ``hunt.status.*`` and pushes updates to connected
analyst clients.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from wolfpack.api.auth import _verify_token

router = APIRouter()


@router.websocket("/cases/{case_id}")
async def case_websocket(websocket: WebSocket, case_id: str) -> None:
    """WebSocket for real-time case status updates.

    After connecting, the client must send an auth message with
    ``{"type": "auth", "token": "..."}`` within 5 seconds.
    """
    await websocket.accept()

    # Simple auth handshake with timeout
    try:
        auth_msg_raw = await asyncio.wait_for(websocket.receive_text(), timeout=5.0)
        auth_msg: dict[str, Any] = json.loads(auth_msg_raw)
        if auth_msg.get("type") != "auth":
            await websocket.close(code=1008, reason="Auth required")
            return
        # Validate token using the same logic as HTTP routes
        await _verify_token(auth_msg.get("token"))
    except TimeoutError:
        await websocket.close(code=1008, reason="Auth timeout")
        return
    except (json.JSONDecodeError, KeyError, WebSocketDisconnect):
        await websocket.close(code=1008, reason="Auth required")
        return
    except Exception:
        await websocket.close(code=1008, reason="Invalid token")
        return

    await websocket.send_text(json.dumps({"type": "connected", "case_id": case_id}))

    # Keep connection alive with heartbeat and push synthetic updates.
    # In a full implementation this would subscribe to NATS and
    # forward messages. For V1 we send a heartbeat every 30s.
    heartbeat_task: asyncio.Task[Any] | None = None

    async def _heartbeat() -> None:
        while True:
            await asyncio.sleep(30.0)
            try:
                await websocket.send_text(json.dumps({"type": "heartbeat"}))
            except Exception:
                break

    heartbeat_task = asyncio.create_task(_heartbeat())
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
    finally:
        if heartbeat_task is not None:
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass
