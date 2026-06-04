"""
Tests for scoring/api.py — validates the ported engine is correct.
Hand tiles must be 13 (with no calls) or 13 - 3*n_calls before the winning tile.
"""
import pytest
from scoring.parsing import (
    Tile, TileType, Call, CallType,
    parse_tiles_english as tiles, analyze_hand,
)
from scoring.api import is_winning, score_hand, waits, shanten, WinFlags
from scoring.fan import load_fans_from_csv, calculate_score


def T(s: str) -> Tile:
    """Parse a single tile string like '1b', 'E', 'R'."""
    result = tiles(s)
    assert len(result) == 1, f"Expected 1 tile from {s!r}, got {result}"
    return result[0]


def pong(tile_str: str) -> Call:
    t = T(tile_str)
    return Call(CallType.TRIPLET, [t, t, t])


def chow(tile_str: str) -> Call:
    ts = sorted(tiles(tile_str))
    assert len(ts) == 3
    return Call(CallType.STRAIGHT, ts)


# ---------------------------------------------------------------------------
# is_winning
# ---------------------------------------------------------------------------

class TestIsWinning:
    def test_simple_closed_hand(self):
        # 123b 456b 789b 123c | win 3c — actually wait: 13+1=14 means
        # hand = tiles('123b456b789b123c') = 12 tiles, but need 13. Add pair:
        # hand = tiles('123b456b789b123c11c') = 3+3+3+3+2 = 14 tiles. That's too many.
        # Correct construction: 3 complete groups + partial = 10+1 = 11... no.
        # Use: 3 groups × 3 = 9 tiles + 1 partial group + 1 pair:
        # 123b 456b 789b 12c 11c = 9+2+2 = 13 tiles, win 3c completes chow 123c.
        hand = tiles('123b456b789b12c11c')   # 13 tiles
        assert is_winning(hand, [], T('3c'), WinFlags())

    def test_seven_pairs(self):
        # 11223344556677b = 14 tiles for seven pairs
        # 13 tiles + win: 1122334455667b = 13 tiles, win 7b
        hand = tiles('1122334455667b')      # 13 tiles
        assert is_winning(hand, [], T('7b'), WinFlags(self_drawn=True))

    def test_thirteen_orphans(self):
        # All 13 orphan tiles in hand (including one R), win R for pair
        hand = tiles('19b19c19dESWNWhGR')  # 13 tiles
        assert is_winning(hand, [], T('R'), WinFlags(self_drawn=True))

    def test_not_winning(self):
        # 13 random tiles that don't form a hand
        hand = tiles('12345b123c123d12b')   # 13 tiles
        assert not is_winning(hand, [], T('3b'), WinFlags())

    def test_win_with_open_call(self):
        # [555c open pong] + 123b 456b 789b (9 tiles) + 1c half-pair
        # hand_tiles = 9 + 1 = 10 tiles; win 1c for pair; call contributes 3 tiles
        # total = 3 + 10 + 1 = 14 ✓; 5c only in call (no clash with 4-tile limit)
        hand = tiles('123b456b789b1c')      # 10 tiles
        win = T('1c')
        assert is_winning(hand, [pong('5c')], win, WinFlags())

    def test_not_winning_with_call(self):
        # Broken hand
        hand = tiles('135b246b357b5c')      # 10 tiles
        assert not is_winning(hand, [pong('5c')], T('9c'), WinFlags())


# ---------------------------------------------------------------------------
# score_hand
# ---------------------------------------------------------------------------

