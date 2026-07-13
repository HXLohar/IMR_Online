"""
Bot ②: Auto-call (自動鳴牌).
Calls whenever legally possible (direct quad > triplet > straight), but never wins.
When needing to discard (after call or on own turn), picks randomly.
"""
import random
from bots.base import Bot
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
        # Priority: direct quad > triplet > straight; never win
        if 'direct_quad_call' in options:
            return {'claim': 'direct_quad_call'}
        if 'triplet_call' in options:
            return {'claim': 'triplet_call'}
        if 'straight_call' in options:
            # Pick first available straight call (FSM will resolve which tiles)
            return {'claim': 'straight_call', 'tiles': []}
        return {'claim': 'skip'}
