"""Run ten deterministic bot matches without network or browser dependencies.

Usage from the repository root:
    .venv\\Scripts\\python.exe server/tests/smoke_10_games.py
"""
from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path

os.environ.setdefault('IMR_WIN_THRESHOLD_MODE', 'test')
os.environ.setdefault('IMR_HAND_PAUSE_SECONDS', '0')
os.environ.setdefault('IMR_BOT_DELAY_SECONDS', '0')
os.environ.setdefault('IMR_DB_PATH', str(Path(tempfile.gettempdir()) / 'imr-online-smoke.sqlite3'))

from db import init_db
from multiplayer import Match, Seat


async def noop(*args) -> None:
    return None


async def run() -> None:
    init_db()
    for index in range(10):
        seed = 0x1A2B3C4D + index
        seats = [Seat(bot='efficiency') for _ in range(4)]
        match = Match(f'smoke-{index}', 'smoke', 1, seats, noop, noop)
        match.seed = seed
        match.game._seed = seed
        await match.start()
        assert match.finished, f'seed {seed} did not finish (state={match.game.state.name}, wall={match.game.wall.remaining() if match.game.wall else None}, current={match.game.current_seat}, events={len(match.replay)}, tail={match.replay[-5:]})'
        print(f'OK seed={seed} replay_events={len(match.replay)}')

    sent = []

    async def capture(user_id, message) -> None:
        sent.append((user_id, message))

    seats = [Seat(100 + seat, f'user{seat}') for seat in range(4)]
    match = Match('smoke-resume', 'smoke', 1, seats, capture, noop)
    match.seed = 0x5EED
    match.game._seed = match.seed
    await match.start()
    live_turn_id = match.game.turn_id
    await match.game.timeout('turn', live_turn_id + 1)
    assert match.game.state.name == 'PLAYER_TURN'
    await match.disconnect_user(103)
    await match.reconnect_user(103)
    await match.resume_state(103)
    snapshot = next(message for user_id, message in reversed(sent)
                     if user_id == 103 and message['type'] == 'match_snapshot')
    assert snapshot['your_seat'] == 3
    assert snapshot['turn_id'] == match.game.turn_id
    assert all('hand' not in player for player in snapshot['players'] if player['seat'] != 3)
    print('OK reconnect snapshot seat=3 stale-timeout-safe')


if __name__ == '__main__':
    asyncio.run(run())
