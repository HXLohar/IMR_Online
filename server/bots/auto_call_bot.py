"""
Bot ②: Auto-call (自動鳴牌).
Calls whenever legally possible (kong > pong > chow), but never wins.
When needing to discard (after call or on own turn), picks randomly.
"""
import random
from bots.base import Bot
from game.legal import can_chow
from scoring.parsing import parse_tiles_english


class AutoCallBot(Bot):
    def __init__(self, seed: int | None = None):
        self._rng = random.Random(seed)

    def decide_turn(self, view: dict) -> dict:
        hand = view.get('hand', [])
        # Randomly discard one tile (excluding calling/win logic)
        if not hand:
            return {'type': 'discard', 'action': 'discard', 'tile': None, 'face_down': False}
        tile = self._rng.choice(hand)
        return {'type': 'discard', 'action': 'discard', 'tile': tile, 'face_down': False}

    def decide_claim(self, view: dict, options: list[str]) -> dict:
        # Priority: kong > pong > chow; never win
        if 'kong' in options:
            return {'claim': 'kong'}
        if 'pong' in options:
            return {'claim': 'pong'}
        if 'chow' in options:
            # Pick first available chow (FSM will resolve which tiles)
            return {'claim': 'chow', 'tiles': []}
        return {'claim': 'skip'}
