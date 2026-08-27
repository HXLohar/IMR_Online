"""
Fan (番) Scoring System for IMR Mahjong Calculator
Handles fan detection and scoring based on hand explanations.
"""
# IMPORTANT THING MUST READ
# IMR's Fan definition can be different from Chinese Mahjong (MCR) or Japanese Riichi Mahjong.
# So when you see a Fan's description is different from other ruleset, whether in the code or in any related files I mentioned, DO NOT TOUCH IT, JUST DO IT.
# 重要內容, 必須閱讀!
# IMR的番種定義和中國國標麻將和日本立直麻將可能不同.
# 所以當你看到一個番種的描述和其他規則集不同的時候(無論是在代碼中還是在提到的任何其他相關文件), 不要進行更改. 照做即可.
import csv
import os
from typing import List, Dict, Optional, Set, Tuple
from dataclasses import dataclass, field
from collections import Counter
from scoring.parsing import (
    HandExplanation, Group, Tile, TileType, ParsedHand,
)


@dataclass
class Fan:
    """Represents a Fan (scoring pattern)."""
    id: int
    is_excellence: bool  # True if this is an Excellence Fan
    value: int
    name_e: str  # English name
    name_c: str  # Chinese name (Traditional)
    desc_e: str  # English description
    desc_c: str  # Chinese description
    hand_format: str  # Valid hand formats (e.g., "TTTTp", "seven_pairs", "SSSSp, TTTTp")
    overrides: List[int] = field(default_factory=list)  # List of fan IDs this fan directly overrides


@dataclass
class AchievedFan:
    """Represents an achieved Fan with its calculated score."""
    fan: Fan
    score: int  # The actual score (may be halved for secondary excellence fans)
    is_main: bool = False  # True if this is the main excellence fan


@dataclass
class ScoringResult:
    """Complete scoring result for a hand explanation."""
    explanation: HandExplanation
    achieved_fans: List[AchievedFan]
    total_score: int
    is_excellence: bool  # True if any excellence fan was achieved


# =============================================================================
# CSV LOADING AND OVERRIDE COMPUTATION
# =============================================================================

_DEFAULT_FAN_CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "fan.csv")


def load_fans_from_csv(filepath: str = None) -> Dict[int, Fan]:
    if filepath is None:
        filepath = _DEFAULT_FAN_CSV
    """Load fan definitions from CSV file."""
    fans = {}
    encodings = ['utf-8', 'utf-8-sig', 'gb2312', 'gbk', 'cp936', 'big5', 'latin-1']

    for encoding in encodings:
        try:
            with open(filepath, 'r', encoding=encoding) as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if not row.get('id'):
                        continue
                    try:
                        # Parse override field (comma-separated IDs)
                        override_str = row.get('override', '').strip()
                        overrides = []
                        if override_str:
                            for part in override_str.split(','):
                                part = part.strip()
                                if part:
                                    overrides.append(int(part))

                        fan = Fan(
                            id=int(row['id']),
                            is_excellence=row.get('is_excellence', '').upper() == 'TRUE',
                            value=int(row.get('value', 0)),
                            name_e=row.get('name_e', ''),
                            name_c=row.get('name_c', ''),
                            desc_e=row.get('desc_e', ''),
                            desc_c=row.get('desc_c', ''),
                            hand_format=row.get('hand_format', ''),
                            overrides=overrides
                        )
                        fans[fan.id] = fan
                    except (ValueError, KeyError):
                        continue
            break  # Success, stop trying encodings
        except (FileNotFoundError, UnicodeDecodeError):
            continue

    return fans


def compute_recursive_overrides(fans: Dict[int, Fan]) -> Dict[int, Set[int]]:
    """
    Compute the transitive closure of overrides.
    If A overrides B and B overrides CD, then A overrides BCD.
    Returns a dict mapping fan_id -> set of all fan_ids it overrides (recursively).
    """
    # Build direct override map
    direct_overrides: Dict[int, Set[int]] = {}
    for fan_id, fan in fans.items():
        direct_overrides[fan_id] = set(fan.overrides)

    # Compute transitive closure
    all_overrides: Dict[int, Set[int]] = {}

    def get_all_overrides(fan_id: int, visited: Set[int]) -> Set[int]:
        if fan_id in all_overrides:
            return all_overrides[fan_id]

        if fan_id in visited:
            return set()  # Cycle detection

        visited.add(fan_id)
        result = set(direct_overrides.get(fan_id, set()))

        # Recursively get overrides of overridden fans
        for override_id in list(result):
            if override_id in fans:
                result.update(get_all_overrides(override_id, visited))

        all_overrides[fan_id] = result
        return result

    for fan_id in fans:
        get_all_overrides(fan_id, set())

    return all_overrides


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def get_all_tiles(explanation: HandExplanation) -> List[Tile]:
    """Get all tiles from a hand explanation."""
    tiles = []
    for group in explanation.groups:
        tiles.extend(group.tiles)
    if explanation.pair:
        tiles.extend(explanation.pair)
    return tiles


def get_numbered_suits(tiles: List[Tile]) -> Set[TileType]:
    """Get set of numbered suits used in tiles."""
    return {t.tile_type for t in tiles if not t.is_honor()}


def get_straights(explanation: HandExplanation) -> List[Group]:
    """Get all straight groups from an explanation."""
    return [g for g in explanation.groups if g.group_type == 'straight']


def get_triplets(explanation: HandExplanation) -> List[Group]:
    """Get all triplet groups (not quads) from an explanation."""
    return [g for g in explanation.groups if g.group_type == 'triplet']


def get_quads(explanation: HandExplanation) -> List[Group]:
    """Get all quad groups from an explanation."""
    return [g for g in explanation.groups if g.group_type == 'quad']


def get_triplets_and_quads(explanation: HandExplanation) -> List[Group]:
    """Get all triplet and quad groups from an explanation."""
    return [g for g in explanation.groups if g.group_type in ('triplet', 'quad')]


def get_calls(explanation: HandExplanation) -> List[Group]:
    """Get all called groups (melds)."""
    return [g for g in explanation.groups if g.is_call]


def get_concealed_triplets(explanation: HandExplanation) -> List[Group]:
    """Get all concealed triplets (not called, or concealed quad).
    Win-by-discard: the triplet that the winning tile completes is not counted
    as fully concealed (the winning tile came from an opponent's discard).
    """
    result = []
    for g in explanation.groups:
        if g.group_type == 'triplet' and not g.is_call:
            result.append(g)
        elif g.group_type == 'quad' and g.is_concealed_quad:
            result.append(g)
    if not explanation.is_self_drawn:
        wt = explanation.winning_tile
        for g in list(result):
            if g.group_type == 'triplet' and any(t == wt for t in g.tiles):
                result.remove(g)
                break
    return result


def get_straight_key(group: Group) -> Tuple[TileType, int]:
    """Get (suit, starting_value) key for a straight."""
    sorted_tiles = sorted(group.tiles)
    return (sorted_tiles[0].tile_type, sorted_tiles[0].value)


def get_triplet_key(group: Group) -> Tuple[TileType, int]:
    """Get (suit, value) key for a triplet/quad."""
    return (group.tiles[0].tile_type, group.tiles[0].value)


def is_wind_triplet(group: Group) -> bool:
    """Check if group is a wind triplet/quad."""
    return group.group_type in ('triplet', 'quad') and group.tiles[0].tile_type == TileType.WIND


def is_dragon_triplet(group: Group) -> bool:
    """Check if group is a dragon triplet/quad."""
    return group.group_type in ('triplet', 'quad') and group.tiles[0].tile_type == TileType.DRAGON


