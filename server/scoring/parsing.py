"""
Mahjong hand parsing and decomposition engine.
Ported from IMR_Calculator/main.py — CLI/interactive logic removed.
"""
import re
from typing import List, Dict, Tuple, Optional
from collections import Counter
from dataclasses import dataclass, field
from enum import Enum


class TileType(Enum):
    BAMBOO = 'bamboo'
    CHARACTER = 'character'
    DOT = 'dot'
    WIND = 'wind'
    DRAGON = 'dragon'


@dataclass
class Tile:
    tile_type: TileType
    value: int  # 1-9 suits; winds E=1 S=2 W=3 N=4; dragons Wh=1 G=2 R=3

    def __hash__(self):
        return hash((self.tile_type, self.value))

    def __eq__(self, other):
        if not isinstance(other, Tile):
            return False
        return self.tile_type == other.tile_type and self.value == other.value

    def __lt__(self, other):
        order = [TileType.CHARACTER, TileType.DOT, TileType.BAMBOO, TileType.WIND, TileType.DRAGON]
        if self.tile_type != other.tile_type:
            return order.index(self.tile_type) < order.index(other.tile_type)
        return self.value < other.value

    def __repr__(self):
        return self.to_english()

    def is_honor(self) -> bool:
        return self.tile_type in (TileType.WIND, TileType.DRAGON)

    def is_terminal(self) -> bool:
        return not self.is_honor() and self.value in (1, 9)

    def is_terminal_or_honor(self) -> bool:
        return self.is_honor() or self.is_terminal()

    def to_english(self) -> str:
        if self.tile_type == TileType.BAMBOO:
            return f"{self.value}b"
        elif self.tile_type == TileType.CHARACTER:
            return f"{self.value}c"
        elif self.tile_type == TileType.DOT:
            return f"{self.value}d"
        elif self.tile_type == TileType.WIND:
            return {1: 'E', 2: 'S', 3: 'W', 4: 'N'}[self.value]
        elif self.tile_type == TileType.DRAGON:
            return {1: 'Wh', 2: 'G', 3: 'R'}[self.value]

    def to_japanese(self) -> str:
        if self.tile_type == TileType.BAMBOO:
            return f"{self.value}s"
        elif self.tile_type == TileType.CHARACTER:
            return f"{self.value}m"
        elif self.tile_type == TileType.DOT:
            return f"{self.value}p"
        elif self.tile_type == TileType.WIND:
            return f"{self.value}z"
        elif self.tile_type == TileType.DRAGON:
            return f"{self.value + 4}z"


class CallType(Enum):
    STRAIGHT = 'straight'
    TRIPLET = 'triplet'
    QUAD = 'quad'
    CONCEALED_QUAD = 'concealed_quad'


@dataclass
class Call:
    call_type: CallType
    tiles: List[Tile]

    def __repr__(self):
        tiles_str = ''.join(t.to_english() for t in self.tiles)
        if self.call_type == CallType.CONCEALED_QUAD:
            return f"[{tiles_str}*]"
        return f"[{tiles_str}]"


@dataclass
class Group:
    group_type: str  # 'straight', 'triplet', 'quad', 'pair', 'thirteen_orphans'
    tiles: List[Tile]
    is_call: bool = False
    is_concealed_quad: bool = False

    def __repr__(self):
        tiles_str = format_tiles_compact(self.tiles)
        if self.is_call:
            if self.is_concealed_quad:
                return f"[{tiles_str}*]"
            return f"[{tiles_str}]"
        return f"({tiles_str})"


@dataclass
class ParsedHand:
    calls: List[Call]
    hand_tiles: List[Tile]
    winning_tile: Tile
    is_self_drawn: bool
    additional_notes: str
    format_type: str


