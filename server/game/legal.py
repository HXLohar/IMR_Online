"""
Legal-action detection: pure functions, no async/network.

Given a discarded tile and a player's hand state, determines which claims
(chow/pong/kong/win) are legally available.

Key IMR rules enforced here:
  - Chow only available to the player immediately downstream (next seat).
  - chow_pong_limit: derived from pass_count (0→None, 1→2, 2→1).
    If calling chow/pong would push the player's chow_pong_count over the
    limit, the call is disallowed. Kong never counts toward this limit.
  - A face-down discard (rang_guo) cannot be claimed by anyone.
  - is_winning is used to test whether a win claim is legal.
"""
from __future__ import annotations
from collections import Counter
from typing import TYPE_CHECKING

from game.tiles import Tile, TileType
from scoring.parsing import Call, CallType
from scoring.api import is_winning, WinFlags

if TYPE_CHECKING:
    from game.player_state import PlayerState


def chow_pong_limit(pass_count: int) -> int | None:
    """Max chow+pong count given how many times this player has passed (rang_guo)."""
    if pass_count == 0:
        return None  # no limit
    elif pass_count == 1:
        return 2
    else:
        return 1


def can_chow(
    hand: list[Tile],
    discard: Tile,
    pass_count: int,
    chow_pong_count: int,
) -> list[Call]:
    """
    Return all valid chow options.
    Chow is only valid when called by the player directly downstream.
    (Caller must check seat adjacency before using this result.)
    """
    if discard.is_honor():
        return []

    limit = chow_pong_limit(pass_count)
    if limit is not None and chow_pong_count >= limit:
        return []

    hand_counts = Counter(hand)
    suit = discard.tile_type
    v = discard.value
    options = []

    # Three possible chow positions:
    for low in (v - 2, v - 1, v):
        tiles_needed = [
            Tile(suit, low),
            Tile(suit, low + 1),
            Tile(suit, low + 2),
        ]
        if any(t.value < 1 or t.value > 9 for t in tiles_needed):
            continue
        # The discard covers one slot; need the other two from hand
        needed_from_hand = [t for t in tiles_needed if t != discard]
        # Count how many the hand actually has
        if len(needed_from_hand) == 2:
            t1, t2 = needed_from_hand
            if hand_counts[t1] >= 1 and hand_counts[t2] >= 1:
                options.append(Call(CallType.STRAIGHT, sorted(tiles_needed)))
        elif len(needed_from_hand) == 1:
            # Discard appears twice in the straight (impossible for normal tiles)
            t1 = needed_from_hand[0]
            if hand_counts[t1] >= 1:
                options.append(Call(CallType.STRAIGHT, sorted(tiles_needed)))

    return options


def can_pong(
    hand: list[Tile],
    discard: Tile,
    pass_count: int,
    chow_pong_count: int,
) -> bool:
    """Return True if player can pong the discard."""
    limit = chow_pong_limit(pass_count)
    if limit is not None and chow_pong_count >= limit:
        return False
    return Counter(hand)[discard] >= 2


def can_open_kong(
    hand: list[Tile],
    discard: Tile,
) -> bool:
    """Return True if player can declare open kong (大明槓) on the discard."""
    return Counter(hand)[discard] >= 3


def can_added_kong(
    hand: list[Tile],
    calls: list[Call],
    drawn_tile: Tile,
) -> list[Tile]:
    """
    Return tiles for which added-kong (加槓) is possible.
    Player has a pong call and now holds the 4th tile in hand (or just drew it).
    """
    pong_tiles = {
        call.tiles[0]
        for call in calls
        if call.call_type == CallType.TRIPLET
    }
    result = []
    hand_counts = Counter(hand)
    for t in pong_tiles:
        if hand_counts[t] >= 1 or t == drawn_tile:
            result.append(t)
    return result


def can_concealed_kong(
    hand: list[Tile],
    drawn_tile: Tile,
) -> list[Tile]:
    """Return tiles that can form a concealed kong from hand (including drawn tile)."""
    all_tiles = Counter(hand + [drawn_tile])
    return [tile for tile, count in all_tiles.items() if count >= 4]


def can_win_on_discard(
    hand: list[Tile],
    calls: list[Call],
    discard: Tile,
    flags: WinFlags,
) -> bool:
    """Return True if player can win (ron) on the discarded tile."""
    return is_winning(hand, calls, discard, flags)


def can_win_self_drawn(
    hand: list[Tile],
    calls: list[Call],
    drawn_tile: Tile,
    flags: WinFlags,
) -> bool:
    """Return True if player can win by tsumo on the drawn tile."""
    return is_winning(hand, calls, drawn_tile, flags)


def legal_claims(
    hand: list[Tile],
    calls: list[Call],
    discard: Tile,
    from_seat: int,
    my_seat: int,
    num_players: int,
    pass_count: int,
    chow_pong_count: int,
    win_flags: WinFlags,
    face_down: bool = False,
) -> dict:
    """
    Compute the full set of legal claims this player can make on a discard.

    Returns a dict:
        {
          'chow': [Call, ...],   # list of valid chow calls
          'pong': bool,
          'kong': bool,
          'win': bool,
          'skip': True,          # always available
        }
    Face-down discards (rang_guo) cannot be claimed.
    """
    if face_down:
        return {'chow': [], 'pong': False, 'kong': False, 'win': False, 'skip': True}

    downstream = (from_seat + 1) % num_players
    is_downstream = (my_seat == downstream)

    chows = can_chow(hand, discard, pass_count, chow_pong_count) if is_downstream else []
    pong = can_pong(hand, discard, pass_count, chow_pong_count)
    kong = can_open_kong(hand, discard)
    win = can_win_on_discard(hand, calls, discard, win_flags)

    return {
        'chow': chows,
        'pong': pong,
        'kong': kong,
        'win': win,
        'skip': True,
    }