def check_hand_format(explanation: HandExplanation, required_format: str) -> bool:
    """Check if explanation matches the required hand format."""
    if not required_format:
        return True  # No format restriction

    formats = [f.strip() for f in required_format.split(',')]
    pattern = explanation.pattern_type

    for fmt in formats:
        if fmt == 'seven_pairs':
            if pattern == '7P':
                return True
        elif fmt == 'thirteen_orphans':
            if pattern == '13O':
                return True
        elif fmt == 'TTTTp':
            if pattern == 'TTTTp':
                return True
        elif fmt == 'SSSSp':
            if pattern == 'SSSSp':
                return True
        elif fmt == 'TTTSp':
            if pattern == 'TTTSp':
                return True
        elif fmt == 'TTSSp':
            if pattern == 'TTSSp':
                return True
        elif fmt == 'TSSSp':
            if pattern == 'TSSSp':
                return True
        elif '?' in fmt:
            # Pattern with wildcards like "T???p", "TT??p", "SSS?p", etc.
            # Count T's and S's in format
            fmt_t = fmt.count('T')
            fmt_s = fmt.count('S')
            pattern_t = pattern.count('T')
            pattern_s = pattern.count('S')

            # Must have at least the required number of T's and S's
            if pattern_t >= fmt_t and pattern_s >= fmt_s and pattern.endswith('p'):
                return True
        elif fmt == '????p':
            # Any 4-group pattern
            if pattern.endswith('p') and pattern != '7P' and pattern != '13O':
                return True

    return False


# =============================================================================
# FAN DETECTION FUNCTIONS - EXCELLENCE FANS (101-124)
# =============================================================================

def check_101_supreme_nine_gates(explanation: HandExplanation) -> bool:
    """
    101: SUPREME NINE GATES (純正九蓮寶燈)
    1112345678999 of same suit, all tiles of that suit are valid waits.
    Must be fully concealed — no calls, no concealed quads.
    """
    if explanation.pattern_type not in ('SSSSp', 'TSSSp', 'TTSSp', 'TTTSp', 'TTTTp'):
        return False
    if any(g.is_call for g in explanation.groups):
        return False

    tiles = get_all_tiles(explanation)
    suits = get_numbered_suits(tiles)
    if len(suits) != 1:
        return False

    suit = list(suits)[0]
    values = sorted([t.value for t in tiles if t.tile_type == suit])

    if len(values) != 14:
        return False

    # Must be exactly 1112345678999 + any tile of same suit
    # Check for 1112345678999 base (13 tiles) plus one extra
    value_counts = Counter(values)

    # The base pattern: 1(3), 2(1), 3(1), 4(1), 5(1), 6(1), 7(1), 8(1), 9(3)
    base_pattern = {1: 3, 2: 1, 3: 1, 4: 1, 5: 1, 6: 1, 7: 1, 8: 1, 9: 3}

    # One value should have count = base + 1
    valid_wait = False
    for v in range(1, 10):
        expected = base_pattern.get(v, 0)
        if value_counts.get(v, 0) == expected + 1:
            # Check all other values match base
            all_match = True
            for v2 in range(1, 10):
                if v2 != v:
                    if value_counts.get(v2, 0) != base_pattern.get(v2, 0):
                        all_match = False
                        break
            if all_match:
                valid_wait = True
                break

    if not valid_wait:
        return False

    # For SUPREME, need all 9 waits (1-9 of same suit)
    # This requires checking the waiting tiles, which is complex
    # For simplicity, check if hand is exactly 1112345678999 + one more
    # and verify the winning tile allows 9-sided wait
    # The 9-sided wait only happens when you have exactly 1112345678999

    # Check if without the winning tile, we have 1112345678999
    hand_without_win = [t for t in tiles if not (t == explanation.winning_tile)]
    # Actually, we need to remove just one instance of winning tile
    temp_tiles = list(tiles)
    temp_tiles.remove(explanation.winning_tile)

    temp_values = sorted([t.value for t in temp_tiles if t.tile_type == suit])
    temp_counts = Counter(temp_values)

    if temp_counts == base_pattern:
        return True  # All 9 waits possible

    return False


def check_102_nine_gates(explanation: HandExplanation) -> bool:
    """
    102: NINE GATES (九蓮寶燈)
    1112345678999X of same suit, where X is any tile of that suit.
    But NOT a 9-sided wait. Must be fully concealed — no calls, no concealed quads.
    """
    if explanation.pattern_type not in ('SSSSp', 'TSSSp', 'TTSSp', 'TTTSp', 'TTTTp'):
        return False
    if any(g.is_call for g in explanation.groups):
        return False

    tiles = get_all_tiles(explanation)
    suits = get_numbered_suits(tiles)
    if len(suits) != 1:
        return False

    suit = list(suits)[0]
    values = sorted([t.value for t in tiles if t.tile_type == suit])

    if len(values) != 14:
        return False

    value_counts = Counter(values)

    # Must have at least: 1(3), 9(3), and 2-8(1 each)
    if value_counts.get(1, 0) < 3 or value_counts.get(9, 0) < 3:
        return False

    for v in range(2, 9):
        if value_counts.get(v, 0) < 1:
            return False

    # Total should be 14
    if sum(value_counts.values()) != 14:
        return False

    # Check it's NOT supreme (not 9-sided wait)
    base_pattern = {1: 3, 2: 1, 3: 1, 4: 1, 5: 1, 6: 1, 7: 1, 8: 1, 9: 3}
    temp_tiles = list(tiles)
    temp_tiles.remove(explanation.winning_tile)
    temp_values = sorted([t.value for t in temp_tiles if t.tile_type == suit])
    temp_counts = Counter(temp_values)

    if temp_counts == base_pattern:
        return False  # This is SUPREME, not regular

    return True


def check_103_quadruple_straights(explanation: HandExplanation) -> bool:
    """
    103: QUADRUPLE STRAIGHTS (一色四同順)
    4 straights, all same suit and numbers.
    """
    if not check_hand_format(explanation, 'SSSSp'):
        return False

    straights = get_straights(explanation)
    if len(straights) != 4:
        return False

    keys = [get_straight_key(s) for s in straights]
    return len(set(keys)) == 1


def check_104_grand_seven_stars(explanation: HandExplanation) -> bool:
    """
    104: GRAND SEVEN STARS (大七星)
    Seven Pairs made of all 7 types of honor tiles.
    """
    if explanation.pattern_type != '7P':
        return False

    tiles = get_all_tiles(explanation)
    if len(tiles) != 14:
        return False

    # Must be all honors
    if not all(t.is_honor() for t in tiles):
        return False

    # Must have all 7 types: 4 winds + 3 dragons
    tile_types = set((t.tile_type, t.value) for t in tiles)

    required = {
        (TileType.WIND, 1), (TileType.WIND, 2), (TileType.WIND, 3), (TileType.WIND, 4),
        (TileType.DRAGON, 1), (TileType.DRAGON, 2), (TileType.DRAGON, 3)
    }

    return tile_types == required


def check_105_seven_consecutive_pairs(explanation: HandExplanation) -> bool:
    """
    105: SEVEN CONSECUTIVE PAIRS (連七對)
    Seven Pairs of same suit, 7 consecutive numbers.
    """
    if explanation.pattern_type != '7P':
        return False

    tiles = get_all_tiles(explanation)
    suits = get_numbered_suits(tiles)

    if len(suits) != 1:
        return False

    suit = list(suits)[0]
    values = sorted(set(t.value for t in tiles))

    if len(values) != 7:
        return False

    # Check consecutive
    for i in range(6):
        if values[i + 1] - values[i] != 1:
            return False

    return True


def check_106_four_quads(explanation: HandExplanation) -> bool:
    """
    106: FOUR QUADS (四槓)
    4 Quads of any kind.
    """
    quads = get_quads(explanation)
    return len(quads) == 4


def check_107_major_four_winds(explanation: HandExplanation) -> bool:
    """
    107: MAJOR FOUR WINDS (大四喜)
    Triplets of all 4 winds.
    """
    if not check_hand_format(explanation, 'TTTTp'):
        return False

    triplets = get_triplets_and_quads(explanation)
    wind_values = set()

    for t in triplets:
        if is_wind_triplet(t):
            wind_values.add(t.tiles[0].value)

    return wind_values == {1, 2, 3, 4}


