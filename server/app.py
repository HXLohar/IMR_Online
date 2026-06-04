"""
FastAPI entry point + WebSocket endpoint for IMR Online.

Usage:
  uvicorn app:app --reload --port 8000
"""
from __future__ import annotations
import asyncio
import json
import logging

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import ValidationError

from game.room import Room
from protocol.messages import parse_client_message

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title='IMR Online Server')

app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_methods=['*'],
    allow_headers=['*'],
)

# ---------------------------------------------------------------------------
# Single-room singleton for Step 1
# ---------------------------------------------------------------------------

_room: Room | None = None
_human_ws: WebSocket | None = None


async def _send_to_seat(seat: int, msg: dict) -> None:
    """Send a message to a specific seat (only seat 0 is human in Step 1)."""
    if seat == 0 and _human_ws is not None:
        try:
            await _human_ws.send_json(msg)
        except Exception:
            pass


async def _broadcast(msg: dict) -> None:
    """Broadcast a message to all human clients."""
    if _human_ws is not None:
        try:
            await _human_ws.send_json(msg)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# WebSocket endpoint
# ---------------------------------------------------------------------------

@app.websocket('/ws')
async def websocket_endpoint(ws: WebSocket) -> None:
    global _room, _human_ws

    await ws.accept()
    _human_ws = ws
    seat = 0  # human always seat 0 in Step 1

    # Recreate room for each connection
    _room = Room(send_fn=_send_to_seat, broadcast_fn=_broadcast)

    logger.info('Client connected')

    try:
        # Send joined confirmation
        await ws.send_json({
            'type': 'joined',
            'seat': seat,
            'players': [
                {'seat': p.seat, 'name': p.name, 'is_bot': p.is_bot}
                for p in _room.players
            ],
        })

        # Wait for join message
        raw = await ws.receive_text()
        try:
            data = json.loads(raw)
            if data.get('type') == 'join':
                name = data.get('name', 'Guest')
                _room.set_human_name(name)
        except (json.JSONDecodeError, ValueError):
            pass

        # Start the game
        asyncio.create_task(_room.start())

        # Receive player actions
        while True:
            raw = await ws.receive_text()
            try:
                data = json.loads(raw)
                msg = parse_client_message(data)
                await _room.handle_message(seat, msg.model_dump())
            except (json.JSONDecodeError, ValidationError) as e:
                await ws.send_json({'type': 'error', 'message': str(e)})
            except Exception as e:
                logger.exception('Error handling message')
                await ws.send_json({'type': 'error', 'message': str(e)})

    except WebSocketDisconnect:
        logger.info('Client disconnected')
    finally:
        _human_ws = None