@dataclass
class HandExplanation:
    explanation_id: int
    pattern_type: str  # '13O', '7P', 'TTTTp', etc.
    groups: List[Group]
    pair: Optional[List[Tile]]
    additional_notes: str
    is_self_drawn: bool
    winning_tile: Tile

    def __repr__(self):
        groups_str = ''.join(str(g) for g in self.groups)
        if self.pair:
            pair_str = f"({format_tiles_compact(self.pair)})"
            groups_str += pair_str
        drawn_mark = "*" if self.is_self_drawn else ""
        return f"id={self.explanation_id}, type='{self.pattern_type}', hand=\"{groups_str}{drawn_mark} +{self.additional_notes}\""


def format_tiles_compact(tiles: List[Tile]) -> str:
    if not tiles:
        return ""
    sorted_tiles = sorted(tiles)
    result = []
    current_type = None
    current_values = []
    for tile in sorted_tiles:
        if tile.tile_type != current_type:
            if current_type is not None:
                result.append(_format_group(current_type, current_values))
            current_type = tile.tile_type
            current_values = [tile.value]
        else:
            current_values.append(tile.value)
    if current_type is not None:
        result.append(_format_group(current_type, current_values))
    return ''.join(result)


def _format_group(tile_type: TileType, values: List[int]) -> str:
    if tile_type == TileType.BAMBOO:
        return ''.join(str(v) for v in values) + 'b'
    elif tile_type == TileType.CHARACTER:
        return ''.join(str(v) for v in values) + 'c'
    elif tile_type == TileType.DOT:
        return ''.join(str(v) for v in values) + 'd'
    elif tile_type == TileType.WIND:
        winds = {1: 'E', 2: 'S', 3: 'W', 4: 'N'}
        return ''.join(winds[v] for v in values)
    elif tile_type == TileType.DRAGON:
        dragons = {1: 'Wh', 2: 'G', 3: 'R'}
        return ''.join(dragons[v] for v in values)


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def detect_format(input_str: str) -> Optional[str]:
    clean = re.sub(r'\[.*?\]', '', input_str)
    clean = re.sub(r'\s+', '', clean)
    has_japanese = bool(re.search(r'\d[spmSPM]', clean)) or bool(re.search(r'[1-7]z', clean, re.IGNORECASE))
    has_english = bool(re.search(r'\d[bcdBCD]', clean)) or bool(re.search(r'(?<!\d)(?:Wh|[ESWNRG])(?![a-z])', clean))
    if has_japanese and has_english:
        return None
    elif has_japanese:
        return 'japanese'
    elif has_english:
        return 'english'
    return None


def parse_tiles_japanese(tile_str: str) -> List[Tile]:
    tiles = []
    for match in re.finditer(r'(\d+)([spzmSPZM])', tile_str):
        numbers, suit = match.group(1), match.group(2).lower()
        for num in numbers:
            value = int(num)
            if suit == 's' and 1 <= value <= 9:
                tiles.append(Tile(TileType.BAMBOO, value))
            elif suit == 'p' and 1 <= value <= 9:
                tiles.append(Tile(TileType.DOT, value))
            elif suit == 'm' and 1 <= value <= 9:
                tiles.append(Tile(TileType.CHARACTER, value))
            elif suit == 'z':
                if 1 <= value <= 4:
                    tiles.append(Tile(TileType.WIND, value))
                elif 5 <= value <= 7:
                    tiles.append(Tile(TileType.DRAGON, value - 4))
    return tiles


def parse_tiles_english(tile_str: str) -> List[Tile]:
    tiles = []
    pattern_suit = r'(\d+)([bcdBCD])'
    for match in re.finditer(pattern_suit, tile_str):
        numbers, suit = match.group(1), match.group(2).lower()
        for num in numbers:
            value = int(num)
            if 1 <= value <= 9:
                if suit == 'b':
                    tiles.append(Tile(TileType.BAMBOO, value))
                elif suit == 'd':
                    tiles.append(Tile(TileType.DOT, value))
                elif suit == 'c':
                    tiles.append(Tile(TileType.CHARACTER, value))
    remaining = re.sub(pattern_suit, '', tile_str)
    honor_patterns = [
        (r'Wh', TileType.DRAGON, 1),
        (r'G', TileType.DRAGON, 2),
        (r'R', TileType.DRAGON, 3),
        (r'E', TileType.WIND, 1),
        (r'S', TileType.WIND, 2),
        (r'W', TileType.WIND, 3),
        (r'N', TileType.WIND, 4),
    ]
    for pattern, tile_type, value in honor_patterns:
        count = len(re.findall(pattern, remaining))
        for _ in range(count):
            tiles.append(Tile(tile_type, value))
        remaining = re.sub(pattern, '', remaining)
    return tiles