def check_108_minor_four_winds(explanation: HandExplanation) -> bool:
    """
    108: MINOR FOUR WINDS (小四喜)
    Triplets of 3 winds, 4th wind as pair.
    """
    triplets = get_triplets_and_quads(explanation)
    wind_triplet_values = set()

    for t in triplets:
        if is_wind_triplet(t):
            wind_triplet_values.add(t.tiles[0].value)

    if len(wind_triplet_values) != 3:
        return False

    # Check pair is the 4th wind
    if not explanation.pair:
        return False

    pair_tile = explanation.pair[0]
    if pair_tile.tile_type != TileType.WIND:
        return False

    missing_wind = {1, 2, 3, 4} - wind_triplet_values
    return pair_tile.value in missing_wind


def check_109_all_honors(explanation: HandExplanation) -> bool:
    """
    109: ALL HONORS (字一色)
    All Triplets or Seven Pairs, consists only of Honor tiles.
    """
    if explanation.pattern_type not in ('TTTTp', '7P'):
        return False

    tiles = get_all_tiles(explanation)
    return all(t.is_honor() for t in tiles)


def check_110_major_three_dragons(explanation: HandExplanation) -> bool:
    """
    110: MAJOR THREE DRAGONS (大三元)
    Triplets of all 3 dragons.
    """
    triplets = get_triplets_and_quads(explanation)
    dragon_values = set()

    for t in triplets:
        if is_dragon_triplet(t):
            dragon_values.add(t.tiles[0].value)

    return dragon_values == {1, 2, 3}


def check_111_blessing_of_heaven(explanation: HandExplanation) -> bool:
    """
    111: BLESSING OF HEAVEN (天和)
    Dealer wins with initial dealt 14 tiles.
    Marked with +BOH in additional notes.
    """
    return '+BOH' in explanation.additional_notes.upper()


def check_112_blessing_of_earth(explanation: HandExplanation) -> bool:
    """
    112: BLESSING OF EARTH (地和)
    Non-Dealer wins on first tile drawn.
    Marked with +BOE in additional notes.
    """
    return '+BOE' in explanation.additional_notes.upper()


def check_113_all_green(explanation: HandExplanation) -> bool:
    """
    113: ALL GREEN (綠一色)
    Only contains 23468b and G (Green dragon).
    """
    tiles = get_all_tiles(explanation)

    allowed = {
        (TileType.BAMBOO, 2), (TileType.BAMBOO, 3), (TileType.BAMBOO, 4),
        (TileType.BAMBOO, 6), (TileType.BAMBOO, 8), (TileType.DRAGON, 2)
    }

    for t in tiles:
        if (t.tile_type, t.value) not in allowed:
            return False

    return True


def check_114_all_terminals(explanation: HandExplanation) -> bool:
    """
    114: ALL TERMINALS (清老頭)
    All Triplets or Seven Pairs, only Terminal tiles (1 and 9).
    """
    if explanation.pattern_type not in ('TTTTp', '7P'):
        return False

    tiles = get_all_tiles(explanation)
    return all(t.is_terminal() for t in tiles)


def check_115_extended_pure_four_consecutive_triplets(explanation: HandExplanation) -> bool:
    """
    115: EXTENDED PURE FOUR CONSECUTIVE TRIPLETS (一色小步高全)
    Four Consecutive Triplets + pair of same suit with number right next to triplets.
    """
    if not check_hand_format(explanation, 'TTTTp'):
        return False

    triplets = get_triplets_and_quads(explanation)
    if len(triplets) != 4:
        return False

    # Get suit and values of triplets
    suits = set()
    values = []
    for t in triplets:
        if t.tiles[0].is_honor():
            return False
        suits.add(t.tiles[0].tile_type)
        values.append(t.tiles[0].value)

    if len(suits) != 1:
        return False

    suit = list(suits)[0]
    values.sort()

    # Check consecutive: each +1
    for i in range(3):
        if values[i + 1] - values[i] != 1:
            return False

    # Check pair is same suit and adjacent to triplets
    if not explanation.pair:
        return False

    pair_tile = explanation.pair[0]
    if pair_tile.tile_type != suit:
        return False

    # Pair value should be values[0]-1 or values[3]+1
    pair_val = pair_tile.value
    if pair_val == values[0] - 1 or pair_val == values[3] + 1:
        return True

    return False


def check_116_four_consecutive_triplets(explanation: HandExplanation) -> bool:
    """
    116: FOUR CONSECUTIVE TRIPLETS (一色四步高)
    4 triplets of same suit, each 1 higher than previous.
    """
    if not check_hand_format(explanation, 'TTTTp'):
        return False

    triplets = get_triplets_and_quads(explanation)
    if len(triplets) != 4:
        return False

    suits = set()
    values = []
    for t in triplets:
        if t.tiles[0].is_honor():
            return False
        suits.add(t.tiles[0].tile_type)
        values.append(t.tiles[0].value)

    if len(suits) != 1:
        return False

    values.sort()
    for i in range(3):
        if values[i + 1] - values[i] != 1:
            return False

    return True


def check_117_four_consecutive_straights(explanation: HandExplanation) -> bool:
    """
    117: FOUR CONSECUTIVE STRAIGHTS (一色四步順)
    4 straights of same suit, each 1 higher than previous.
    """
    if not check_hand_format(explanation, 'SSSSp'):
        return False

    straights = get_straights(explanation)
    if len(straights) != 4:
        return False

    suits = set()
    starts = []
    for s in straights:
        key = get_straight_key(s)
        suits.add(key[0])
        starts.append(key[1])

    if len(suits) != 1:
        return False

    starts.sort()
    for i in range(3):
        if starts[i + 1] - starts[i] != 1:
            return False

    return True


def check_118_two_consecutive_numbers(explanation: HandExplanation) -> bool:
    """
    118: TWO CONSECUTIVE NUMBERS (兩連刻)
    All Triplets or Seven Pairs, only two consecutive numbers.
    """
    if explanation.pattern_type not in ('TTTTp', '7P'):
        return False

    tiles = get_all_tiles(explanation)

    # Must be all numbered tiles
    if any(t.is_honor() for t in tiles):
        return False

    values = set(t.value for t in tiles)

    if len(values) != 2:
        return False

    values_list = sorted(values)
    return values_list[1] - values_list[0] == 1


def check_119_pure_dragon_party(explanation: HandExplanation) -> bool:
    """
    119: PURE DRAGON PARTY (一色雙龍會)
    Double Twin Straight of 123 and 789 of same suit, with pair of 5 from same suit.
    """
    if not check_hand_format(explanation, 'SSSSp'):
        return False

    straights = get_straights(explanation)
    if len(straights) != 4:
        return False

    # Group by suit
    suit_starts = {}
    for s in straights:
        key = get_straight_key(s)
        suit = key[0]
        start = key[1]
        if suit not in suit_starts:
            suit_starts[suit] = []
        suit_starts[suit].append(start)

    # Must be single suit
    if len(suit_starts) != 1:
        return False

    suit = list(suit_starts.keys())[0]
    starts = sorted(suit_starts[suit])

    # Must be [1, 1, 7, 7]
    if starts != [1, 1, 7, 7]:
        return False

    # Check pair is 5 of same suit
    if not explanation.pair:
        return False

    pair_tile = explanation.pair[0]
    return pair_tile.tile_type == suit and pair_tile.value == 5


