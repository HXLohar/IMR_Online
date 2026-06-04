"""Tests for game/legal.py and game/redraw.py."""
from scoring.parsing import Tile, TileType, Call, CallType
from scoring.api import WinFlags
from game.legal import (
    can_chow, can_pong, can_open_kong, can_concealed_kong,
    can_added_kong, can_win_on_discard, legal_claims,
    chow_pong_limit,
)
from game.redraw import is_redraw_eligible
from game.tiles import tile_from_str as T, tiles_from_str as tiles


# ---------------------------------------------------------------------------
# chow_pong_limit
# ---------------------------------------------------------------------------

def test_limit_no_pass():
    assert chow_pong_limit(0) is None

def test_limit_one_pass():
    assert chow_pong_limit(1) == 2

def test_limit_two_passes():
    assert chow_pong_limit(2) == 1


# ---------------------------------------------------------------------------
# can_chow
# ---------------------------------------------------------------------------

class TestCanChow:
    def test_basic_chow(self):
        hand = tiles('13b')
        discard = T('2b')
        options = can_chow(hand, discard, pass_count=0, chow_pong_count=0)
        assert len(options) == 1
        assert sorted(options[0].tiles) == sorted(tiles('123b'))

    def test_multiple_chow_options(self):
        # 1b 2b 3b 4b in hand, discard 3b → chow 123b or 234b
        hand = tiles('124b')
        discard = T('3b')
        options = can_chow(hand, discard, 0, 0)
        assert len(options) == 2

    def test_no_chow_honor(self):
        hand = tiles('EE')
        discard = T('E')
        assert can_chow(hand, discard, 0, 0) == []

    def test_no_chow_missing_tile(self):
        hand = tiles('1b')
        discard = T('2b')
        # Need 1b+3b for 123b, but only have 1b and no 3b
        assert can_chow(hand, discard, 0, 0) == []

    def test_chow_blocked_by_limit(self):
        # pass_count=2 → limit=1; already used 1 chow/pong
        hand = tiles('13b')
        discard = T('2b')
        options = can_chow(hand, discard, pass_count=2, chow_pong_count=1)
        assert options == []

    def test_chow_at_edge_of_limit(self):
        # pass_count=1 → limit=2; used 1 so far, can still call
        hand = tiles('13b')
        discard = T('2b')
        options = can_chow(hand, discard, pass_count=1, chow_pong_count=1)
        assert len(options) == 1


# ---------------------------------------------------------------------------
# can_pong
# ---------------------------------------------------------------------------

class TestCanPong:
    def test_basic_pong(self):
        hand = tiles('55c')
        assert can_pong(hand, T('5c'), pass_count=0, chow_pong_count=0)

    def test_pong_need_two_in_hand(self):
        hand = tiles('5c')
        assert not can_pong(hand, T('5c'), 0, 0)

    def test_pong_blocked_by_limit(self):
        hand = tiles('55c')
        assert not can_pong(hand, T('5c'), pass_count=2, chow_pong_count=1)

    def test_pong_allowed_at_limit_edge(self):
        hand = tiles('55c')
        assert can_pong(hand, T('5c'), pass_count=1, chow_pong_count=1)


# ---------------------------------------------------------------------------
# can_open_kong
# ---------------------------------------------------------------------------

class TestCanKong:
    def test_open_kong(self):
        hand = tiles('555c')
        assert can_open_kong(hand, T('5c'))

    def test_open_kong_needs_three(self):
        hand = tiles('55c')
        assert not can_open_kong(hand, T('5c'))

    def test_concealed_kong(self):
        hand = tiles('5555c')
        result = can_concealed_kong(hand, T('5c'))
        assert T('5c') in result

    def test_concealed_kong_from_draw(self):
        hand = tiles('555c')
        # Draw the 4th 5c
        result = can_concealed_kong(hand, T('5c'))
        assert T('5c') in result

    def test_added_kong(self):
        hand = tiles('5c')
        pong_call = Call(CallType.TRIPLET, [T('5c')] * 3)
        result = can_added_kong(hand, [pong_call], T('1b'))
        assert T('5c') in result

    def test_added_kong_from_draw(self):
        hand = []
        pong_call = Call(CallType.TRIPLET, [T('5c')] * 3)
        result = can_added_kong(hand, [pong_call], T('5c'))
        assert T('5c') in result


