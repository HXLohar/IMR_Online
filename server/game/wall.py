"""
Tile wall: shuffle, deal, draw, quad supplement.
Step 1 has no dora indicators — the wall is simply 136 tiles.
"""
import random
from game.tiles import ALL_TILES, Tile

FULL_WALL_SIZE = 136  # 34 types × 4 copies


class Wall:
    def __init__(self, seed: int | None = None):
        self._rng = random.Random(seed)
        tiles = ALL_TILES * 4
        self._rng.shuffle(tiles)
        self._tiles: list[Tile] = tiles
        # Dead wall: last 14 tiles (for quad supplements)
        # For Step 1, just track a draw pointer and supplement pointer.
        self._draw_ptr = 0
        self._supp_ptr = FULL_WALL_SIZE - 1  # supplements drawn from the end

    def remaining(self) -> int:
        """Live tiles left (between draw_ptr and supp_ptr, exclusive)."""
        return self._supp_ptr - self._draw_ptr

    def draw(self) -> Tile | None:
        """Draw the next tile from the live wall."""
        if self._draw_ptr > self._supp_ptr:
            return None
        t = self._tiles[self._draw_ptr]
        self._draw_ptr += 1
        return t

    def draw_supplement(self) -> Tile | None:
        """Draw a supplement tile from the dead-wall end after a quad."""
        if self._draw_ptr > self._supp_ptr:
            return None
        t = self._tiles[self._supp_ptr]
        self._supp_ptr -= 1
        return t

    def deal(self, num_players: int = 4) -> list[list[Tile]]:
        """
        Deal initial hands: each player gets 13 tiles.
        Deals in standard rounds of 4-4-4-1.
        """
        hands: list[list[Tile]] = [[] for _ in range(num_players)]
        # Three rounds of 4 tiles each
        for _ in range(3):
            for seat in range(num_players):
                for _ in range(4):
                    t = self.draw()
                    if t:
                        hands[seat].append(t)
        # One final tile each
        for seat in range(num_players):
            t = self.draw()
            if t:
                hands[seat].append(t)
        return hands

    def snapshot(self) -> dict:
        """Serializable wall state for reconnecting clients."""
        return {
            'draw_ptr': self._draw_ptr,
            'supplement_ptr': self._supp_ptr,
            'remaining': self.remaining(),
        }