def parse_tiles(tile_str: str, format_type: str) -> List[Tile]:
    if format_type == 'japanese':
        return parse_tiles_japanese(tile_str)
    return parse_tiles_english(tile_str)


def parse_call(call_str: str, format_type: str) -> Optional[Call]:
    inner = call_str.strip('[]')
    is_concealed = inner.endswith('*')
    if is_concealed:
        inner = inner[:-1]
    tiles = parse_tiles(inner, format_type)
    if not tiles:
        return None
    if len(tiles) == 3:
        if tiles[0] == tiles[1] == tiles[2]:
            return Call(CallType.TRIPLET, tiles)
        sorted_tiles = sorted(tiles)
        if (not sorted_tiles[0].is_honor() and
                sorted_tiles[0].tile_type == sorted_tiles[1].tile_type == sorted_tiles[2].tile_type and
                sorted_tiles[1].value == sorted_tiles[0].value + 1 and
                sorted_tiles[2].value == sorted_tiles[0].value + 2):
            return Call(CallType.STRAIGHT, sorted_tiles)
        return None
    elif len(tiles) == 4:
        if tiles[0] == tiles[1] == tiles[2] == tiles[3]:
            call_type = CallType.CONCEALED_QUAD if is_concealed else CallType.QUAD
            return Call(call_type, tiles)
        return None
    return None


def parse_hand(input_str: str) -> Tuple[Optional[ParsedHand], str]:
    input_str = input_str.strip()
    format_type = detect_format(input_str)
    if format_type is None:
        return None, "Cannot detect format or mixed notation"
    parts = input_str.split('+')
    if len(parts) < 2:
        return None, "Missing winning tile (needs '+' separator)"
    hand_part = parts[0].strip()
    winning_part = parts[1].strip()
    additional_notes = ('+' + '+'.join(parts[2:])).strip() if len(parts) > 2 else ""
    is_self_drawn = winning_part.endswith('*')
    if is_self_drawn:
        winning_part = winning_part[:-1].strip()
    winning_tiles = parse_tiles(winning_part, format_type)
    if len(winning_tiles) != 1:
        return None, f"Winning tile must be exactly one tile, got {len(winning_tiles)}"
    winning_tile = winning_tiles[0]
    call_pattern = r'\[[^\]]+\]'
    calls = []
    for call_str in re.findall(call_pattern, hand_part):
        call = parse_call(call_str, format_type)
        if call is None:
            return None, f"Invalid call: {call_str}"
        calls.append(call)
    remaining_hand = re.sub(call_pattern, '', hand_part)
    hand_tiles = parse_tiles(remaining_hand, format_type)
    return ParsedHand(
        calls=calls,
        hand_tiles=hand_tiles,
        winning_tile=winning_tile,
        is_self_drawn=is_self_drawn,
        additional_notes=additional_notes,
        format_type=format_type
    ), ""


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_hand(parsed: ParsedHand) -> Tuple[bool, str]:
    num_quads = sum(1 for c in parsed.calls if c.call_type in (CallType.QUAD, CallType.CONCEALED_QUAD))
    total_tiles = sum(len(c.tiles) for c in parsed.calls) + len(parsed.hand_tiles) + 1
    expected_tiles = 14 + num_quads
    if total_tiles != expected_tiles:
        return False, f"Expected {expected_tiles} tiles, got {total_tiles}"
    if len(parsed.calls) > 4:
        return False, f"Too many calls: {len(parsed.calls)}"
    all_tiles: List[Tile] = []
    for call in parsed.calls:
        all_tiles.extend(call.tiles)
    all_tiles.extend(parsed.hand_tiles)
    all_tiles.append(parsed.winning_tile)
    for tile, count in Counter(all_tiles).items():
        if count > 4:
            if tile == parsed.winning_tile and Counter(parsed.hand_tiles)[tile] == 4:
                return False, f"Drawing dead: 0 outs for {tile}"
            return False, f"Too many copies of {tile}: {count}"
    notes = parsed.additional_notes.upper()
    has_non_quad_calls = any(c.call_type in (CallType.STRAIGHT, CallType.TRIPLET) for c in parsed.calls)
    has_quads = any(c.call_type in (CallType.QUAD, CallType.CONCEALED_QUAD) for c in parsed.calls)
    if '+BOH' in notes and parsed.calls:
        return False, "Blessing of Heaven requires no calls"
    if '+BOE' in notes and parsed.calls:
        return False, "Blessing of Earth requires no calls"
    if '+EW' in notes and has_non_quad_calls:
        return False, "Eastern Wind tenpai cannot have open calls"
    if '+DW' in notes and has_non_quad_calls:
        return False, "Declare Waiting cannot have open calls"
    if '+AQ' in notes and not has_quads:
        return False, "After Quad requires at least 1 quad"
    return True, ""


