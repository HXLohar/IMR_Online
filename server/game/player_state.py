"""Per-seat mutable game state."""
from __future__ import annotations
from dataclasses import dataclass, field
from bots.base import Bot
from game.tiles import Tile
from scoring.parsing import Call


@dataclass
class PlayerState:
    seat: int
    name: str
    is_bot: bool = False
    bot: Bot | None = None

    hand: list[Tile] = field(default_factory=list)         # closed tiles
    calls: list[Call] = field(default_factory=list)        # open/concealed melds
    river: list[Tile] = field(default_factory=list)        # face-up discards
    river_face_down: list[bool] = field(default_factory=list)  # parallel: True = rang_guo

    pass_count: int = 0        # number of rang_guo (face-down discards)
    straight_triplet_count: int = 0   # straight + triplet calls (quad excluded)
    has_declared_wait: bool = False
    declared_waits: list[Tile] = field(default_factory=list)

    score: int = 0             # running total across hands (not yet used in Step 1)

    def draw(self, tile: Tile) -> None:
        self.hand.append(tile)

    def discard(self, tile: Tile, face_down: bool = False) -> None:
        self.hand.remove(tile)
        self.river.append(tile)
        self.river_face_down.append(face_down)
        if face_down:
            self.pass_count += 1

    def add_call(self, call: Call, is_straight_or_triplet: bool = True) -> None:
        self.calls.append(call)
        if is_straight_or_triplet:
            self.straight_triplet_count += 1

    def all_visible_discards(self) -> list[Tile]:
        """Return only face-up discards (for redraw condition checks)."""
        return [t for t, fd in zip(self.river, self.river_face_down) if not fd]

    def reset_for_new_hand(self) -> None:
        self.hand.clear()
        self.calls.clear()
        self.river.clear()
        self.river_face_down.clear()
        self.pass_count = 0
        self.straight_triplet_count = 0
        self.has_declared_wait = False
        self.declared_waits.clear()
