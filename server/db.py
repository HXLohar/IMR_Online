"""Small SQLite persistence layer for accounts, sessions, matches and replays."""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import sqlite3
import time
from pathlib import Path

DB_PATH = Path(os.getenv('IMR_DB_PATH', Path(__file__).with_name('imr.sqlite3')))


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    return conn


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _connect() as conn:
        conn.executescript('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL COLLATE NOCASE UNIQUE,
            password_hash TEXT NOT NULL,
            created_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sessions (
            token_hash TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            expires_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS matches (
            id TEXT PRIMARY KEY,
            mode TEXT NOT NULL,
            length INTEGER NOT NULL,
            created_at REAL NOT NULL,
            finished_at REAL,
            replay_json TEXT NOT NULL,
            results_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS match_players (
            match_id TEXT NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
            user_id INTEGER NOT NULL REFERENCES users(id),
            seat INTEGER NOT NULL,
            score INTEGER NOT NULL,
            rank INTEGER NOT NULL,
            PRIMARY KEY (match_id, user_id)
        );
        CREATE INDEX IF NOT EXISTS idx_match_players_user ON match_players(user_id);
        ''')


def _password_hash(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
    return 'scrypt$' + base64.urlsafe_b64encode(salt).decode() + '$' + base64.urlsafe_b64encode(digest).decode()


def _password_matches(password: str, encoded: str) -> bool:
    try:
        _, salt_s, digest_s = encoded.split('$', 2)
        salt = base64.urlsafe_b64decode(salt_s.encode())
        expected = base64.urlsafe_b64decode(digest_s.encode())
        actual = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def create_user(username: str, password: str) -> dict:
    with _connect() as conn:
        cur = conn.execute(
            'INSERT INTO users(username, password_hash, created_at) VALUES (?, ?, ?)',
            (username, _password_hash(password), time.time()),
        )
        return {'id': cur.lastrowid, 'username': username}


def authenticate(username: str, password: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute('SELECT id, username, password_hash FROM users WHERE username = ?', (username,)).fetchone()
    if row is None or not _password_matches(password, row['password_hash']):
        return None
    return {'id': row['id'], 'username': row['username']}


def create_session(user_id: int, days: int = 30) -> str:
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    with _connect() as conn:
        conn.execute('DELETE FROM sessions WHERE expires_at < ?', (time.time(),))
        conn.execute('INSERT INTO sessions(token_hash, user_id, expires_at) VALUES (?, ?, ?)',
                     (token_hash, user_id, time.time() + days * 86400))
    return token


def delete_session(token: str) -> None:
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    with _connect() as conn:
        conn.execute('DELETE FROM sessions WHERE token_hash = ?', (token_hash,))


def user_from_session(token: str | None) -> dict | None:
    if not token:
        return None
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    with _connect() as conn:
        row = conn.execute('''
            SELECT u.id, u.username FROM sessions s JOIN users u ON u.id = s.user_id
            WHERE s.token_hash = ? AND s.expires_at > ?
        ''', (token_hash, time.time())).fetchone()
    return dict(row) if row else None


def save_match(match_id: str, mode: str, length: int, replay: list[dict], results: list[dict], players: list[dict]) -> None:
    import json
    with _connect() as conn:
        conn.execute('INSERT OR REPLACE INTO matches VALUES (?, ?, ?, ?, ?, ?, ?)',
                     (match_id, mode, length, time.time(), time.time(), json.dumps(replay), json.dumps(results)))
        conn.executemany(
            'INSERT OR REPLACE INTO match_players(match_id, user_id, seat, score, rank) VALUES (?, ?, ?, ?, ?)',
            [(match_id, p['user_id'], p['seat'], p['score'], p['rank']) for p in players],
        )


def profile(user_id: int) -> dict:
    with _connect() as conn:
        rows = conn.execute('''
            SELECT mp.score, mp.rank, m.id, m.mode, m.length, m.finished_at
            FROM match_players mp JOIN matches m ON m.id = mp.match_id
            WHERE mp.user_id = ? AND m.mode = 'matchmaking' ORDER BY m.finished_at DESC
        ''', (user_id,)).fetchall()
    games = len(rows)
    wins = sum(1 for r in rows if r['rank'] == 1 and sum(1 for x in rows if x['id'] == r['id'] and x['rank'] == 1) == 1)
    draws = sum(1 for r in rows if r['rank'] == 1 and sum(1 for x in rows if x['id'] == r['id'] and x['rank'] == 1) > 1)
    return {
        'games': games, 'wins': wins, 'draws': draws, 'losses': games - wins - draws,
        'win_rate': round(wins / games, 4) if games else 0,
        'average_score': round(sum(r['score'] for r in rows) / games, 2) if games else 0,
        'recent': [dict(r) for r in rows[:20]],
    }


def replay_for_user(match_id: str, user_id: int) -> dict | None:
    import json
    with _connect() as conn:
        allowed = conn.execute('SELECT 1 FROM match_players WHERE match_id = ? AND user_id = ?', (match_id, user_id)).fetchone()
        row = conn.execute('SELECT * FROM matches WHERE id = ?', (match_id,)).fetchone()
    if not allowed or not row:
        return None
    return {**dict(row), 'replay': json.loads(row['replay_json']), 'results': json.loads(row['results_json'])}


def replays_for_user(user_id: int) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute('''
            SELECT m.id, m.mode, m.length, m.finished_at, mp.score, mp.rank
            FROM match_players mp JOIN matches m ON m.id = mp.match_id
            WHERE mp.user_id = ? ORDER BY m.finished_at DESC LIMIT 50
        ''', (user_id,)).fetchall()
    return [dict(row) for row in rows]