# ---------------------------------------------------------------------------
# Hand decomposition
# ---------------------------------------------------------------------------

def find_all_explanations(parsed: ParsedHand) -> List[HandExplanation]:
    explanations = []
    eid = 1
    all_hand_tiles = parsed.hand_tiles + [parsed.winning_tile]

    if not parsed.calls:
        result = check_thirteen_orphans(all_hand_tiles)
        if result:
            explanations.append(HandExplanation(eid, '13O', result, None,
                                                parsed.additional_notes, parsed.is_self_drawn,
                                                parsed.winning_tile))
            eid += 1

    if not parsed.calls:
        result = check_seven_pairs(all_hand_tiles)
        if result:
            explanations.append(HandExplanation(eid, '7P', result, None,
                                                parsed.additional_notes, parsed.is_self_drawn,
                                                parsed.winning_tile))
            eid += 1

    for pattern_type, groups, pair in find_classic_explanations(parsed):
        explanations.append(HandExplanation(eid, pattern_type, groups, pair,
                                            parsed.additional_notes, parsed.is_self_drawn,
                                            parsed.winning_tile))
        eid += 1

    return explanations


def check_thirteen_orphans(tiles: List[Tile]) -> Optional[List[Group]]:
    if len(tiles) != 14:
        return None
    required = [
        Tile(TileType.CHARACTER, 1), Tile(TileType.CHARACTER, 9),
        Tile(TileType.DOT, 1), Tile(TileType.DOT, 9),
        Tile(TileType.BAMBOO, 1), Tile(TileType.BAMBOO, 9),
        Tile(TileType.WIND, 1), Tile(TileType.WIND, 2),
        Tile(TileType.WIND, 3), Tile(TileType.WIND, 4),
        Tile(TileType.DRAGON, 1), Tile(TileType.DRAGON, 2), Tile(TileType.DRAGON, 3)
    ]
    tile_counts = Counter(tiles)
    for t in required:
        if tile_counts[t] < 1:
            return None
    pair_tile = next((t for t in required if tile_counts[t] == 2), None)
    if pair_tile is None:
        return None
    if sum(tile_counts[t] for t in required) != 14:
        return None
    return [Group('thirteen_orphans', sorted(tiles))]