def check_120_twin_straight_dragon_party(explanation: HandExplanation) -> bool:
    """
    120: TWIN STRAIGHT DRAGON PARTY (三色雙龍會)
    Double Twin Straight of 123 from one suit, 789 from another, pair of 5 from third.
    """
    if not check_hand_format(explanation, 'SSSSp'):
        return False

    straights = get_straights(explanation)
    if len(straights) != 4:
        return False

    # Group by suit
    suit_starts = {}
    for s in straights:
        key = get_straight_key(s)
        suit = key[0]
        start = key[1]
        if suit not in suit_starts:
            suit_starts[suit] = []
        suit_starts[suit].append(start)

    # Must be exactly 2 suits
    if len(suit_starts) != 2:
        return False

    suits = list(suit_starts.keys())
    starts0 = sorted(suit_starts[suits[0]])
    starts1 = sorted(suit_starts[suits[1]])

    # One suit has [1, 1], other has [7, 7]
    valid = (starts0 == [1, 1] and starts1 == [7, 7]) or (starts0 == [7, 7] and starts1 == [1, 1])

    if not valid:
        return False

    # Check pair is 5 from third suit
    if not explanation.pair:
        return False

    pair_tile = explanation.pair[0]
    if pair_tile.is_honor():
        return False

    third_suit = {TileType.BAMBOO, TileType.CHARACTER, TileType.DOT} - set(suits)
    if not third_suit:
        return False

    return pair_tile.tile_type in third_suit and pair_tile.value == 5


def check_121_all_waits_thirteen_orphans(explanation: HandExplanation) -> bool:
    """
    121: ALL WAITS THIRTEEN ORPHANS (十三么(十三面聽))
    Thirteen Orphans with 13-sided wait.
    """
    if explanation.pattern_type != '13O':
        return False

    # Check if winning tile makes it 13-sided wait
    # 13-sided wait means before winning, hand was exactly one of each terminal/honor
    tiles = get_all_tiles(explanation)

    # Remove winning tile once
    temp_tiles = list(tiles)
    temp_tiles.remove(explanation.winning_tile)

    # Should have exactly 13 unique terminal/honor tiles
    required = {
        Tile(TileType.CHARACTER, 1), Tile(TileType.CHARACTER, 9),
        Tile(TileType.DOT, 1), Tile(TileType.DOT, 9),
        Tile(TileType.BAMBOO, 1), Tile(TileType.BAMBOO, 9),
        Tile(TileType.WIND, 1), Tile(TileType.WIND, 2),
        Tile(TileType.WIND, 3), Tile(TileType.WIND, 4),
        Tile(TileType.DRAGON, 1), Tile(TileType.DRAGON, 2), Tile(TileType.DRAGON, 3)
    }

    return set(temp_tiles) == required


def check_122_thirteen_orphans(explanation: HandExplanation) -> bool:
    """
    122: THIRTEEN ORPHANS (十三么)
    One pair of terminal/honor + one of each other terminal/honor.
    """
    return explanation.pattern_type == '13O'


def check_123_triple_premium_seven_pairs(explanation: HandExplanation) -> bool:
    """
    123: TRIPLE PREMIUM SEVEN PAIRS (三連貴七對)
    Seven Pairs with 3x "Four of a kind".
    """
    if explanation.pattern_type != '7P':
        return False

    tiles = get_all_tiles(explanation)
    tile_counts = Counter((t.tile_type, t.value) for t in tiles)

    # Count how many tiles appear 4 times
    four_of_kinds = sum(1 for count in tile_counts.values() if count == 4)

    return four_of_kinds >= 3


def check_124_four_concealed_triplets(explanation: HandExplanation) -> bool:
    """
    124: FOUR CONCEALED TRIPLETS (四暗刻)
    All Triplets, all 4 triplets concealed.
    """
    if not check_hand_format(explanation, 'TTTTp'):
        return False

    concealed = get_concealed_triplets(explanation)
    return len(concealed) == 4


# =============================================================================
# FAN DETECTION FUNCTIONS - FLUSH/NUMBER PATTERNS (201-218)
# =============================================================================

def check_201_pure_flush(explanation: HandExplanation) -> bool:
    """
    201: Pure Flush (清一色)
    Only one numbered suit, no honors.
    """
    tiles = get_all_tiles(explanation)

    if any(t.is_honor() for t in tiles):
        return False

    suits = get_numbered_suits(tiles)
    return len(suits) == 1


def check_202_mixed_flush(explanation: HandExplanation) -> bool:
    """
    202: Mixed Flush (混一色)
    Only one numbered suit plus honor tiles.
    """
    tiles = get_all_tiles(explanation)

    has_honors = any(t.is_honor() for t in tiles)
    numbered_tiles = [t for t in tiles if not t.is_honor()]

    if not has_honors or not numbered_tiles:
        return False

    suits = set(t.tile_type for t in numbered_tiles)
    return len(suits) == 1


def check_203_pure_outside_hand(explanation: HandExplanation) -> bool:
    """
    203: Pure Outside Hand (純全帶么)
    All 4 groups involve terminal tiles, pair is terminal.
    """
    if explanation.pattern_type in ('7P', '13O'):
        return False

    # Check all groups contain terminal
    for group in explanation.groups:
        has_terminal = any(t.is_terminal() for t in group.tiles)
        if not has_terminal:
            return False

    # Check pair is terminal
    if not explanation.pair:
        return False

    return explanation.pair[0].is_terminal()


def check_204_mixed_outside_hand(explanation: HandExplanation) -> bool:
    """
    204: Mixed Outside Hand (混全帶么)
    All 4 groups involve terminal or honor, pair is terminal or honor.
    """
    if explanation.pattern_type in ('7P', '13O'):
        return False

    for group in explanation.groups:
        has_terminal_or_honor = any(t.is_terminal_or_honor() for t in group.tiles)
        if not has_terminal_or_honor:
            return False

    if not explanation.pair:
        return False

    return explanation.pair[0].is_terminal_or_honor()


def check_205_all_terminals_and_honors(explanation: HandExplanation) -> bool:
    """
    205: All Terminals and Honors (混老頭)
    All Triplets or Seven Pairs, only terminal or honor tiles.
    """
    if explanation.pattern_type not in ('TTTTp', '7P'):
        return False

    tiles = get_all_tiles(explanation)
    return all(t.is_terminal_or_honor() for t in tiles)


def check_206_5_in_all_groups(explanation: HandExplanation) -> bool:
    """
    206: 5 in All Groups (全帶五)
    All 4 groups involve 5, pair is 5.
    """
    if explanation.pattern_type in ('7P', '13O'):
        return False

    for group in explanation.groups:
        has_five = any(not t.is_honor() and t.value == 5 for t in group.tiles)
        if not has_five:
            return False

    if not explanation.pair:
        return False

    pair_tile = explanation.pair[0]
    return not pair_tile.is_honor() and pair_tile.value == 5


def check_207_3_in_all_groups(explanation: HandExplanation) -> bool:
    """
    207: 3 in All Groups (全帶三)
    All 4 groups involve 3, pair is 3.
    """
    if explanation.pattern_type in ('7P', '13O'):
        return False

    for group in explanation.groups:
        has_three = any(not t.is_honor() and t.value == 3 for t in group.tiles)
        if not has_three:
            return False

    if not explanation.pair:
        return False

    pair_tile = explanation.pair[0]
    return not pair_tile.is_honor() and pair_tile.value == 3


def check_208_4_in_all_groups(explanation: HandExplanation) -> bool:
    """
    208: 4 in All Groups (全帶四)
    All 4 groups involve 4, pair is 4.
    """
    if explanation.pattern_type in ('7P', '13O'):
        return False

    for group in explanation.groups:
        has_four = any(not t.is_honor() and t.value == 4 for t in group.tiles)
        if not has_four:
            return False

    if not explanation.pair:
        return False

    pair_tile = explanation.pair[0]
    return not pair_tile.is_honor() and pair_tile.value == 4


def check_209_6_in_all_groups(explanation: HandExplanation) -> bool:
    """
    209: 6 in All Groups (全帶六)
    All 4 groups involve 6, pair is 6.
    """
    if explanation.pattern_type in ('7P', '13O'):
        return False

    for group in explanation.groups:
        has_six = any(not t.is_honor() and t.value == 6 for t in group.tiles)
        if not has_six:
            return False

    if not explanation.pair:
        return False

    pair_tile = explanation.pair[0]
    return not pair_tile.is_honor() and pair_tile.value == 6


