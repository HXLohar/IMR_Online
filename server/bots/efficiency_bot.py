"""Closed-hand efficiency bot: no calls, push toward declare wait."""
from collections import Counter

from bots.base import Bot
from game.tiles import tile_from_str
from scoring.api import shanten, waits


ORPHANS = {'1b', '9b', '1c', '9c', '1d', '9d', 'E', 'S', 'W', 'N', 'Wh', 'G', 'R'}


class EfficiencyBot(Bot):
    def decide_turn(self, view: dict) -> dict:
        options = view.get('options', [])
        if 'tsumo' in options:
            return {'type': 'self_action', 'action': 'tsumo'}
        if 'declare_wait' in options:
            return {'type': 'self_action', 'action': 'declare_wait'}

        hand = view.get('hand', [])
        tile = self._best_discard(hand)
        return {'type': 'discard', 'action': 'discard', 'tile': tile, 'face_down': False}

    def decide_claim(self, view: dict, options: list[str]) -> dict:
        if 'win' in options:
            return {'claim': 'win'}
        return {'claim': 'skip'}

    def _best_discard(self, hand: list[str]) -> str | None:
        if not hand:
            return None
        best = min(hand, key=lambda tile: self._discard_score(hand, tile))
        return best

    def _discard_score(self, hand: list[str], discard: str) -> tuple[int, int, int, str]:
        rest = list(hand)
        rest.remove(discard)
        tiles = [tile_from_str(t) for t in rest]
        count = Counter(rest)
        pair_count = sum(1 for n in count.values() if n >= 2)
        orphan_count = len(set(rest) & ORPHANS)
        wait_count = len(waits(tiles, []))
        # Lower is better: shanten first, then more waits, then preserve 7 pairs / 13 orphans.
        return (shanten(tiles, []), -wait_count, -pair_count, -orphan_count, discard)
