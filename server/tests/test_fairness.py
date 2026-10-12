import asyncio
import copy
import hashlib
import json
import sqlite3
from pathlib import Path

import db
import fairness
import pytest
from game.tiles import tile_to_str
from game.wall import Wall
from multiplayer import Match, Seat

VECTOR = json.loads((Path(__file__).parent / 'fixtures' / 'fairness_v1.json').read_text(encoding='utf-8'))


@pytest.fixture
def database(tmp_path, monkeypatch):
    monkeypatch.setattr(db, 'DB_PATH', tmp_path / 'fairness.sqlite3')
    db.init_db()
    monkeypatch.setenv('IMR_HAND_PAUSE_SECONDS', '0')


def seats():
    return [Seat(101 + seat, f'player{seat}').payload(seat) for seat in range(4)]


def test_database_connections_close_after_commit(database):
    with db._connect() as conn:
        conn.execute('INSERT INTO fairness_counts VALUES (1, 2)')
    with pytest.raises(sqlite3.ProgrammingError):
        conn.execute('SELECT 1')
    with db._connect() as reopened:
        assert reopened.execute('SELECT games_played FROM fairness_counts WHERE user_id = 1').fetchone()[0] == 2


def test_vector_and_actual_initial_hands():
    order = fairness.wall_order(VECTOR['secret'], VECTOR['context'])
    assert order == VECTOR['order']
    assert fairness.wall_hash(order) == VECTOR['wall_hash']
    wall = Wall(order=order)
    assert [[tile_to_str(tile) for tile in hand] for hand in wall.deal()] == VECTOR['hands']
    assert tile_to_str(wall.draw()) == VECTOR['dealer_draw']
    assert tile_to_str(wall.draw_supplement()) == VECTOR['wall'][-1]
    for field, value in [('match_id', 'different'), ('hand', 2), ('dealer', 3)]:
        context = {**VECTOR['context'], field: value}
        assert fairness.wall_order(VECTOR['secret'], context) != order
    context = copy.deepcopy(VECTOR['context'])
    context['players'][0]['games_played'] += 1
    assert fairness.wall_order(VECTOR['secret'], context) != order
    with pytest.raises(ValueError):
        Wall(order=[0] * 136)
    with pytest.raises(ValueError):
        fairness.wall_order('00', VECTOR['context'])


def test_rejection_sampling_consumes_the_next_value(monkeypatch):
    calls = []

    def digest(key, message, algorithm):
        calls.append(message)
        return (b'\xff' * 4 + bytes(28)) if len(calls) == 1 else bytes(32)

    monkeypatch.setattr(fairness.hmac, 'digest', digest)
    assert fairness.wall_order(VECTOR['secret'], VECTOR['context']) == list(range(1, 136)) + [0]
    assert calls[0][-4:] == bytes(4)
    assert calls[1][-4:] == (1).to_bytes(4, 'big')


def test_rotation_counts_and_interrupted_matches(database):
    state = fairness.public_keys()
    assert set(state['current']) == {'hash', 'created_at'}
    assert state['history'] == []
    secret, context = fairness.begin_match('match-1', seats())
    assert hashlib.sha256(bytes.fromhex(secret)).hexdigest() == state['current']['hash']
    assert all(p['games_played'] == 0 for p in context['players'])
    with pytest.raises(ValueError, match='still playing'):
        fairness.rotate_key()
    assert fairness.public_keys() == state
    with pytest.raises(sqlite3.IntegrityError):
        fairness.begin_match('match-1', seats())
    fairness.close_interrupted_matches()
    result = fairness.rotate_key()
    history = fairness.public_keys()['history']
    assert history[0]['secret'] == secret
    assert history[0]['hash'] == result['previous_hash']
    assert history[0]['retired_at'] >= history[0]['created_at']
    assert fairness.public_keys()['current']['hash'] == result['current_hash']
    _, next_context = fairness.begin_match('match-2', seats())
    assert all(p['games_played'] == 1 for p in next_context['players'])
    fairness.finish_match('match-2')
    fairness.rotate_key()
    with db._connect() as conn:
        assert conn.execute("SELECT status FROM fairness_matches WHERE match_id = 'match-1'").fetchone()[0] == 'interrupted'


def test_legacy_counts_are_preserved(database):
    db.save_match('old-game', 'room', 1, [], [], [{'user_id': db.create_user('legacy', 'long enough password')['id'],
                                                'seat': 0, 'score': 0, 'rank': 1}])
    _, context = fairness.begin_match('new-game', [Seat(1, 'legacy').payload(0)] + [Seat(bot='efficiency').payload(i) for i in range(1, 4)])
    assert context['players'][0]['games_played'] == 1
    assert all(p['user_id'] is None and p['games_played'] == 0 for p in context['players'][1:])


def test_match_announces_commitment_before_dealing_and_preserves_it_on_resume(database):
    broadcasts, sent = [], []
    with db._connect() as conn:
        conn.executemany('INSERT INTO users VALUES (?, ?, ?, ?)', [(101 + i, f'player{i}', 'unused', 0) for i in range(4)])

    async def send(uid, message):
        sent.append((uid, message))

    async def broadcast(users, message):
        broadcasts.append(message)

    async def run():
        match = Match('live-test', 'room', 2, [Seat(101 + i, f'player{i}') for i in range(4)], send, broadcast)
        await match.start()
        proof = broadcasts[0]['fairness']
        assert broadcasts[0]['type'] == 'match_started'
        assert broadcasts[1]['type'] == 'game_start'
        assert 'secret' not in json.dumps(broadcasts + sent)
        assert match._server_key not in json.dumps(broadcasts + sent)
        order = fairness.wall_order(match._server_key, proof)
        expected = [[tile_to_str(tile) for tile in hand] for hand in Wall(order=order).deal()]
        for seat in range(4):
            start = next(message for uid, message in sent if uid == 101 + seat and message['type'] == 'game_start')
            assert start['your_hand'] == expected[seat]
        await match.start()
        assert match.fairness == proof
        await match.resume_state(104)
        assert next(message for uid, message in reversed(sent) if message['type'] == 'match_snapshot')['fairness'] == proof
        await match._hand_complete({})
        assert match.fairness['hand'] == 2 and match.fairness['dealer'] == 1
        assert match.fairness['server_key_hash'] == proof['server_key_hash']
        assert match.fairness['wall_hash'] != proof['wall_hash']
        assert broadcasts[-3]['type'] == 'next_hand'
        match.game._cancel_timeout()
        await match._hand_complete({})
        fairness.rotate_key()

    asyncio.run(run())


def test_public_api_does_not_disclose_current_key(database):
    from fastapi.testclient import TestClient
    from app import app

    with TestClient(app) as client:
        response = client.get('/api/fairness')
        assert response.status_code == 200
        assert response.headers['cache-control'] == 'no-store'
        assert 'secret' not in response.json()['current']
        fairness.rotate_key()
        data = client.get('/api/fairness').json()
        assert 'secret' not in data['current']
        assert hashlib.sha256(bytes.fromhex(data['history'][0]['secret'])).hexdigest() == data['history'][0]['hash']
        assert client.get('/fairness.html?view=history').status_code == 200
        assert client.get('/fairness.html?view=verify').status_code == 200
