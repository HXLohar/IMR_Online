"""
Redraw (重摸) eligibility — pure function, no side effects.

A player may redraw on a just-drawn tile if ANY of these conditions hold:

  1. The tile is an honor tile AND at least 2 copies are already "visible"
     (in any player's discard river or in open calls across the table).

  2. The player has previously discarded this tile:
     - Honor tile: ≥ 1 time in their own river.
     - Non-honor tile: ≥ 2 times in their own river.

  3. The drawn tile is the same as the LAST tile in the player's own river
     (face-up discard only; tiles claimed by triplet/straight calls don't count as "in river").
"""
from __future__ import annotations
from collections import Counter

from game.tiles import Tile


def is_redraw_eligible(
    drawn_tile: Tile,
    own_river: list[Tile],          # tiles this player has discarded (face-up only)
    all_visible_tiles: list[Tile],  # ALL tiles visible on the table (rivers + open calls)
) -> bool:
    """
    Return True if the player may immediately discard drawn_tile and redraw.
    """
    # Condition 1: honor tile with ≥2 visible copies
    if drawn_tile.is_honor():
        visible_count = Counter(all_visible_tiles)[drawn_tile]
        if visible_count >= 2:
            return True

    # Condition 2a: player has discarded this honor tile ≥1 time
    own_river_count = Counter(own_river)[drawn_tile]
    if drawn_tile.is_honor():
        if own_river_count >= 1:
            return True
    else:
        # Condition 2b: player has discarded this non-honor tile ≥2 times
        if own_river_count >= 2:
            return True

    # Condition 3: last tile in player's river is same as drawn tile
    if own_river and own_river[-1] == drawn_tile:
        return True

    return False
