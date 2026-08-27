"""
Legal-action detection: pure functions, no async/network.

Given a discarded tile and a player's hand state, determines which claims
(straight call/triplet call/quad call/win) are legally available.

Key IMR rules enforced here:
  - Straight call only available to the player immediately downstream (next seat).
  - straight_triplet_limit: derived from pass_count.
    If calling straight/triplet would push the player's straight_triplet_count
    over the limit, the call is disallowed. Quad never counts toward this limit.
  - A face-down discard (rang_guo) cannot be claimed by anyone.
  - is_winning is used to test whether a win claim is legal.
"""
from __future__ import annotations
from collections import Counter
from typing import TYPE_CHECKING

from game.tiles import Tile
from scoring.parsing import Call, CallType
from scoring.api import is_winning, waits, WinFlags

if TYPE_CHECKING:
    from game.player_state import PlayerState


def straight_triplet_limit(pass_count: int) -> int | None:
    """Max straight+triplet call count given how many times this player has passed."""
    if pass_count == 0:
        return 4
    return max(0, 3 - pass_count)


def can_add_pass(pass_count: int, straight_triplet_count: int) -> bool:
    return pass_count + straight_triplet_count < 3


def can_add_straight_triplet_call(pass_count: int, straight_triplet_count: int) -> bool:
    if pass_count == 0:
        return straight_triplet_count < 4
    return pass_count + straight_triplet_count < 3


def can_straight_call(
    hand: list[Tile],
    discard: Tile,
    pass_count: int,
    straight_triplet_count: int = 0,
) -> list[Call]:
    """
    Return all valid straight call options.
    Straight call is only valid when called by the player directly downstream.
    (Caller must check seat adjacency before using this result.)
    """
    if discard.is_honor():
        return []

    if not can_add_straight_triplet_call(pass_count, straight_triplet_count):
        return []

    hand_counts = Counter(hand)
    suit = discard.tile_type
    v = discard.value
    options = []

    # Three possible straight-call positions:
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


def can_triplet_call(
    hand: list[Tile],
    discard: Tile,
    pass_count: int,
    straight_triplet_count: int = 0,
) -> bool:
    """Return True if player can triplet-call the discard."""
    if not can_add_straight_triplet_call(pass_count, straight_triplet_count):
        return False
    return Counter(hand)[discard] >= 2


def can_direct_quad_call(
    hand: list[Tile],
    discard: Tile,
    calls: list[Call] | None = None,
    has_declared_wait: bool = False,
) -> bool:
    """Return True if player can direct-quad-call (大明槓) the discard."""
    if Counter(hand)[discard] < 3:
        return False
    if not has_declared_wait:
        return True
    new_hand = list(hand)
    for _ in range(3):
        new_hand.remove(discard)
    return bool(waits(new_hand, (calls or []) + [Call(CallType.QUAD, [discard] * 4)]))


def can_upgraded_quad_declare(
    hand: list[Tile],
    calls: list[Call],
    drawn_tile: Tile,
) -> list[Tile]:
    """
    Return tiles for which upgraded quad declare (補槓) is possible.
    Player has a triplet call and now holds the 4th tile in hand (or just drew it).
    """
    triplet_tiles = {
        call.tiles[0]
        for call in calls
        if call.call_type == CallType.TRIPLET
    }
    result = []
    hand_counts = Counter(hand)
    for t in triplet_tiles:
        if hand_counts[t] >= 1 or t == drawn_tile:
            result.append(t)
    return result


def can_concealed_quad_declare(
    hand: list[Tile],
    drawn_tile: Tile,
) -> list[Tile]:
    """Return tiles that can form a concealed quad declare from hand."""
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
    straight_triplet_count: int = 0,
    win_flags: WinFlags | None = None,
    face_down: bool = False,
    has_declared_wait: bool = False,
) -> dict:
    """
    Compute the full set of legal claims this player can make on a discard.

    Returns a dict:
        {
          'straight_call': [Call, ...],
          'triplet_call': bool,
          'direct_quad_call': bool,
          'win': bool,
          'skip': True,          # always available
        }
    Face-down discards (rang_guo) cannot be claimed.
    """
    win_flags = win_flags or WinFlags()
    if face_down:
        return _claims_result([], False, False, False)

    downstream = (from_seat + 1) % num_players
    is_downstream = (my_seat == downstream)

    straight_calls = [] if has_declared_wait else can_straight_call(hand, discard, pass_count, straight_triplet_count) if is_downstream else []
    triplet_call = False if has_declared_wait else can_triplet_call(hand, discard, pass_count, straight_triplet_count)
    direct_quad_call = can_direct_quad_call(hand, discard, calls, has_declared_wait)
    win = can_win_on_discard(hand, calls, discard, win_flags)

    return _claims_result(straight_calls, triplet_call, direct_quad_call, win)


def _claims_result(straight_calls: list[Call], triplet_call: bool, direct_quad_call: bool, win: bool) -> dict:
    result = {
        'straight_call': straight_calls,
        'triplet_call': triplet_call,
        'direct_quad_call': direct_quad_call,
        'win': win,
        'skip': True,
    }
    return result
