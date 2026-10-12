"""Versioned, reproducible walls and persistent server-key commitments."""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time

import db

# shortcut: metadata is predictable; add post-commitment entropy for bias-resistant generation.
VERSION = 'imr-hmac-sha256-v1'


def _current_key(conn) -> dict:
    row = conn.execute('SELECT * FROM fairness_keys WHERE retired_at IS NULL').fetchone()
    if row is None:
        secret = secrets.token_bytes(32)
        key = {'hash': hashlib.sha256(secret).hexdigest(), 'secret': secret.hex(), 'created_at': time.time()}
        conn.execute('INSERT INTO fairness_keys VALUES (?, ?, ?, NULL)',
                     (key['hash'], key['secret'], key['created_at']))
        return key
    return dict(row)


def public_keys() -> dict:
    with db._connect() as conn:
        conn.execute('BEGIN IMMEDIATE')
        key = _current_key(conn)
        history = [dict(row) for row in conn.execute(
            'SELECT hash, secret, created_at, retired_at FROM fairness_keys '
            'WHERE retired_at IS NOT NULL ORDER BY retired_at DESC')]
    return {'current': {'hash': key['hash'], 'created_at': key['created_at']}, 'history': history}


def rotate_key() -> dict:
    with db._connect() as conn:
        conn.execute('BEGIN IMMEDIATE')
        old = _current_key(conn)
        if conn.execute("SELECT 1 FROM fairness_matches WHERE status = 'playing' LIMIT 1").fetchone():
            raise ValueError('Cannot rotate: matches are still playing. Finish them first; restart the server to close interrupted matches.')
        conn.execute('UPDATE fairness_keys SET retired_at = ? WHERE hash = ?', (time.time(), old['hash']))
        new = _current_key(conn)
    return {'previous_hash': old['hash'], 'current_hash': new['hash']}


def begin_match(match_id: str, seats: list[dict]) -> tuple[str, dict]:
    """Reserve pre-match counts and the key atomically, before any cards are sent."""
    with db._connect() as conn:
        conn.execute('BEGIN IMMEDIATE')
        key = _current_key(conn)
        players = []
        for slot in seats:
            uid = slot['user_id']
            count = 0
            if uid is not None:
                row = conn.execute('SELECT games_played FROM fairness_counts WHERE user_id = ?', (uid,)).fetchone()
                if row is None:
                    # Preserve completed games from before this feature was installed.
                    count = conn.execute('SELECT COUNT(*) FROM match_players WHERE user_id = ?', (uid,)).fetchone()[0]
                else:
                    count = row['games_played']
                conn.execute('INSERT INTO fairness_counts VALUES (?, ?) '
                             'ON CONFLICT(user_id) DO UPDATE SET games_played = excluded.games_played', (uid, count + 1))
            players.append({'seat': slot['seat'], 'user_id': uid, 'games_played': count, 'bot': slot['bot']})
        context = {'version': VERSION, 'match_id': match_id, 'hand': 1, 'dealer': 0, 'players': players}
        conn.execute('INSERT INTO fairness_matches VALUES (?, ?, ?, ?, ?, NULL)',
                     (match_id, key['hash'], json.dumps(context), 'playing', time.time()))
    return key['secret'], {**context, 'server_key_hash': key['hash']}


def finish_match(match_id: str, status: str = 'finished') -> None:
    with db._connect() as conn:
        conn.execute("UPDATE fairness_matches SET status = ?, finished_at = ? WHERE match_id = ? AND status = 'playing'",
                     (status, time.time(), match_id))


def close_interrupted_matches() -> None:
    # The application uses one server process and cannot resume games after restart.
    with db._connect() as conn:
        conn.execute("UPDATE fairness_matches SET status = 'interrupted', finished_at = ? WHERE status = 'playing'", (time.time(),))


def wall_order(secret: str, context: dict) -> list[int]:
    players = [[p['seat'], p['user_id'], p['games_played'], p['bot']] for p in context['players']]
    data = [context['version'], context['match_id'], context['hand'], context['dealer'], players]
    message = json.dumps(data, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    key = bytes.fromhex(secret)
    if len(key) != 32 or context['version'] != VERSION:
        raise ValueError('Invalid server key or fairness version')
    counter = 0
    block = b''
    offset = 32

    def uint32() -> int:
        nonlocal counter, block, offset
        if offset == 32:
            block = hmac.digest(key, message + b'\0' + counter.to_bytes(4, 'big'), 'sha256')
            counter += 1
            offset = 0
        value = int.from_bytes(block[offset:offset + 4], 'big')
        offset += 4
        return value

    order = list(range(136))
    for i in range(135, 0, -1):
        size = i + 1
        limit = (2**32 // size) * size
        x = uint32()
        while x >= limit:
            x = uint32()
        j = x % size
        order[i], order[j] = order[j], order[i]
    return order


def wall_hash(order: list[int]) -> str:
    return hashlib.sha256(bytes(order)).hexdigest()