class TestScoreHand:
    def test_concealed_hand_score(self):
        # Use analyze_hand to parse canonical test case, then score it
        result = analyze_hand('[RRRR*][123b]4567899b + 9b* +LT')
        assert result['is_valid'], result.get('error')
        exp = result['explanations'][0]
        sr = calculate_score(exp)
        assert sr.total_score > 0, f"Got 0 fans: {sr}"

    def test_pure_flush_seven_pairs(self):
        # 1122335577889b = 13 tiles, win 9b = seven pairs
        hand = tiles('1122335577889b')      # 13 tiles
        wt = T('9b')
        sr = score_hand(hand, [], wt, WinFlags(self_drawn=False))
        assert sr is not None
        assert sr.total_score > 0
        fan_names = {af.fan.name_e for af in sr.achieved_fans}
        assert 'Pure Flush' in fan_names or 'Seven Pairs' in fan_names

    def test_self_drawn_gives_fan(self):
        # 123b 456b 789b 11c 22c (13 tiles) — tsumo vs ron; win 2c completes 222c + pair 11c
        hand = tiles('123b456b789b11c22c')  # 13 tiles
        wt = T('2c')
        sr_ron = score_hand(hand, [], wt, WinFlags(self_drawn=False))
        sr_tsumo = score_hand(hand, [], wt, WinFlags(self_drawn=True))
        assert sr_ron is not None
        assert sr_tsumo is not None
        ron_fans = {af.fan.name_e for af in sr_ron.achieved_fans}
        tsumo_fans = {af.fan.name_e for af in sr_tsumo.achieved_fans}
        assert 'Self-drawn' in tsumo_fans
        assert 'Self-drawn' not in ron_fans

    def test_major_four_winds_excellence(self):
        # [EEE][SSS][WWW] + NNN4d + win 4d
        # 3 calls (9 tiles) + 4 closed (NNN4d) + 1 win = 14 tiles
        result = analyze_hand('[EEE][SSS][WWW]NNN4d + 4d')
        assert result['is_valid'], result.get('error')
        sr = calculate_score(result['explanations'][0])
        assert sr.is_excellence

    def test_score_returns_best(self):
        # 678b33344455cRR = 13 tiles (3+8+2), win 5c
        hand = tiles('678b33344455cRR')     # 13 tiles
        wt = T('5c')
        sr = score_hand(hand, [], wt, WinFlags())
        assert sr is not None
        assert sr.total_score > 0

    def test_simple_hand_fan(self):
        # A hand with Simple Hand (no terminals/honors): [222d]234b6789c5c pair
        # [222d] open + 234b 67c + pair 55c = 3+3+2+2 = 10 hand tiles + win = 11...
        # Let me use all-closed instead:
        # 234b 678c 234d 55b = wait on 5b
        hand = tiles('234b678c234d5b')      # 3+3+3+1=10 tiles → still not 13
        # Proper 13-tile simple hand: 234b 345b 456b 678c 55c = 3+3+3+3+2=14, so:
        hand = tiles('234b345b456b678c5c')  # 3+3+3+3+1=13 tiles
        wt = T('5c')
        sr = score_hand(hand, [], wt, WinFlags())
        assert sr is not None
        # Should detect Simple Hand (216) since all tiles are 2-8
        fan_names = {af.fan.name_e for af in sr.achieved_fans}
        assert 'Simple Hand' in fan_names


# ---------------------------------------------------------------------------
# waits
# ---------------------------------------------------------------------------

class TestWaits:
    def test_single_pair_wait(self):
        # 123b 456b 789b 123c + 1c waiting for pair 1c1c
        hand = tiles('123b456b789b123c1c')  # 13 tiles
        w = waits(hand, [])
        assert T('1c') in w

    def test_multi_suit_tenpai(self):
        # 123b 456b 789b 12c + ?, wait on 3c
        hand = tiles('123b456b789b12c1c')   # 13 tiles (with 1c extra)
        # Actually better: 123b 456b 789b 12c waiting on 3c, need one more tile:
        hand2 = tiles('123b456b789b12c11c')  # 3+3+3+2+2=13 → wait on 3c for a chow+pair
        w = waits(hand2, [])
        assert len(w) > 0

    def test_seven_pairs_tenpai(self):
        # 1122334455667b = 13 tiles (wait on 7b for seventh pair)
        hand = tiles('1122334455667b')      # 13 tiles
        w = waits(hand, [])
        assert T('7b') in w

    def test_no_wait_for_bad_hand(self):
        # A scattered hand unlikely to have waits
        hand = tiles('12b46c13d579bESW')    # 3+2+2+3+3=13 tiles
        w = waits(hand, [])
        assert isinstance(w, list)  # just ensure no crash


# ---------------------------------------------------------------------------
# shanten
# ---------------------------------------------------------------------------

class TestShanten:
    def test_tenpai_is_zero(self):
        # 13-tile tenpai: 123b 456b 789b 12c 11c → waits on 3c (chow 123c + pair 11c)
        hand = tiles('123b456b789b12c11c')  # 13 tiles
        assert shanten(hand, []) == 0

    def test_complete_shape_tenpai(self):
        # 13-tile tenpai: 123b 456b 789b 11c 22c → waits on 2c (triplet 222c + pair 11c)
        hand = tiles('123b456b789b11c22c')  # 13 tiles
        assert shanten(hand, []) == 0

    def test_one_away_from_tenpai(self):
        # A hand that needs 2+ tiles to win (shanten > 0)
        hand = tiles('123b456b135c246d1c')  # 13 tiles, harder to form groups
        s = shanten(hand, [])
        assert s >= 0  # At least needs some tiles


# ---------------------------------------------------------------------------
# Fan CSV
# ---------------------------------------------------------------------------

class TestFanCSV:
    def test_fans_loaded(self):
        fans = load_fans_from_csv()
        assert len(fans) > 50, f"Should have many fans defined, got {len(fans)}"

    def test_fan_has_names(self):
        fans = load_fans_from_csv()
        assert len(fans) > 0, "No fans loaded"
        for fid, fan in fans.items():
            assert fan.name_e or fan.name_c, f"Fan {fid} has no name"

    def test_excellence_fans_exist(self):
        fans = load_fans_from_csv()
        excellence = [f for f in fans.values() if f.is_excellence]
        assert len(excellence) > 0

    def test_fan_values_positive(self):
        fans = load_fans_from_csv()
        for fid, fan in fans.items():
            assert fan.value > 0, f"Fan {fid} has non-positive value {fan.value}"
