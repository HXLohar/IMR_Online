"""Per-seat mutable game state."""
from __future__ import annotations
from dataclasses import dataclass, field
from game.tiles import Tile
from scoring.parsing import Call


@dataclass
class PlayerState:
    seat: int
    name: str
    is_bot: bool = False

    hand: list[Tile] = field(default_factory=list)         # closed tiles
    calls: list[Call] = field(default_factory=list)        # open/concealed melds
    river: list[Tile] = field(default_factory=list)        # face-up discards
    river_face_down: list[bool] = field(default_factory=list)  # parallel: True = rang_guo

    pass_count: int = 0        # number of rang_guo (face-down discards)
    straight_triplet_count: int = 0   # straight + triplet calls (quad excluded)
    has_declared_wait: bool = False
    declared_waits: list[Tile] = field(default_factory=list)
    is_ready: bool = False     # game-start ready

    score: int = 0             # running total across hands (not yet used in Step 1)

    def draw(self, tile: Tile) -> None:
        self.hand.append(tile)

    def discard(self, tile: Tile, face_down: bool = False) -> None:
        self.hand.remove(tile)
        self.river.append(tile)
        self.river_face_down.append(face_down)
        if face_down:
            self.pass_count += 1

    @property
    def chow_pong_count(self) -> int:
        """Legacy alias for straight_triplet_count."""
        return self.straight_triplet_count

    @chow_pong_count.setter
    def chow_pong_count(self, value: int) -> None:
        self.straight_triplet_count = value

    @property
    def is_riichi(self) -> bool:
        """Legacy alias for has_declared_wait."""
        return self.has_declared_wait

    @is_riichi.setter
    def is_riichi(self, value: bool) -> None:
        self.has_declared_wait = value

    def add_call(self, call: Call, is_straight_or_triplet: bool = True, **legacy: bool) -> None:
        self.calls.append(call)
        if "is_pong_or_chow" in legacy:
            is_straight_or_triplet = legacy["is_pong_or_chow"]
        if is_straight_or_triplet:
            self.straight_triplet_count += 1

    def all_visible_discards(self) -> list[Tile]:
        """Return only face-up discards (for redraw condition checks)."""
        return [t for t, fd in zip(self.river, self.river_face_down) if not fd]

    def all_tiles_visible_to_others(self) -> list[Tile]:
        """Tiles other players can see: face-up river + open call tiles."""
        from scoring.parsing import CallType
        open_call_tiles: list[Tile] = []
        for call in self.calls:
            if call.call_type != 'concealed_quad':
                open_call_tiles.extend(call.tiles)
        return self.all_visible_discards() + open_call_tiles

    def reset_for_new_hand(self) -> None:
        self.hand.clear()
        self.calls.clear()
        self.river.clear()
        self.river_face_down.clear()
        self.pass_count = 0
        self.straight_triplet_count = 0
        self.has_declared_wait = False
        self.declared_waits.clear()