def check_210_7_in_all_groups(explanation: HandExplanation) -> bool:
    """
    210: 7 in All Groups (全帶七)
    All 4 groups involve 7, pair is 7.
    """
    if explanation.pattern_type in ('7P', '13O'):
        return False

    for group in explanation.groups:
        has_seven = any(not t.is_honor() and t.value == 7 for t in group.tiles)
        if not has_seven:
            return False

    if not explanation.pair:
        return False

    pair_tile = explanation.pair[0]
    return not pair_tile.is_honor() and pair_tile.value == 7


def check_211_even_tiles(explanation: HandExplanation) -> bool:
    """
    211: Even Tiles (全雙)
    All Triplets or Seven Pairs, only 2, 4, 6, 8.
    """
    if explanation.pattern_type not in ('TTTTp', '7P'):
        return False

    tiles = get_all_tiles(explanation)

    for t in tiles:
        if t.is_honor():
            return False
        if t.value not in (2, 4, 6, 8):
            return False

    return True


def check_212_odd_tiles(explanation: HandExplanation) -> bool:
    """
    212: Odd Tiles (全單)
    All Triplets or Seven Pairs, only 1, 3, 5, 7, 9.
    """
    if explanation.pattern_type not in ('TTTTp', '7P'):
        return False

    tiles = get_all_tiles(explanation)

    for t in tiles:
        if t.is_honor():
            return False
        if t.value not in (1, 3, 5, 7, 9):
            return False

    return True


def check_213_three_consecutive_numbers(explanation: HandExplanation) -> bool:
    """
    213: Three consecutive numbers (三連刻)
    Hand contains only 3 consecutive numbers.
    """
    tiles = get_all_tiles(explanation)

    if any(t.is_honor() for t in tiles):
        return False

    values = set(t.value for t in tiles)

    if len(values) != 3:
        return False

    values_list = sorted(values)
    return values_list[1] - values_list[0] == 1 and values_list[2] - values_list[1] == 1


def check_214_four_consecutive_numbers(explanation: HandExplanation) -> bool:
    """
    214: Four consecutive numbers (四連刻)
    Hand contains only 4 consecutive numbers.
    """
    tiles = get_all_tiles(explanation)

    if any(t.is_honor() for t in tiles):
        return False

    values = set(t.value for t in tiles)

    if len(values) != 4:
        return False

    values_list = sorted(values)
    for i in range(3):
        if values_list[i + 1] - values_list[i] != 1:
            return False

    return True


def check_215_simpler_hand(explanation: HandExplanation) -> bool:
    """
    215: Simpler Hand (斷二八)
    Hand only contains 3-7.
    """
    tiles = get_all_tiles(explanation)

    for t in tiles:
        if t.is_honor():
            return False
        if t.value not in (3, 4, 5, 6, 7):
            return False

    return True


def check_216_simple_hand(explanation: HandExplanation) -> bool:
    """
    216: Simple Hand (斷么)
    Hand contains no terminals or honors (only 2-8).
    """
    tiles = get_all_tiles(explanation)

    for t in tiles:
        if t.is_terminal_or_honor():
            return False

    return True


def check_217_reversible_tiles(explanation: HandExplanation) -> bool:
    """
    217: Reversible Tiles (牌不靠)
    Hand only contains rotationally symmetric tiles: 245689b, 1234589d, Wh.
    """
    tiles = get_all_tiles(explanation)

    allowed = {
        (TileType.BAMBOO, 2), (TileType.BAMBOO, 4), (TileType.BAMBOO, 5),
        (TileType.BAMBOO, 6), (TileType.BAMBOO, 8), (TileType.BAMBOO, 9),
        (TileType.DOT, 1), (TileType.DOT, 2), (TileType.DOT, 3),
        (TileType.DOT, 4), (TileType.DOT, 5), (TileType.DOT, 8), (TileType.DOT, 9),
        (TileType.DRAGON, 1)  # Wh = White dragon
    }

    for t in tiles:
        if (t.tile_type, t.value) not in allowed:
            return False

    return True


def check_218_all_five_types(explanation: HandExplanation) -> bool:
    """
    218: All Five Types (五門齊)
    Hand includes Bamboo, Character, Dots, Wind, and Dragon.
    """
    tiles = get_all_tiles(explanation)

    has_bamboo = any(t.tile_type == TileType.BAMBOO for t in tiles)
    has_character = any(t.tile_type == TileType.CHARACTER for t in tiles)
    has_dot = any(t.tile_type == TileType.DOT for t in tiles)
    has_wind = any(t.tile_type == TileType.WIND for t in tiles)
    has_dragon = any(t.tile_type == TileType.DRAGON for t in tiles)

    return has_bamboo and has_character and has_dot and has_wind and has_dragon


# =============================================================================
# FAN DETECTION FUNCTIONS - QUAD/TRIPLET PATTERNS (251-265)
# =============================================================================

def check_251_three_quads(explanation: HandExplanation) -> bool:
    """
    251: Three Quads (三槓)
    3 Quads.
    """
    quads = get_quads(explanation)
    return len(quads) == 3


def check_252_two_quads(explanation: HandExplanation) -> bool:
    """
    252: Two Quads (雙槓)
    2 Quads.
    """
    quads = get_quads(explanation)
    return len(quads) == 2


def check_253_one_quad(explanation: HandExplanation) -> bool:
    """
    253: One Quad (一槓)
    1 Quad.
    """
    quads = get_quads(explanation)
    return len(quads) == 1


def check_254_three_concealed_triplets(explanation: HandExplanation) -> bool:
    """
    254: Three concealed triplets (三暗刻)
    3 concealed triplets.
    """
    concealed = get_concealed_triplets(explanation)
    return len(concealed) == 3


def check_255_three_wind_triplets(explanation: HandExplanation) -> bool:
    """
    255: Three Wind Triplets (三風刻)
    3 Wind triplets.
    """
    triplets = get_triplets_and_quads(explanation)
    wind_count = sum(1 for t in triplets if is_wind_triplet(t))
    return wind_count == 3


def check_256_minor_three_winds(explanation: HandExplanation) -> bool:
    """
    256: Minor Three Winds (小三風)
    2 Wind triplets + Wind pair.
    """
    triplets = get_triplets_and_quads(explanation)
    wind_count = sum(1 for t in triplets if is_wind_triplet(t))

    if wind_count != 2:
        return False

    if not explanation.pair:
        return False

    return explanation.pair[0].tile_type == TileType.WIND


def check_257_two_wind_triplets(explanation: HandExplanation) -> bool:
    """
    257: Two Wind Triplets (雙風刻)
    2 Wind triplets.
    """
    triplets = get_triplets_and_quads(explanation)
    wind_count = sum(1 for t in triplets if is_wind_triplet(t))
    return wind_count == 2


def check_258_wind_triplet(explanation: HandExplanation) -> bool:
    """
    258: Wind Triplet (風刻)
    1 Wind triplet.
    """
    triplets = get_triplets_and_quads(explanation)
    wind_count = sum(1 for t in triplets if is_wind_triplet(t))
    return wind_count == 1


def check_259_minor_three_dragons(explanation: HandExplanation) -> bool:
    """
    259: Minor Three Dragons (小三元)
    2 Dragon triplets + Dragon pair.
    """
    triplets = get_triplets_and_quads(explanation)
    dragon_count = sum(1 for t in triplets if is_dragon_triplet(t))

    if dragon_count != 2:
        return False

    if not explanation.pair:
        return False

    return explanation.pair[0].tile_type == TileType.DRAGON


