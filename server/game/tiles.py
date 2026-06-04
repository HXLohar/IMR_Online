"""
Game-layer tile utilities.
Re-exports the canonical Tile/TileType/Call/CallType from scoring.parsing
and adds game-specific helpers.
"""
from scoring.parsing import (
    Tile, TileType, Call, CallType,
    parse_tiles_english, parse_tiles_japanese,
)

# ---------------------------------------------------------------------------
# All 34 distinct tile types in canonical order
# ---------------------------------------------------------------------------

ALL_TILES: list[Tile] = [
    *[Tile(TileType.CHARACTER, v) for v in range(1, 10)],
    *[Tile(TileType.DOT, v) for v in range(1, 10)],
    *[Tile(TileType.BAMBOO, v) for v in range(1, 10)],
    Tile(TileType.WIND, 1), Tile(TileType.WIND, 2),
    Tile(TileType.WIND, 3), Tile(TileType.WIND, 4),
    Tile(TileType.DRAGON, 1), Tile(TileType.DRAGON, 2), Tile(TileType.DRAGON, 3),
]


def tile_from_str(s: str) -> Tile:
    """Parse a single tile string (e.g. '5b', 'E', 'Wh')."""
    result = parse_tiles_english(s)
    if len(result) == 1:
        return result[0]
    raise ValueError(f"Cannot parse tile: {s!r}")


def tiles_from_str(s: str) -> list[Tile]:
    """Parse a tile string like '123b456c' into a list of Tile objects."""
    return parse_tiles_english(s)


def tile_to_str(t: Tile) -> str:
    return t.to_english()
