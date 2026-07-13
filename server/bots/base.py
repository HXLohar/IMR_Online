"""Bot interface — every bot implements these two methods."""
from abc import ABC, abstractmethod


class Bot(ABC):
    @abstractmethod
    def decide_turn(self, view: dict) -> dict:
        """
        Called when it's this bot's turn (after drawing a tile).
        view['hand'] includes the drawn tile as the last element.
        Must return one of:
          {'type': 'discard', 'action': 'discard', 'tile': '5c', 'face_down': False}
          {'type': 'self_action', 'action': 'tsumo'}
          etc.
        """

    @abstractmethod
    def decide_claim(self, view: dict, options: list[str]) -> dict:
        """
        Called during a claim window.
        Must return {'claim': 'skip'|'triplet_call'|'direct_quad_call'|'straight_call'|'win', ...}.
        """