def check_260_two_dragon_triplets(explanation: HandExplanation) -> bool:
    """
    260: Two Dragon Triplets (雙箭刻)
    2 Dragon triplets.
    """
    triplets = get_triplets_and_quads(explanation)
    dragon_count = sum(1 for t in triplets if is_dragon_triplet(t))
    return dragon_count == 2


def check_261_dragon_triplet(explanation: HandExplanation) -> bool:
    """
    261: Dragon Triplet (箭刻)
    1 Dragon triplet.
    """
    triplets = get_triplets_and_quads(explanation)
    dragon_count = sum(1 for t in triplets if is_dragon_triplet(t))
    return dragon_count == 1


def check_262_triple_triplets(explanation: HandExplanation) -> bool:
    """
    262: Triple Triplets (三同刻)
    3 triplets of different suits with same number.
    """
    triplets = get_triplets_and_quads(explanation)

    # Group by value
    value_suits: Dict[int, Set[TileType]] = {}
    for t in triplets:
        if t.tiles[0].is_honor():
            continue
        val = t.tiles[0].value
        suit = t.tiles[0].tile_type
        if val not in value_suits:
            value_suits[val] = set()
        value_suits[val].add(suit)

    # Check if any value has 3 different suits
    for val, suits in value_suits.items():
        if len(suits) >= 3:
            return True

    return False


def check_263_minor_triple_triplets(explanation: HandExplanation) -> bool:
    """
    263: Minor Triple Triplets (小三同刻)
    2 triplets of different suits with same number + pair of same number from third suit.
    """
    triplets = get_triplets_and_quads(explanation)

    # Group triplets by value
    value_suits: Dict[int, Set[TileType]] = {}
    for t in triplets:
        if t.tiles[0].is_honor():
            continue
        val = t.tiles[0].value
        suit = t.tiles[0].tile_type
        if val not in value_suits:
            value_suits[val] = set()
        value_suits[val].add(suit)

    if not explanation.pair:
        return False

    pair_tile = explanation.pair[0]
    if pair_tile.is_honor():
        return False

    pair_val = pair_tile.value
    pair_suit = pair_tile.tile_type

    # Check if pair value has 2 triplets of different suits
    if pair_val in value_suits and len(value_suits[pair_val]) >= 2:
        # And pair suit is different from triplet suits
        if pair_suit not in value_suits[pair_val]:
            return True

    return False


def check_264_three_consecutive_triplets(explanation: HandExplanation) -> bool:
    """
    264: Three Consecutive Triplets (一色三步高)
    3 triplets of same suit, each 1 higher than previous.
    """
    triplets = get_triplets_and_quads(explanation)

    # Group by suit
    suit_values: Dict[TileType, List[int]] = {}
    for t in triplets:
        if t.tiles[0].is_honor():
            continue
        suit = t.tiles[0].tile_type
        val = t.tiles[0].value
        if suit not in suit_values:
            suit_values[suit] = []
        suit_values[suit].append(val)

    # Check each suit for 3 consecutive
    for suit, values in suit_values.items():
        if len(values) >= 3:
            values.sort()
            for i in range(len(values) - 2):
                if values[i + 1] - values[i] == 1 and values[i + 2] - values[i + 1] == 1:
                    return True

    return False


def check_265_mixed_three_consecutive_triplets(explanation: HandExplanation) -> bool:
    """
    265: Mixed Three Consecutive Triplets (三色三步高)
    3 triplets of different suits, each 1 higher than previous.
    """
    triplets = get_triplets_and_quads(explanation)

    # Get all non-honor triplet values with suits
    triplet_data = []
    for t in triplets:
        if t.tiles[0].is_honor():
            continue
        triplet_data.append((t.tiles[0].value, t.tiles[0].tile_type))

    if len(triplet_data) < 3:
        return False

    # Check all combinations of 3 triplets
    from itertools import combinations
    for combo in combinations(triplet_data, 3):
        values = sorted([c[0] for c in combo])
        suits = set(c[1] for c in combo)

        # Must be 3 different suits
        if len(suits) != 3:
            continue

        # Must be consecutive values
        if values[1] - values[0] == 1 and values[2] - values[1] == 1:
            return True

    return False


# =============================================================================
# FAN DETECTION FUNCTIONS - STRAIGHT PATTERNS (301-309)
# =============================================================================

def check_301_mixed_dragon_party(explanation: HandExplanation) -> bool:
    """
    301: Mixed Dragon Party (三色雙龍會)
    Two groups of 123 and 789 from different suits, pair of 5 from third suit.
    """
    if not check_hand_format(explanation, 'SSSSp'):
        return False

    straights = get_straights(explanation)
    if len(straights) != 4:
        return False

    suit_starts = {}
    for s in straights:
        key = get_straight_key(s)
        suit = key[0]
        start = key[1]
        if suit not in suit_starts:
            suit_starts[suit] = []
        suit_starts[suit].append(start)

    # Must be exactly 2 suits
    if len(suit_starts) != 2:
        return False

    suits = list(suit_starts.keys())

    # Each suit should have two straights: one starting 1 and one starting 7
    for suit in suits:
        starts = sorted(suit_starts[suit])
        if starts != [1, 7]:
            return False

    # Pair must be 5 from third suit
    if not explanation.pair:
        return False

    pair_tile = explanation.pair[0]
    if pair_tile.is_honor():
        return False

    third_suit = {TileType.BAMBOO, TileType.CHARACTER, TileType.DOT} - set(suits)
    return pair_tile.tile_type in third_suit and pair_tile.value == 5


def check_302_four_chained_straights(explanation: HandExplanation) -> bool:
    """
    302: Four Chained Straights (一色四連環)
    4 straights of same suit, each 2 higher than previous.
    """
    if not check_hand_format(explanation, 'SSSSp'):
        return False

    straights = get_straights(explanation)
    if len(straights) != 4:
        return False

    suits = set()
    starts = []
    for s in straights:
        key = get_straight_key(s)
        suits.add(key[0])
        starts.append(key[1])

    if len(suits) != 1:
        return False

    starts.sort()
    # Each must be 2 higher: e.g., 1, 3, 5, 7
    for i in range(3):
        if starts[i + 1] - starts[i] != 2:
            return False

    return True


def check_303_three_consecutive_straights(explanation: HandExplanation) -> bool:
    """
    303: Three Consecutive Straights (一色三步順)
    3 straights of same suit, each 1 higher than previous.
    """
    straights = get_straights(explanation)
    if len(straights) < 3:
        return False

    # Group by suit
    suit_starts: Dict[TileType, List[int]] = {}
    for s in straights:
        key = get_straight_key(s)
        suit = key[0]
        start = key[1]
        if suit not in suit_starts:
            suit_starts[suit] = []
        suit_starts[suit].append(start)

    # Check each suit for 3 consecutive
    for suit, starts in suit_starts.items():
        if len(starts) >= 3:
            starts.sort()
            for i in range(len(starts) - 2):
                if starts[i + 1] - starts[i] == 1 and starts[i + 2] - starts[i + 1] == 1:
                    return True

    return False


def check_304_dragon_straight(explanation: HandExplanation) -> bool:
    """
    304: Dragon Straight (清龍)
    123, 456, 789 of same suit.
    """
    straights = get_straights(explanation)
    if len(straights) < 3:
        return False

    # Group by suit
    suit_starts: Dict[TileType, Set[int]] = {}
    for s in straights:
        key = get_straight_key(s)
        suit = key[0]
        start = key[1]
        if suit not in suit_starts:
            suit_starts[suit] = set()
        suit_starts[suit].add(start)

    # Check if any suit has 1, 4, 7
    for suit, starts in suit_starts.items():
        if {1, 4, 7}.issubset(starts):
            return True

    return False


