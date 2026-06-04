"""
Room: manages players, bot setup, and the GameState lifecycle.
Step 1: single room, 1 human + 3 bots.
"""
from __future__ import annotations
import asyncio
from typing import Callable, Awaitable

from game.player_state import PlayerState
from game.fsm import GameState
from bots.discard_only_bot import DiscardOnlyBot
from bots.auto_call_bot import AutoCallBot


def _make_players() -> list[PlayerState]:
    """Create 4 seats: seat 0 = human, seats 1-3 = bots."""
    ps = [PlayerState(seat=0, name='Guest', is_bot=False)]

    bot_types = [AutoCallBot(), DiscardOnlyBot(), DiscardOnlyBot()]
    bot_names = ['Bot-A', 'Bot-B', 'Bot-C']

    for i, (bot, name) in enumerate(zip(bot_types, bot_names), start=1):
        p = PlayerState(seat=i, name=name, is_bot=True)
        p._bot = bot   # attach bot instance
        ps.append(p)

    return ps


class Room:
    def __init__(
        self,
        send_fn: Callable[[int, dict], Awaitable[None]],
        broadcast_fn: Callable[[dict], Awaitable[None]],
        seed: int | None = None,
    ):
        self.players = _make_players()
        self.game = GameState(
            players=self.players,
            send_fn=send_fn,
            broadcast_fn=broadcast_fn,
            seed=seed,
        )
        self._started = False

    def set_human_name(self, name: str) -> None:
        self.players[0].name = name

    async def start(self) -> None:
        if not self._started:
            self._started = True
            await self.game.start()

    async def handle_message(self, seat: int, msg: dict) -> None:
        t = msg.get('type')
        if t == 'discard':
            action = {'action': 'discard', 'tile': msg['tile'], 'face_down': msg.get('face_down', False)}
            await self.game.handle_player_action(seat, action)
        elif t == 'self_action':
            await self.game.handle_player_action(seat, msg)
        elif t == 'claim':
            await self.game.handle_claim(seat, msg)
        else:
            pass  # unknown
