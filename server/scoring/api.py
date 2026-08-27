"""
Clean public API for the IMR scoring engine.
Upper layers should only import from here.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import List, Optional
from collections import Counter

from scoring.parsing import (
    Tile, TileType, Call,
    ParsedHand, HandExplanation,
    find_all_explanations, validate_hand,
)
from scoring.fan import (
    ScoringResult,
    load_fans_from_csv, calculate_score,
)

# ---------------------------------------------------------------------------
# Module-level fan cache (loaded once)
# ---------------------------------------------------------------------------
_FANS: Optional[dict] = None


def _fans() -> dict:
    global _FANS
    if _FANS is None:
        _FANS = load_fans_from_csv()
    return _FANS


# ---------------------------------------------------------------------------
# Flags dataclass
# ---------------------------------------------------------------------------

@dataclass
class WinFlags:
    self_drawn: bool = False
    last_tile: bool = False        # 海底/last tile in wall
    declared_wait: bool = False    # 报听 (+DW)
    after_quad: bool = False       # 嶺上開花 (+AQ)
    robbing_quad: bool = False     # 搶槓 (+RQ)
    heavenly: bool = False         # 天和 (+BOH)
    earthly: bool = False          # 地和 (+BOE)
    heavenly_wait: bool = False    # 天聽 (+EW)


def _build_notes(flags: WinFlags) -> str:
    parts = []
    if flags.last_tile:
        parts.append('+LT')
    if flags.declared_wait:
        parts.append('+DW')
    if flags.after_quad:
        parts.append('+AQ')
    if flags.robbing_quad:
        parts.append('+RQ')
    if flags.heavenly:
        parts.append('+BOH')
    if flags.earthly:
        parts.append('+BOE')
    if flags.heavenly_wait:
        parts.append('+EW')
    return ''.join(parts)


def _make_parsed_hand(
    hand_tiles: List[Tile],
    calls: List[Call],
    winning_tile: Tile,
    flags: WinFlags,
) -> ParsedHand:
    return ParsedHand(
        calls=calls,
        hand_tiles=hand_tiles,
        winning_tile=winning_tile,
        is_self_drawn=flags.self_drawn,
        additional_notes=_build_notes(flags),
        format_type='english',
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def is_winning(
    hand_tiles: List[Tile],
    calls: List[Call],
    winning_tile: Tile,
    flags: WinFlags,
) -> bool:
    """Return True if the hand forms a legal winning pattern."""
    parsed = _make_parsed_hand(hand_tiles, calls, winning_tile, flags)
    ok, _ = validate_hand(parsed)
    if not ok:
        return False
    return bool(find_all_explanations(parsed))


def score_hand(
    hand_tiles: List[Tile],
    calls: List[Call],
    winning_tile: Tile,
    flags: WinFlags,
) -> Optional[ScoringResult]:
    """
    Score the best explanation of the hand.
    Returns the highest-scoring ScoringResult, or None if not a winning hand.
    """
    parsed = _make_parsed_hand(hand_tiles, calls, winning_tile, flags)
    ok, _ = validate_hand(parsed)
    if not ok:
        return None
    explanations = find_all_explanations(parsed)
    if not explanations:
        return None
    fans = _fans()
    best: Optional[ScoringResult] = None
    for exp in explanations:
        result = calculate_score(exp, fans)
        if best is None or result.total_score > best.total_score:
            best = result
    return best


def waits(hand_tiles: List[Tile], calls: List[Call]) -> List[Tile]:
    """
    Return all tiles that would complete the hand (tenpai waiting tiles).
    Brute-force: try every possible tile and check is_winning.
    """
    all_tile_types = [
        *[Tile(TileType.BAMBOO, v) for v in range(1, 10)],
        *[Tile(TileType.CHARACTER, v) for v in range(1, 10)],
        *[Tile(TileType.DOT, v) for v in range(1, 10)],
        Tile(TileType.WIND, 1), Tile(TileType.WIND, 2),
        Tile(TileType.WIND, 3), Tile(TileType.WIND, 4),
        Tile(TileType.DRAGON, 1), Tile(TileType.DRAGON, 2), Tile(TileType.DRAGON, 3),
    ]
    current_counts = Counter(hand_tiles)
    for call in calls:
        for t in call.tiles:
            current_counts[t] += 1

    result = []
    for candidate in all_tile_types:
        if current_counts[candidate] >= 4:
            continue
        flags = WinFlags(self_drawn=True)
        if is_winning(hand_tiles, calls, candidate, flags):
            result.append(candidate)
    return result


def shanten(hand_tiles: List[Tile], calls: List[Call]) -> int:
    """
    Return the shanten number (0 = tenpai, -1 = winning, >0 = N tiles away).
    Derived from waits: if any wait exists, shanten = 0.
    """
    # Check if already winning (shanten = -1)
    if waits(hand_tiles, calls):
        return 0

    # Simple approximation: count pairs/triplets/straights available
    # Full shanten calculation is complex; for Step 1 bots, 0 vs >0 suffices.
    # We'll use a greedy tile-removal approach.
    return _shanten_calc(hand_tiles, calls)


def _shanten_calc(hand_tiles: List[Tile], calls: List[Call]) -> int:
    """Approximate shanten via standard algorithm."""
    # Number of groups already formed via calls
    groups_from_calls = len(calls)
    tiles = list(hand_tiles)

    # Try standard 4-group + 1 pair pattern
    best = _shanten_standard(Counter(tiles), 4 - groups_from_calls)

    # Seven pairs shanten (only possible when no calls)
    if not calls and len(tiles) >= 1:
        pairs = sum(1 for c in Counter(tiles).values() if c >= 2)
        sp = 6 - pairs
        best = min(best, sp)

    return max(best, 0)


def _shanten_standard(counts: Counter, groups_needed: int) -> int:
    """Standard shanten calculation helper."""
    # Greedy approach: try to form mentsu (groups) and partial groups
    best = groups_needed * 2  # worst case

    def recurse(counts: Counter, groups: int, partial: int, pair: bool) -> int:
        needed = groups_needed - groups
        # Minimum shanten for remaining
        s = needed * 2 - 1 if pair else needed * 2
        s -= partial
        if needed == 0:
            return -1 if pair else 0
        tiles = sorted([t for t, c in counts.items() if c > 0])
        if not tiles:
            return needed * 2 - (1 if pair else 0) - partial

        result = needed * 2  # safe upper bound
        first = tiles[0]

        # Try pair
        if not pair and counts[first] >= 2:
            new = counts.copy()
            new[first] -= 2
            if new[first] == 0:
                del new[first]
            result = min(result, recurse(new, groups, partial, True))

        # Try triplet
        if counts[first] >= 3:
            new = counts.copy()
            new[first] -= 3
            if new[first] == 0:
                del new[first]
            result = min(result, recurse(new, groups + 1, partial, pair))

        # Try straight
        if not first.is_honor() and first.value <= 7:
            n1 = Tile(first.tile_type, first.value + 1)
            n2 = Tile(first.tile_type, first.value + 2)
            if counts.get(n1, 0) >= 1 and counts.get(n2, 0) >= 1:
                new = counts.copy()
                for t in (first, n1, n2):
                    new[t] -= 1
                    if new[t] == 0:
                        del new[t]
                result = min(result, recurse(new, groups + 1, partial, pair))

        # Try partial straight (kanchan or sequential pair)
        if not first.is_honor():
            for delta in (1, 2):
                if first.value + delta <= 9:
                    neighbor = Tile(first.tile_type, first.value + delta)
                    if counts.get(neighbor, 0) >= 1:
                        new = counts.copy()
                        new[first] -= 1
                        if new[first] == 0:
                            del new[first]
                        new[neighbor] -= 1
                        if new[neighbor] == 0:
                            del new[neighbor]
                        result = min(result, recurse(new, groups, partial + 1, pair))

        # Skip tile (always possible as fallback)
        new = counts.copy()
        new[first] -= 1
        if new[first] == 0:
            del new[first]
        result = min(result, recurse(new, groups, partial, pair))

        return result

    return recurse(counts, 0, 0, False)