def check_305_mixed_dragon_straight(explanation: HandExplanation) -> bool:
    """
    305: Mixed Dragon Straight (花龍)
    123, 456, 789 of 3 different suits.
    """
    straights = get_straights(explanation)
    if len(straights) < 3:
        return False

    has_123 = {}
    has_456 = {}
    has_789 = {}

    for s in straights:
        key = get_straight_key(s)
        suit = key[0]
        start = key[1]

        if start == 1:
            has_123[suit] = True
        elif start == 4:
            has_456[suit] = True
        elif start == 7:
            has_789[suit] = True

    # Check if we can form dragon from 3 different suits
    for s1 in has_123:
        for s2 in has_456:
            for s3 in has_789:
                if len({s1, s2, s3}) == 3:
                    return True

    return False


def check_306_triple_straights(explanation: HandExplanation) -> bool:
    """
    306: Triple Straights (一色三同順)
    3 straights of same suit and number.
    """
    straights = get_straights(explanation)
    if len(straights) < 3:
        return False

    key_counts = Counter(get_straight_key(s) for s in straights)

    for key, count in key_counts.items():
        if count >= 3:
            return True

    return False


def check_307_mixed_triple_straights(explanation: HandExplanation) -> bool:
    """
    307: Mixed Triple Straights (三色三同順)
    3 straights of different suits with same number.
    """
    straights = get_straights(explanation)
    if len(straights) < 3:
        return False

    # Group by start value
    start_suits: Dict[int, Set[TileType]] = {}
    for s in straights:
        key = get_straight_key(s)
        start = key[1]
        suit = key[0]
        if start not in start_suits:
            start_suits[start] = set()
        start_suits[start].add(suit)

    # Check if any start has 3 different suits
    for start, suits in start_suits.items():
        if len(suits) >= 3:
            return True

    return False


def check_308_double_twin_straights(explanation: HandExplanation) -> bool:
    """
    308: Double Twin Straights (二般高)
    Two Twin Straights.
    """
    if not check_hand_format(explanation, 'SSSSp'):
        return False

    straights = get_straights(explanation)
    if len(straights) != 4:
        return False

    key_counts = Counter(get_straight_key(s) for s in straights)

    # Need exactly 2 distinct straights, each appearing exactly twice
    # OR 1 straight appearing 4 times
    if len(key_counts) == 2 and all(c == 2 for c in key_counts.values()):
        return True
    if len(key_counts) == 1 and list(key_counts.values())[0] == 4:
        return True

    return False


def check_309_twin_straights(explanation: HandExplanation) -> bool:
    """
    309: Twin Straights (一般高)
    2 straights of same suit and number.
    """
    straights = get_straights(explanation)
    if len(straights) < 2:
        return False

    key_counts = Counter(get_straight_key(s) for s in straights)

    for key, count in key_counts.items():
        if count >= 2:
            return True

    return False


# =============================================================================
# FAN DETECTION FUNCTIONS - HAND TYPES (401-413)
# =============================================================================

def check_401_all_triplets(explanation: HandExplanation) -> bool:
    """
    401: All Triplets (對對和)
    All 4 groups are triplets/quads.
    """
    return explanation.pattern_type == 'TTTTp'


def check_402_double_premium_seven_pairs(explanation: HandExplanation) -> bool:
    """
    402: Double Premium Seven Pairs (雙龍貴七對)
    Seven Pairs with 2x "Four of a kind".
    """
    if explanation.pattern_type != '7P':
        return False

    tiles = get_all_tiles(explanation)
    tile_counts = Counter((t.tile_type, t.value) for t in tiles)

    four_of_kinds = sum(1 for count in tile_counts.values() if count == 4)
    return four_of_kinds >= 2


def check_403_premium_seven_pairs(explanation: HandExplanation) -> bool:
    """
    403: Premium Seven Pairs (龍貴七對)
    Seven Pairs with 1x "Four of a kind".
    """
    if explanation.pattern_type != '7P':
        return False

    tiles = get_all_tiles(explanation)
    tile_counts = Counter((t.tile_type, t.value) for t in tiles)

    four_of_kinds = sum(1 for count in tile_counts.values() if count == 4)
    return four_of_kinds >= 1


def check_404_seven_pairs(explanation: HandExplanation) -> bool:
    """
    404: Seven Pairs (七對)
    Seven different pairs.
    """
    return explanation.pattern_type == '7P'


def check_405_pairs_or_better(explanation: HandExplanation) -> bool:
    """
    405: Pairs or Better (無獨牌落)
    All tiles appeared more than once.
    """
    tiles = get_all_tiles(explanation)
    tile_counts = Counter((t.tile_type, t.value) for t in tiles)

    return all(count >= 2 for count in tile_counts.values())


def check_406_mirrored_tiles(explanation: HandExplanation) -> bool:
    """
    406: Mirrored Tiles (對同)
    4 groups from 2 suits, 2 groups each. Each group in one suit has matching group in other.
    """
    if explanation.pattern_type in ('7P', '13O'):
        return False

    groups = explanation.groups
    if len(groups) != 4:
        return False

    # Group by suit
    suit_groups: Dict[TileType, List[Group]] = {}
    for g in groups:
        suit = g.tiles[0].tile_type
        if suit not in suit_groups:
            suit_groups[suit] = []
        suit_groups[suit].append(g)

    # Must be exactly 2 suits
    if len(suit_groups) != 2:
        return False

    suits = list(suit_groups.keys())
    groups0 = suit_groups[suits[0]]
    groups1 = suit_groups[suits[1]]

    # Must have 2 groups each
    if len(groups0) != 2 or len(groups1) != 2:
        return False

    # Each group in suit0 must have matching group in suit1
    def get_group_signature(g: Group) -> Tuple[str, Tuple[int, ...]]:
        # A quad contains the same three-tile pattern as a triplet.  The
        # mirrored-tiles fan compares the pattern, not the exposed count.
        group_type = 'triplet' if g.group_type in ('triplet', 'quad') else g.group_type
        return (group_type, tuple(sorted(t.value for t in g.tiles))[:3])

    sigs0 = sorted([get_group_signature(g) for g in groups0])
    sigs1 = sorted([get_group_signature(g) for g in groups1])

    return sigs0 == sigs1


def check_407_win_after_quad(explanation: HandExplanation) -> bool:
    """
    407: Win After a Quad (嶺上開花)
    Win after declaring a Quad. Marked with +AQ.
    """
    return '+AQ' in explanation.additional_notes.upper()


def check_408_robbing_quad(explanation: HandExplanation) -> bool:
    """
    408: Robbing a Quad (搶槓)
    Win when another player upgrades triplet to quad. Marked with +RQ.
    """
    return '+RQ' in explanation.additional_notes.upper()


def check_409_grab_the_moon(explanation: HandExplanation) -> bool:
    """
    409: Grab the Moon (海底撈月)
    Win on final turn. Marked with +GTM or +LT.
    """
    notes = explanation.additional_notes.upper()
    return '+GTM' in notes or '+LT' in notes


def check_410_concealed_hand(explanation: HandExplanation) -> bool:
    """
    410: Concealed Hand (門前清)
    Win without any calls, or all calls being concealed quad.
    """
    for g in explanation.groups:
        if g.is_call and not g.is_concealed_quad:
            return False
    return True


def check_411_bless_of_eastern_wind(explanation: HandExplanation) -> bool:
    """
    411: Bless of Eastern Wind (天聽)
    Tenpai from initial dealt tiles (non-dealer). Marked with +EW.
    """
    notes = explanation.additional_notes.upper()
    return '+EW' in notes


def check_412_declare_waiting(explanation: HandExplanation) -> bool:
    """
    412: Declare Waiting Hand (立聽)
    Declare waiting when concealed. Marked with +DW.
    """
    return '+DW' in explanation.additional_notes.upper()


def check_413_four_calls(explanation: HandExplanation) -> bool:
    """
    413: Four Calls (四副露成和)
    Win after 4 calls.
    """
    if explanation.pattern_type in ('13O', '7P'):
        return False

    calls = get_calls(explanation)
    return len(calls) == 4


