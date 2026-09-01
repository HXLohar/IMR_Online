import asyncio

import db
import pytest
from pydantic import ValidationError
from multiplayer import Lobby
from protocol.messages import parse_client_message


def test_password_sessions_and_replay_access(tmp_path, monkeypatch):
    monkeypatch.setattr(db, 'DB_PATH', tmp_path / 'imr.sqlite3')
    db.init_db()
    user = db.create_user('alice', 'correct horse battery')
    assert db.authenticate('alice', 'wrong') is None
    assert db.authenticate('alice', 'correct horse battery')['id'] == user['id']
    token = db.create_session(user['id'])
    assert db.user_from_session(token)['username'] == 'alice'

    db.save_match('m1', 'matchmaking', 1, [{'type': 'discarded'}], [], [
        {'user_id': user['id'], 'seat': 0, 'score': 100, 'rank': 1},
    ])
    assert db.replay_for_user('m1', user['id'])['replay'][0]['type'] == 'discarded'
    assert db.replays_for_user(user['id'])[0]['mode'] == 'matchmaking'
    assert db.replay_for_user('m1', 999) is None


def test_lobby_separates_queue_lengths_and_allows_private_rooms():
    sent = []

    async def send(user_id, msg):
        sent.append((user_id, msg))

    async def broadcast(user_ids, msg):
        sent.append((user_ids, msg))

    async def run():
        lobby = Lobby(send, broadcast)
        room = await lobby.create_room(1, 'alice', 4, 'private')
        assert room.code
        assert room.visibility == 'private'
        assert 10_000_000 <= int(room.id) <= 99_999_999
        await lobby.join_room(2, 'bob', code=room.code)
        await lobby.set_config(1, 4, {'2': 'efficiency', '3': 'auto_call'})
        assert len(room.users()) == 2

        for user_id in range(10, 13):
            await lobby.queue(user_id, f'u{user_id}', 1)
        assert not lobby.matches
        match = await lobby.queue(13, 'u13', 1)
        assert match is not None
        assert match.length == 1
        assert not lobby.queues[4]

    asyncio.run(run())


def test_practice_mode_and_internal_test_room():
    sent = []

    async def send(user_id, msg):
        sent.append((user_id, msg))

    async def broadcast(user_ids, msg):
        sent.append((user_ids, msg))

    async def run():
        lobby = Lobby(send, broadcast)
        test_room = lobby.rooms['63549000']
        assert test_room.visibility == 'private'
        assert [seat.username for seat in test_room.seats] == ['', 'Bot_A', 'Bot_B', '']
        assert all(seat.is_bot for seat in test_room.seats[1:3])
        assert all(not seat.is_bot for seat in (test_room.seats[0], test_room.seats[3]))

        match = await lobby.start_practice(99, 'solo')
        assert match.mode == 'practice'
        assert [seat.username for seat in match.seats] == ['solo', 'Bot_A', 'Bot_B', 'Bot_C']
        assert all(seat.is_bot for seat in match.seats[1:])

    asyncio.run(run())


def test_http_auth_round_trip(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app import app

    monkeypatch.setattr(db, 'DB_PATH', tmp_path / 'http.sqlite3')
    with TestClient(app) as client:
        assert client.get('/healthz').json() == {'status': 'ok'}
        assert client.get('/').status_code == 200
        assert client.get('/auth-hero.png').status_code == 200
        assert client.get('/lobby-bg.png').status_code == 200
        registered = client.post('/api/auth/register', json={'username': 'web_user', 'password': 'long enough password'})
        assert registered.status_code == 200
        assert client.get('/api/me').status_code == 200
        assert client.post('/api/auth/login', json={'username': 'web_user', 'password': 'bad password'}).status_code == 401
        assert client.post('/api/auth/logout').status_code == 200
        assert client.get('/api/me').status_code == 401


def test_protocol_validates_lobby_and_game_messages():
    assert parse_client_message({'type': 'create_room', 'length': 4, 'visibility': 'private'}).length == 4
    assert parse_client_message({'type': 'practice_start'}).type == 'practice_start'
    assert parse_client_message({'type': 'discard', 'tile': '1b'}).tile == '1b'
    assert parse_client_message({'type': 'set_room_config', 'bots': {'1': 'efficiency'}}).bots['1'] == 'efficiency'
    with pytest.raises(ValidationError):
        parse_client_message({'type': 'create_room', 'length': 2})
    with pytest.raises(ValidationError):
        parse_client_message({'type': 'create_room', 'visibility': 'public'})
    with pytest.raises(ValidationError):
        parse_client_message({'type': 'join_room'})
    with pytest.raises(ValidationError):
        parse_client_message({'type': 'claim', 'claim': 'not-a-claim'})


def test_room_state_tracks_connection_and_owner_close():
    sent = []

    async def send(user_id, msg):
        sent.append((user_id, msg))

    async def broadcast(user_ids, msg):
        sent.append((user_ids, msg))

    async def run():
        lobby = Lobby(send, broadcast)
        await lobby.connect_user(1)
        room = await lobby.create_room(1, 'alice', 1, 'public')
        await lobby.connect_user(2)
        await lobby.join_room(2, 'bob', room_id=room.id)
        assert [seat['connected'] for seat in room.view()['seats'][:2]] == [True, True]

        await lobby.disconnect_user(2)
        assert room.view()['seats'][1]['connected'] is False
        await lobby.connect_user(2)
        assert room.view()['seats'][1]['connected'] is True

        with pytest.raises(ValueError):
            await lobby.set_config(2, 4, {})
        with pytest.raises(ValueError):
            await lobby.start_room(2)

        await lobby.leave_room(1)
        assert room.id not in lobby.rooms
        assert 1 not in lobby.user_room and 2 not in lobby.user_room
        assert any(uid == 2 and msg['type'] == 'room_closed' for uid, msg in sent if isinstance(uid, int))

    asyncio.run(run())
