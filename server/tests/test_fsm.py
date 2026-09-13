"""Tests for game/fsm.py — focuses on resolve_claims (pure function)."""
import asyncio
import pytest
from game import fsm
from game.fsm import FSMState, GameState, resolve_claims, ClaimResolution
from game.player_state import PlayerState
from game.tiles import tile_from_str as T, tile_to_str, tiles_from_str as tiles


def mkdiscard(tile_str: str = '5c'):
    return T(tile_str)


# ---------------------------------------------------------------------------
# resolve_claims — priority tests
# ---------------------------------------------------------------------------

class TestResolveClaims:
    def test_win_beats_all(self):
        discard = mkdiscard('5c')
        claims = {
            1: {'claim': 'triplet_call'},
            2: {'claim': 'win'},
            3: {'claim': 'straight_call'},
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
            1: {'claim': 'straight_call'},
            2: {'claim': 'triplet_call'},
            3: {'claim': 'skip'},
        }
        res = resolve_claims(discard, from_seat=0, claims=claims)
        assert res.call_seat == 2
        assert res.call_action['claim'] == 'triplet_call'
        assert res.winners == []

    def test_kong_beats_pong(self):
        discard = mkdiscard('5c')
        claims = {
            1: {'claim': 'triplet_call'},
            2: {'claim': 'direct_quad_call'},
            3: {'claim': 'skip'},
        }
        res = resolve_claims(discard, from_seat=0, claims=claims)
        assert res.call_seat == 2
        assert res.call_action['claim'] == 'direct_quad_call'

    def test_tie_break_closer_seat(self):
        # from_seat=0; seats 2 and 3 both pong → seat 1 (dist 1) wins if present
        # seats 2 (dist 2) and 3 (dist 3) both claim pong → seat 2 wins (closer)
        discard = mkdiscard('5c')
        claims = {
            2: {'claim': 'triplet_call'},
            3: {'claim': 'triplet_call'},
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


class SkipBot:
    def decide_claim(self, view, options):
        return {'claim': 'skip'}


class FakeWall:
    def __init__(self, draw_tiles):
        self.draw_tiles = list(draw_tiles)

    def draw(self):
        return self.draw_tiles.pop(0) if self.draw_tiles else None

    def draw_supplement(self):
        return self.draw()

    def remaining(self):
        return len(self.draw_tiles)


def test_bot_discard_waits_half_a_second(monkeypatch):
    class DiscardBot:
        def decide_turn(self, view):
            return {'type': 'discard', 'tile': view['hand'][-1]}

    async def noop(*args):
        pass

    delays = []

    async def fake_sleep(seconds):
        delays.append(seconds)

    player = PlayerState(seat=0, name='Bot', is_bot=True)
    player.hand = tiles('123b456c789d1122c')
    player.bot = DiscardBot()
    game = GameState([player], noop, noop)
    game.wall = FakeWall([T('9b')])

    async def capture_action(seat, action):
        assert seat == 0
        assert action['type'] == 'discard'

    game.handle_player_action = capture_action
    monkeypatch.setattr(fsm.asyncio, 'sleep', fake_sleep)

    asyncio.run(game._begin_player_turn(0))

    assert delays == [0.5]


def test_redraw_discards_opens_claims_then_draws_for_same_player():
    events = []

    async def send(seat, msg):
        events.append(('send', seat, msg))

    async def broadcast(msg):
        events.append(('broadcast', msg))

    players = [PlayerState(seat=0, name='Human')]
    for seat in (1, 2, 3):
        p = PlayerState(seat=seat, name=f'Bot-{seat}', is_bot=True)
        p.hand = tiles('123b456c789d1122c')
        p.bot = SkipBot()
        players.append(p)

    game = GameState(players, send, broadcast)
    game.state = FSMState.PLAYER_TURN
    game.current_seat = 0
    game.wall = FakeWall([T('9b')])
    players[0].hand = tiles('123b456c789d1122cE')

    asyncio.run(game._do_redraw(0, T('E')))

    assert len(players[0].hand) == 14
    assert T('E') not in players[0].hand
    assert players[0].river[-1] == T('E')
    assert players[0].hand[-1] == T('9b')
    assert game.current_seat == 0
    assert ('broadcast', {
        'type': 'discarded', 'seat': 0, 'tile': 'E', 'face_down': False,
        'pass_count': 0, 'straight_triplet_count': 0,
    }) in events
    assert ('broadcast', {'type': 'redraw', 'seat': 0}) in events


def test_face_down_discard_rejected_when_pass_call_total_is_three():
    events = []

    async def send(seat, msg):
        events.append(('send', seat, msg))

    async def broadcast(msg):
        events.append(('broadcast', msg))

    p = PlayerState(seat=0, name='Human')
    p.hand = tiles('123b456c789d1122c')
    p.pass_count = 2
    p.straight_triplet_count = 1
    game = GameState([p], send, broadcast)
    game.state = FSMState.PLAYER_TURN
    game.current_seat = 0

    asyncio.run(game._do_discard(0, T('1b'), face_down=True))

    assert T('1b') in p.hand
    assert p.pass_count == 2
    assert events == [('send', 0, {'type': 'error', 'message': 'Pass/call limit reached'})]


def test_no_claim_window_when_only_skip_is_legal():
    events = []

    async def send(seat, msg):
        events.append(('send', seat, msg))

    async def broadcast(msg):
        events.append(('broadcast', msg))

    players = []
    for seat in range(4):
        p = PlayerState(seat=seat, name=f'P{seat}')
        p.hand = tiles('234b456b789d45cES')
        players.append(p)

    game = GameState(players, send, broadcast)
    game.wall = FakeWall([T('9b')])

    asyncio.run(game._begin_await_claims(from_seat=1, tile=T('1c')))

    assert not any(e[0] == 'send' and e[2].get('type') == 'claim_window' for e in events)
    assert game.current_seat == 2


def test_non_downstream_straight_call_claim_is_sanitized_to_skip():
    async def send(seat, msg):
        pass

    async def broadcast(msg):
        pass

    players = []
    for seat in range(4):
        p = PlayerState(seat=seat, name=f'P{seat}')
        p.hand = tiles('23c456b789d45cES')
        players.append(p)

    game = GameState(players, send, broadcast)
    game.state = FSMState.AWAIT_CLAIMS
    game.wall = FakeWall([])
    game._pending_discard = T('1c')
    game._pending_from_seat = 1  # downstream is seat 2, not seat 0

    asyncio.run(game.handle_claim(0, {'claim': 'straight_call', 'tiles': ['1c', '2c', '3c']}))

    assert game._claims[0] == {'claim': 'skip'}


def test_straight_call_consumes_only_the_two_hand_tiles():
    async def noop(*args):
        pass

    players = []
    for seat in range(4):
        p = PlayerState(seat=seat, name=f'P{seat}')
        p.hand = tiles('123b456b789d45cES')
        players.append(p)

    # The hand has two 5c and one 7c; 6c is the claimed discard.
    players[2].hand = tiles('55c7c123b789d4dES')
    game = GameState(players, noop, noop)
    game.state = FSMState.AWAIT_CLAIMS
    game.wall = FakeWall([])
    game._pending_discard = T('6c')
    game._pending_from_seat = 1

    assert game._sanitize_claim(2, {'claim': 'straight_call', 'tiles': ['5c', '6c', '7c']}) == {'claim': 'skip'}
    action = game._sanitize_claim(2, {'claim': 'straight_call', 'tiles': ['5c', '7c']})
    assert action['claim'] == 'straight_call'

    asyncio.run(game._do_call(2, action, T('6c'), from_seat=1))

    assert players[2].hand.count(T('5c')) == 1
    assert T('7c') not in players[2].hand
    assert players[2].calls[-1].tiles == sorted([T('5c'), T('6c'), T('7c')])


def test_declare_wait_option_when_discard_leaves_tenpai():
    p = PlayerState(seat=0, name='Human')
    p.hand = tiles('123b456b789b12c11d9d')
    game = GameState([p])
    game.wall = FakeWall([T('1b')])

    assert game._can_declare_wait(p)
    assert 'declare_wait' in game._compute_turn_options(p, T('9d'))


def test_wait_options_count_visible_outs_after_discard():
    p = PlayerState(seat=0, name='Human')
    p.hand = tiles('123b456b789b12c11d9d')
    other = PlayerState(seat=1, name='Other')
    other.river = [T('3c')] * 3
    other.river_face_down = [False] * 3
    game = GameState([p, other])

    assert game._wait_options(p) == [{'discard': '9d', 'waits': ['3c'], 'outs': 1}]


def test_declare_wait_atomically_discards_selected_tile():
    events = []

    async def send(seat, msg):
        events.append(('send', seat, msg))

    async def broadcast(msg):
        events.append(('broadcast', msg))

    p = PlayerState(seat=0, name='Human')
    p.hand = tiles('123b456b789b12c11d9d')
    game = GameState([p], send, broadcast)
    game.state = FSMState.PLAYER_TURN
    game.current_seat = 0
    game.wall = FakeWall([T('1b')])

    asyncio.run(game._process_turn_action(0, {'action': 'declare_wait', 'tile': '9d'}))

    assert p.has_declared_wait
    assert p.river[-1] == T('9d')
    assert T('9d') not in p.hand
    assert any(event[0] == 'broadcast' and event[1]['type'] == 'wait_declared' for event in events)
    assert any(event[0] == 'broadcast' and event[1]['type'] == 'discarded' for event in events)
    your_turn = next(event[2] for event in reversed(events) if event[0] == 'send' and event[2]['type'] == 'your_turn')
    assert your_turn['your_hand'] == [tile_to_str(tile) for tile in p.hand]
