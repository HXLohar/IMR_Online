"""
Bot ①: Pure discard (摸切).
Never calls chow/pong/kong. Never wins. Always discards the last drawn tile.
"""
from bots.base import Bot


class DiscardOnlyBot(Bot):
    def decide_turn(self, view: dict) -> dict:
        hand = view.get('hand', [])
        # Always discard the most recently drawn tile (last in hand list)
        tile = hand[-1] if hand else None
        return {'type': 'discard', 'action': 'discard', 'tile': tile, 'face_down': False}

    def decide_claim(self, view: dict, options: list[str]) -> dict:
        return {'claim': 'skip'}