def check_seven_pairs(tiles: List[Tile]) -> Optional[List[Group]]:
    if len(tiles) != 14:
        return None
    tile_counts = Counter(tiles)
    for count in tile_counts.values():
        if count not in (2, 4):
            return None
    if sum(count // 2 for count in tile_counts.values()) != 7:
        return None
    groups = []
    for tile in sorted(tile_counts.keys()):
        for _ in range(tile_counts[tile] // 2):
            groups.append(Group('pair', [tile, tile]))
    return groups


def find_classic_explanations(parsed: ParsedHand) -> List[Tuple[str, List[Group], List[Tile]]]:
    results = []
    call_groups = []
    num_t = num_s = 0
    for call in parsed.calls:
        if call.call_type == CallType.STRAIGHT:
            call_groups.append(Group('straight', call.tiles, is_call=True))
            num_s += 1
        elif call.call_type == CallType.TRIPLET:
            call_groups.append(Group('triplet', call.tiles, is_call=True))
            num_t += 1
        elif call.call_type in (CallType.QUAD, CallType.CONCEALED_QUAD):
            is_cq = call.call_type == CallType.CONCEALED_QUAD
            call_groups.append(Group('quad', call.tiles, is_call=True, is_concealed_quad=is_cq))
            num_t += 1
    remaining = parsed.hand_tiles + [parsed.winning_tile]
    groups_needed = 4 - len(call_groups)
    for groups, pair in find_decompositions(remaining, groups_needed):
        all_groups = call_groups + groups
        total_t = num_t + sum(1 for g in groups if g.group_type in ('triplet', 'quad'))
        total_s = num_s + sum(1 for g in groups if g.group_type == 'straight')
        pattern_type = 'T' * total_t + 'S' * total_s + 'p'
        results.append((pattern_type, all_groups, pair))
    return results


def find_decompositions(tiles: List[Tile], groups_needed: int) -> List[Tuple[List[Group], List[Tile]]]:
    results = []
    tile_counts = Counter(tiles)
    for pair_tile in [t for t, c in tile_counts.items() if c >= 2]:
        rem = tile_counts.copy()
        rem[pair_tile] -= 2
        if rem[pair_tile] == 0:
            del rem[pair_tile]
        if sum(rem.values()) != groups_needed * 3:
            continue
        for groups in find_groups(rem, groups_needed):
            results.append((groups, [pair_tile, pair_tile]))
    return results


def find_groups(tile_counts: Counter, num_groups: int, memo: dict = None) -> List[List[Group]]:
    if num_groups == 0:
        return [[]] if sum(tile_counts.values()) == 0 else []
    if sum(tile_counts.values()) < num_groups * 3:
        return []
    key = (tuple(sorted(tile_counts.items())), num_groups)
    if memo is None:
        memo = {}
    if key in memo:
        return memo[key]
    results = []
    available = sorted([t for t, c in tile_counts.items() if c > 0])
    if not available:
        return []
    first = available[0]
    if tile_counts[first] >= 3:
        new = tile_counts.copy()
        new[first] -= 3
        if new[first] == 0:
            del new[first]
        for sub in find_groups(new, num_groups - 1, memo):
            results.append([Group('triplet', [first, first, first])] + sub)
    if not first.is_honor() and first.value <= 7:
        n1 = Tile(first.tile_type, first.value + 1)
        n2 = Tile(first.tile_type, first.value + 2)
        if tile_counts.get(n1, 0) >= 1 and tile_counts.get(n2, 0) >= 1:
            new = tile_counts.copy()
            for t in (first, n1, n2):
                new[t] -= 1
                if new[t] == 0:
                    del new[t]
            for sub in find_groups(new, num_groups - 1, memo):
                results.append([Group('straight', [first, n1, n2])] + sub)
    memo[key] = results
    return results


# ---------------------------------------------------------------------------
# Convenience
# ---------------------------------------------------------------------------

def analyze_hand(input_str: str) -> dict:
    result = {'input': input_str, 'is_valid': False, 'error': '', 'parsed': None, 'explanations': []}
    parsed, error = parse_hand(input_str)
    if parsed is None:
        result['error'] = error
        return result
    result['parsed'] = parsed
    is_valid, error = validate_hand(parsed)
    if not is_valid:
        result['error'] = error
        return result
    result['is_valid'] = True
    explanations = find_all_explanations(parsed)
    result['explanations'] = explanations
    if not explanations:
        result['error'] = "No valid winning pattern found"
        result['is_valid'] = False
    return result
