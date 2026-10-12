from contextlib import ExitStack

import db
import app as app_module
from fastapi.testclient import TestClient
from multiplayer import Lobby


def test_four_websocket_players_start_a_match(tmp_path, monkeypatch):
    monkeypatch.setattr(db, 'DB_PATH', tmp_path / 'ws.sqlite3')
    for match in app_module.lobby.matches.values():
        for task in match._offline_tasks.values():
            task.cancel()
    app_module.connections.clear()
    app_module.lobby = Lobby(app_module.send_user, app_module.broadcast_users)

    with ExitStack() as stack:
        # One server event loop, with four separately authenticated connections.
        client = stack.enter_context(TestClient(app_module.app))
        clients = [client] * 4
        sockets = []
        for index, client in enumerate(clients):
            registered = client.post('/api/auth/register', json={
                'username': f'ws_user_{index}',
                'password': 'long enough password',
            })
            assert registered.status_code == 200
            socket = stack.enter_context(client.websocket_connect('/ws'))
            sockets.append(socket)
            assert socket.receive_json()['type'] == 'session'
            assert socket.receive_json()['type'] == 'lobby_state'

        for socket in sockets[:3]:
            socket.send_json({'type': 'queue_join', 'length': 1})
            assert socket.receive_json()['type'] == 'queue_joined'

        sockets[3].send_json({'type': 'queue_join', 'length': 1})
        started = [socket.receive_json() for socket in sockets]
        assert all(message['type'] == 'match_started' for message in started)
        assert {player['seat'] for player in started[0]['players']} == {0, 1, 2, 3}
        assert all(message['fairness'] == started[0]['fairness'] for message in started)
        assert len(started[0]['fairness']['wall_hash']) == 64
        assert all(socket.receive_json()['type'] == 'game_start' for socket in sockets)

    for match in app_module.lobby.matches.values():
        for task in match._offline_tasks.values():
            task.cancel()
    app_module.connections.clear()
    app_module.lobby = Lobby(app_module.send_user, app_module.broadcast_users)