def check_501_self_drawn(explanation: HandExplanation) -> bool:
    """
    501: Self-drawn (自摸)
    Win by self-drawn.
    """
    return explanation.is_self_drawn


# =============================================================================
# FAN DETECTION REGISTRY
# =============================================================================

FAN_CHECKERS = {
    # Excellence Fans (101-124)
    101: check_101_supreme_nine_gates,
    102: check_102_nine_gates,
    103: check_103_quadruple_straights,
    104: check_104_grand_seven_stars,
    105: check_105_seven_consecutive_pairs,
    106: check_106_four_quads,
    107: check_107_major_four_winds,
    108: check_108_minor_four_winds,
    109: check_109_all_honors,
    110: check_110_major_three_dragons,
    111: check_111_blessing_of_heaven,
    112: check_112_blessing_of_earth,
    113: check_113_all_green,
    114: check_114_all_terminals,
    115: check_115_extended_pure_four_consecutive_triplets,
    116: check_116_four_consecutive_triplets,
    117: check_117_four_consecutive_straights,
    118: check_118_two_consecutive_numbers,
    119: check_119_pure_dragon_party,
    120: check_120_twin_straight_dragon_party,
    121: check_121_all_waits_thirteen_orphans,
    122: check_122_thirteen_orphans,
    123: check_123_triple_premium_seven_pairs,
    124: check_124_four_concealed_triplets,

    # Flush/Number Patterns (201-218)
    201: check_201_pure_flush,
    202: check_202_mixed_flush,
    203: check_203_pure_outside_hand,
    204: check_204_mixed_outside_hand,
    205: check_205_all_terminals_and_honors,
    206: check_206_5_in_all_groups,
    207: check_207_3_in_all_groups,
    208: check_208_4_in_all_groups,
    209: check_209_6_in_all_groups,
    210: check_210_7_in_all_groups,
    211: check_211_even_tiles,
    212: check_212_odd_tiles,
    213: check_213_three_consecutive_numbers,
    214: check_214_four_consecutive_numbers,
    215: check_215_simpler_hand,
    216: check_216_simple_hand,
    217: check_217_reversible_tiles,
    218: check_218_all_five_types,

    # Quad/Triplet Patterns (251-265)
    251: check_251_three_quads,
    252: check_252_two_quads,
    253: check_253_one_quad,
    254: check_254_three_concealed_triplets,
    255: check_255_three_wind_triplets,
    256: check_256_minor_three_winds,
    257: check_257_two_wind_triplets,
    258: check_258_wind_triplet,
    259: check_259_minor_three_dragons,
    260: check_260_two_dragon_triplets,
    261: check_261_dragon_triplet,
    262: check_262_triple_triplets,
    263: check_263_minor_triple_triplets,
    264: check_264_three_consecutive_triplets,
    265: check_265_mixed_three_consecutive_triplets,

    # Straight Patterns (301-309)
    301: check_301_mixed_dragon_party,
    302: check_302_four_chained_straights,
    303: check_303_three_consecutive_straights,
    304: check_304_dragon_straight,
    305: check_305_mixed_dragon_straight,
    306: check_306_triple_straights,
    307: check_307_mixed_triple_straights,
    308: check_308_double_twin_straights,
    309: check_309_twin_straights,

    # Hand Types (401-413)
    401: check_401_all_triplets,
    402: check_402_double_premium_seven_pairs,
    403: check_403_premium_seven_pairs,
    404: check_404_seven_pairs,
    405: check_405_pairs_or_better,
    406: check_406_mirrored_tiles,
    407: check_407_win_after_quad,
    408: check_408_robbing_quad,
    409: check_409_grab_the_moon,
    410: check_410_concealed_hand,
    411: check_411_bless_of_eastern_wind,
    412: check_412_declare_waiting,
    413: check_413_four_calls,

    # Self-drawn (501)
    501: check_501_self_drawn,
}


# =============================================================================
# SCORING CALCULATION
# =============================================================================

def detect_fans(explanation: HandExplanation, fans: Dict[int, Fan]) -> List[Tuple[int, Fan]]:
    """
    Detect all applicable fans for a hand explanation.
    Returns list of (fan_id, fan) tuples.
    """
    achieved = []

    for fan_id, fan in fans.items():
        checker = FAN_CHECKERS.get(fan_id)
        if checker is None:
            continue

        # Check hand format compatibility
        if fan.hand_format and not check_hand_format(explanation, fan.hand_format):
            continue

        # Run the checker
        if checker(explanation):
            achieved.append((fan_id, fan))

    return achieved


def apply_overrides(achieved: List[Tuple[int, Fan]], all_overrides: Dict[int, Set[int]]) -> List[Tuple[int, Fan]]:
    """
    Remove fans that are overridden by higher-value fans.
    Uses precomputed recursive overrides.
    """
    achieved_ids = set(fid for fid, _ in achieved)

    # Collect all overridden fan IDs
    overridden_ids = set()
    for fan_id, fan in achieved:
        # Add all recursively overridden fans
        overridden_ids.update(all_overrides.get(fan_id, set()))

    # Filter out overridden fans
    return [(fid, fan) for fid, fan in achieved if fid not in overridden_ids]


def calculate_score(explanation: HandExplanation, fans: Dict[int, Fan] = None) -> ScoringResult:
    """
    Calculate the total score for a hand explanation.

    Scoring rules:
    1. Excellence Fan achieved:
       - All fans < 500 pts are overridden (ignored)
       - Main fan (highest value) is applied normally
       - Other excellence fans are halved (round down to 100, min 300)

    2. No Excellence Fan:
       - Sum all applicable fans
       - If sum > 3000, excess is halved (round down to 100)
    """
    if fans is None:
        fans = load_fans_from_csv()

    # Compute recursive overrides
    all_overrides = compute_recursive_overrides(fans)

    # Detect all applicable fans
    achieved = detect_fans(explanation, fans)

    # Apply explicit override rules
    achieved = apply_overrides(achieved, all_overrides)

    if not achieved:
        return ScoringResult(
            explanation=explanation,
            achieved_fans=[],
            total_score=0,
            is_excellence=False
        )

    # Check for excellence fans
    excellence_fans = [(fid, fan) for fid, fan in achieved if fan.is_excellence]

    achieved_results = []
    total = 0

    if excellence_fans:
        # Case 1: Excellence Fan achieved
        # Excellence fans override everything < 500 pts
        achieved = [(fid, fan) for fid, fan in achieved if fan.value >= 500]

        # Sort by value descending, then by ID ascending
        achieved.sort(key=lambda x: (-x[1].value, x[0]))

        # Main fan is the one with highest value
        main_fan_id, main_fan = achieved[0]
        main_score = main_fan.value
        achieved_results.append(AchievedFan(fan=main_fan, score=main_score, is_main=True))
        total += main_score

        # Other fans >= 500 are halved (round down to 100, min 300)
        for fid, fan in achieved[1:]:
            halved = (fan.value // 2) // 100 * 100
            halved = max(halved, 300)
            achieved_results.append(AchievedFan(fan=fan, score=halved, is_main=False))
            total += halved

        return ScoringResult(
            explanation=explanation,
            achieved_fans=achieved_results,
            total_score=total,
            is_excellence=True
        )
    else:
        # Case 2: No Excellence Fan
        # Sort by value descending
        achieved.sort(key=lambda x: (-x[1].value, x[0]))

        raw_total = 0
        for fid, fan in achieved:
            achieved_results.append(AchievedFan(fan=fan, score=fan.value, is_main=False))
            raw_total += fan.value

        # Apply cap: if > 3000, excess is halved (round down to 100)
        if raw_total <= 3000:
            total = raw_total
        else:
            excess = raw_total - 3000
            halved_excess = (excess // 2) // 100 * 100
            total = 3000 + halved_excess

        return ScoringResult(
            explanation=explanation,
            achieved_fans=achieved_results,
            total_score=total,
            is_excellence=False
        )