# ---------------------------------------------------------------------------
# can_win_on_discard
# ---------------------------------------------------------------------------

class TestCanWin:
    def test_win_on_discard(self):
        # 123b 456b 789b 11c (hand=13) wait on 1c
        hand = tiles('123b456b789b123c1c')
        assert can_win_on_discard(hand, [], T('1c'), WinFlags())

    def test_no_win_on_discard(self):
        hand = tiles('123b456b789b123c5c')  # not tenpai on 1c
        # 5c doesn't complete anything useful, but let's use a clearly bad hand
        hand2 = tiles('13579b135c13d1c')   # 13 scattered tiles
        assert not can_win_on_discard(hand2, [], T('2c'), WinFlags())


# ---------------------------------------------------------------------------
# legal_claims
# ---------------------------------------------------------------------------

class TestLegalClaims:
    def test_downstream_can_chow(self):
        # seat 0 discards, seat 1 is downstream
        hand = tiles('12b345c678d11c')     # 13 tiles with pair 11c + chow potential
        discard = T('3b')
        claims = legal_claims(
            hand=tiles('12b345c678d1c'),    # 10 tiles (with 1 open call below)
            calls=[],
            discard=discard,
            from_seat=0, my_seat=1, num_players=4,
            pass_count=0, chow_pong_count=0,
            win_flags=WinFlags(),
        )
        assert len(claims['chow']) > 0

    def test_non_downstream_cannot_chow(self):
        hand = tiles('12b345c678d1c')
        discard = T('3b')
        claims = legal_claims(
            hand=hand, calls=[],
            discard=discard,
            from_seat=0, my_seat=2, num_players=4,
            pass_count=0, chow_pong_count=0,
            win_flags=WinFlags(),
        )
        assert claims['chow'] == []

    def test_face_down_no_claims(self):
        hand = tiles('12b345c678d1c')
        claims = legal_claims(
            hand=hand, calls=[],
            discard=T('5c'),
            from_seat=0, my_seat=1, num_players=4,
            pass_count=0, chow_pong_count=0,
            win_flags=WinFlags(),
            face_down=True,
        )
        assert not claims['chow']
        assert not claims['pong']
        assert not claims['kong']
        assert not claims['win']
        assert claims['skip']


# ---------------------------------------------------------------------------
# redraw
# ---------------------------------------------------------------------------

class TestRedraw:
    def test_honor_two_visible(self):
        # E is visible twice on the table
        assert is_redraw_eligible(
            drawn_tile=T('E'),
            own_river=[],
            own_open_calls=[],
            all_visible_tiles=[T('E'), T('E'), T('1b')],
        )

    def test_honor_one_visible_not_eligible(self):
        assert not is_redraw_eligible(
            drawn_tile=T('E'),
            own_river=[],
            own_open_calls=[],
            all_visible_tiles=[T('E')],
        )

    def test_own_discarded_honor_once(self):
        assert is_redraw_eligible(
            drawn_tile=T('E'),
            own_river=[T('E')],
            own_open_calls=[],
            all_visible_tiles=[T('E')],
        )

    def test_own_discarded_non_honor_twice(self):
        assert is_redraw_eligible(
            drawn_tile=T('5b'),
            own_river=[T('5b'), T('5b')],
            own_open_calls=[],
            all_visible_tiles=[T('5b'), T('5b')],
        )

    def test_own_discarded_non_honor_once_not_eligible(self):
        # Only one 5b in own river, last river tile is different → no condition fires
        assert not is_redraw_eligible(
            drawn_tile=T('5b'),
            own_river=[T('5b'), T('1c')],  # 5b discarded once, but last is 1c
            own_open_calls=[],
            all_visible_tiles=[T('5b'), T('1c')],
        )

    def test_same_as_last_in_river(self):
        assert is_redraw_eligible(
            drawn_tile=T('3c'),
            own_river=[T('1c'), T('3c')],
            own_open_calls=[],
            all_visible_tiles=[T('1c'), T('3c')],
        )

    def test_different_from_last_in_river(self):
        assert not is_redraw_eligible(
            drawn_tile=T('3c'),
            own_river=[T('3c'), T('1c')],   # last is 1c, not 3c
            own_open_calls=[],
            all_visible_tiles=[T('3c'), T('1c')],
        )
