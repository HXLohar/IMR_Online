"""FastAPI entry point for authenticated lobby and multiplayer games."""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from db import authenticate, create_session, create_user, delete_session, init_db, profile, replay_for_user, replays_for_user, user_from_session
from multiplayer import Lobby
from protocol.messages import parse_client_message

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title='IMR Online Server')
app.add_middleware(CORSMiddleware, allow_origins=['http://localhost:5173', 'http://127.0.0.1:5173'], allow_credentials=True,
                   allow_methods=['*'], allow_headers=['*'])

connections: dict[int, WebSocket] = {}


async def send_user(user_id: int, msg: dict) -> None:
    ws = connections.get(user_id)
    if ws is not None:
        try:
            await ws.send_json(msg)
        except Exception:
            connections.pop(user_id, None)


async def broadcast_users(user_ids: list[int], msg: dict) -> None:
    targets = list(connections) if not user_ids else user_ids
    await asyncio.gather(*(send_user(uid, msg) for uid in targets), return_exceptions=True)


lobby = Lobby(send_user, broadcast_users)


class Credentials(BaseModel):
    username: str = Field(min_length=3, max_length=24, pattern=r'^[A-Za-z0-9_\-]+$')
    password: str = Field(min_length=8, max_length=128)


def request_user(request: Request) -> dict:
    user = user_from_session(request.cookies.get('imr_session'))
    if not user:
        raise HTTPException(401, 'Login required')
    return user


@app.on_event('startup')
async def startup() -> None:
    init_db()


@app.post('/api/auth/register')
async def register(body: Credentials):
    try:
        user = create_user(body.username, body.password)
    except Exception as exc:
        if 'UNIQUE' in str(exc).upper():
            raise HTTPException(409, 'Username already exists')
        raise
    token = create_session(user['id'])
    response = {'user': user}
    from fastapi.responses import JSONResponse
    out = JSONResponse(response)
    out.set_cookie('imr_session', token, httponly=True, samesite='lax', max_age=30 * 86400)
    return out


@app.post('/api/auth/login')
async def login(body: Credentials):
    user = authenticate(body.username, body.password)
    if not user:
        raise HTTPException(401, 'Invalid username or password')
    token = create_session(user['id'])
    from fastapi.responses import JSONResponse
    out = JSONResponse({'user': user})
    out.set_cookie('imr_session', token, httponly=True, samesite='lax', max_age=30 * 86400)
    return out


@app.post('/api/auth/logout')
async def logout(request: Request):
    token = request.cookies.get('imr_session')
    if token:
        delete_session(token)
    from fastapi.responses import JSONResponse
    out = JSONResponse({'ok': True})
    out.delete_cookie('imr_session')
    return out


@app.get('/api/me')
async def me(request: Request):
    user = request_user(request)
    return {'user': user, 'profile': profile(user['id'])}


@app.get('/api/profile')
async def get_profile(request: Request):
    return profile(request_user(request)['id'])


@app.get('/api/replays/{match_id}')
async def get_replay(match_id: str, request: Request):
    replay = replay_for_user(match_id, request_user(request)['id'])
    if not replay:
        raise HTTPException(404, 'Replay not found')
    return replay


@app.get('/api/replays')
async def list_replays(request: Request):
    return {'replays': replays_for_user(request_user(request)['id'])}


async def room_state(room) -> None:
    await lobby.notify_room(room)


async def handle_ws_message(user: dict, msg: dict) -> None:
    msg = parse_client_message(msg).model_dump(exclude_none=True)
    user_id = user['id']
    kind = msg.get('type')
    if kind == 'create_room':
        room = await lobby.create_room(user_id, user['username'], int(msg.get('length', 1)), msg.get('visibility', 'public'))
        await room_state(room)
    elif kind == 'join_room':
        room = await lobby.join_room(user_id, user['username'], msg.get('room_id'), msg.get('code'))
        await room_state(room)
    elif kind == 'set_room_config':
        room = await lobby.set_config(user_id, int(msg.get('length', 1)), msg.get('bots', {}))
        await room_state(room)
    elif kind == 'start_room':
        await lobby.start_room(user_id)
    elif kind == 'queue_join':
        await lobby.queue(user_id, user['username'], int(msg.get('length', 1)))
    elif kind == 'queue_leave':
        length = int(msg.get('length', 1))
        await lobby.leave_queue(user_id, length)
    elif kind == 'leave_room':
        await lobby.leave_room(user_id)
    elif kind == 'discard':
        match = lobby.matches.get(lobby.user_match.get(user_id, ''))
        if match:
            await match.action(user_id, {'action': 'discard', 'tile': msg.get('tile'),
                                         'face_down': msg.get('face_down', False),
                                         'turn_id': msg.get('turn_id')})
    elif kind == 'self_action':
        match = lobby.matches.get(lobby.user_match.get(user_id, ''))
        if match:
            await match.action(user_id, msg)
    elif kind == 'claim':
        match = lobby.matches.get(lobby.user_match.get(user_id, ''))
        if match:
            await match.claim(user_id, msg)
    elif kind == 'resume':
        match = lobby.matches.get(lobby.user_match.get(user_id, ''))
        if match:
            await match.resume_state(user_id)
        else:
            await send_user(user_id, {'type': 'match_lost', 'reason': 'server_restart'})
    else:
        await send_user(user_id, {'type': 'error', 'message': f'Unknown message type: {kind}'})


@app.websocket('/ws')
async def websocket_endpoint(ws: WebSocket) -> None:
    user = user_from_session(ws.cookies.get('imr_session'))
    if not user:
        await ws.close(code=4401, reason='Login required')
        return
    await ws.accept()
    connections[user['id']] = ws
    try:
        await send_user(user['id'], {'type': 'session', 'user': user, 'profile': profile(user['id'])})
        await send_user(user['id'], lobby.snapshot())
        await lobby.connect_user(user['id'])
        existing_match = lobby.matches.get(lobby.user_match.get(user['id'], ''))
        if existing_match:
            await existing_match.resume_state(user['id'])
        while True:
            data = json.loads(await ws.receive_text())
            try:
                await handle_ws_message(user, data)
            except (ValueError, TypeError) as exc:
                await send_user(user['id'], {'type': 'error', 'message': str(exc)})
            except Exception:
                logger.exception('Error handling websocket message')
                await send_user(user['id'], {'type': 'error', 'message': 'Request failed'})
    except (WebSocketDisconnect, json.JSONDecodeError):
        pass
    finally:
        is_current = connections.get(user['id']) is ws
        if is_current:
            connections.pop(user['id'], None)
            existing_match = lobby.matches.get(lobby.user_match.get(user['id'], ''))
            if existing_match:
                await existing_match.disconnect_user(user['id'])
            else:
                await lobby.disconnect_user(user['id'])


dist_index = Path(__file__).parent.parent / 'client' / 'dist' / 'index.html'
if dist_index.exists():
    app.mount('/assets', StaticFiles(directory=dist_index.parent / 'assets'), name='assets')
    app.mount('/tiles', StaticFiles(directory=dist_index.parent / 'tiles'), name='tiles')

    @app.get('/')
    async def index():
        return FileResponse(dist_index)
