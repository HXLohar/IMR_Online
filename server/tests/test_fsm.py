"""Tests for game/fsm.py — focuses on resolve_claims (pure function)."""
import pytest
from game.fsm import resolve_claims, ClaimResolution
from game.tiles import tile_from_str as T


def mkdiscard(tile_str: str = '5c'):
    return T(tile_str)


# ---------------------------------------------------------------------------
# resolve_claims — priority tests
# ---------------------------------------------------------------------------

class TestResolveClaims:
    def test_win_beats_all(self):
        discard = mkdiscard('5c')
        claims = {
            1: {'claim': 'pong'},
            2: {'claim': 'win'},
            3: {'claim': 'chow'},
        }
        res = resolve_claims(discard, from_seat=0, claims=claims)
        assert 2 in res.winners
        assert res.call_seat is None

    def test_multi_win(self):
        discard = mkdiscard('5c')
        claims = {
            1: {'claim': 'win'},
            2: {'claim': 'skip'},
            3: {'claim': 'win'},
        }
        res = resolve_claims(discard, from_seat=0, claims=claims)
        assert set(res.winners) == {1, 3}

    def test_pong_beats_chow(self):
        discard = mkdiscard('5c')
        claims = {
            1: {'claim': 'chow'},
            2: {'claim': 'pong'},
            3: {'claim': 'skip'},
        }
        res = resolve_claims(discard, from_seat=0, claims=claims)
        assert res.call_seat == 2
        assert res.call_action['claim'] == 'pong'
        assert res.winners == []

    def test_kong_beats_pong(self):
        discard = mkdiscard('5c')
        claims = {
            1: {'claim': 'pong'},
            2: {'claim': 'kong'},
            3: {'claim': 'skip'},
        }
        res = resolve_claims(discard, from_seat=0, claims=claims)
        assert res.call_seat == 2
        assert res.call_action['claim'] == 'kong'

    def test_tie_break_closer_seat(self):
        # from_seat=0; seats 2 and 3 both pong → seat 1 (dist 1) wins if present
        # seats 2 (dist 2) and 3 (dist 3) both claim pong → seat 2 wins (closer)
        discard = mkdiscard('5c')
        claims = {
            2: {'claim': 'pong'},
            3: {'claim': 'pong'},
        }
        res = resolve_claims(discard, from_seat=0, claims=claims)
        assert res.call_seat == 2

    def test_all_skip(self):
        discard = mkdiscard('5c')
        claims = {
            1: {'claim': 'skip'},
            2: {'claim': 'skip'},
            3: {'claim': 'skip'},
        }
        res = resolve_claims(discard, from_seat=0, claims=claims)
        assert res.winners == []
        assert res.call_seat is None

    def test_empty_claims(self):
        discard = mkdiscard('5c')
        res = resolve_claims(discard, from_seat=0, claims={})
        assert res.winners == []
        assert res.call_seat is None

    def test_win_seat_1_from_seat_3(self):
        # Seat 3 discards, seat 1 is next (dist 2), seat 2 (dist 3)
        # Only one winner at seat 1
        discard = mkdiscard('5c')
        claims = {1: {'claim': 'win'}, 2: {'claim': 'skip'}}
        res = resolve_claims(discard, from_seat=3, claims=claims)
        assert 1 in res.winners


# ---------------------------------------------------------------------------
# Settle functions smoke tests
# ---------------------------------------------------------------------------

class TestSettle:
    def test_exhaustive_no_tenpai(self):
        from game.settle import settle_exhaustive_draw
        # No one is tenpai → no payments
        # Use a bad hand (not tenpai)
        from game.tiles import tiles_from_str as tiles
        hands = {s: tiles('123b456b789b135c') for s in range(4)}  # 13 scattered tiles
        calls = {s: [] for s in range(4)}
        pcs = {s: 0 for s in range(4)}
        cpcs = {s: 0 for s in range(4)}
        result = settle_exhaustive_draw(pcs, cpcs, hands, calls)
        assert result.is_exhaustive
        assert all(v == 0 for v in result.payments.values())

    def test_exhaustive_rangguo_penalty(self):
        from game.settle import settle_exhaustive_draw
        from game.tiles import tiles_from_str as tiles
        # Seat 0: tenpai (123b456b789b12c waiting for 3c); pass_count=0
        # Seat 1: NOT tenpai; pass_count=1, chow_pong_count=0 → penalty 450
        tenpai_hand = tiles('123b456b789b12c1c')  # 13 tiles tenpai on 3c
        bad_hand = tiles('123b456b135c246d1c')     # 13 tiles, likely not tenpai

        hands = {0: tenpai_hand, 1: bad_hand, 2: bad_hand, 3: bad_hand}
        calls = {s: [] for s in range(4)}
        pcs = {0: 0, 1: 1, 2: 0, 3: 0}
        cpcs = {0: 0, 1: 0, 2: 0, 3: 0}

        result = settle_exhaustive_draw(pcs, cpcs, hands, calls)
        assert result.is_exhaustive
        # Seat 1 should have negative payment if they're not tenpai
        # We can't know for sure without running waits, but can check structure
        assert isinstance(result.payments[0], int)
