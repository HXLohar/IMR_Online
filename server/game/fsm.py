"""
Turn / claim state machine for IMR Online.

States: WAITING → DEALING → PLAYER_TURN → AWAIT_CLAIMS → KONG_DRAW
        → HAND_END | EXHAUSTIVE_DRAW → MATCH_END

All state is held on the GameState object.  The FSM exposes two public methods:
  - handle_player_action(seat, action) → list[Event]
  - handle_claim(seat, claim_action) → list[Event]

Events are plain dicts that the room layer forwards to WebSocket clients.
The resolve_claims() helper is a pure function for easy unit-testing.
"""
from __future__ import annotations
import asyncio
import os
import time
from dataclasses import dataclass
from enum import Enum, auto
from typing import Callable, Awaitable

from game.tiles import Tile, tile_to_str
from game.wall import Wall
from game.player_state import PlayerState
from game.legal import (
    can_straight_call, can_triplet_call, can_direct_quad_call,
    can_upgraded_quad_declare, can_concealed_quad_declare,
    can_win_on_discard, can_win_self_drawn,
    can_add_straight_triplet_call, can_add_pass, legal_claims,
)
from game.redraw import is_redraw_eligible
from game.settle import settle_wins, settle_exhaustive_draw
from scoring.parsing import Call, CallType
from scoring.api import WinFlags, waits

STRAIGHT_CALL = 'straight_call'


def _bot_delay() -> float:
    return max(0.0, float(os.getenv('IMR_BOT_DELAY_SECONDS', '0.5')))
TRIPLET_CALL = 'triplet_call'
DIRECT_QUAD_CALL = 'direct_quad_call'
UPGRADED_QUAD_DECLARE = 'upgraded_quad_declare'
CONCEALED_QUAD_DECLARE = 'concealed_quad_declare'
DECLARE_WAIT = 'declare_wait'

# ---------------------------------------------------------------------------
# State enum
# ---------------------------------------------------------------------------

class FSMState(Enum):
    WAITING = auto()
    DEALING = auto()
    PLAYER_TURN = auto()
    AWAIT_CLAIMS = auto()
    KONG_DRAW = auto()
    HAND_END = auto()
    EXHAUSTIVE_DRAW = auto()
    MATCH_END = auto()


# ---------------------------------------------------------------------------
# Claim resolution (pure function — unit-testable)
# ---------------------------------------------------------------------------

@dataclass
class ClaimResolution:
    winners: list[int]    # seats declaring win (多响)
    call_seat: int | None # seat making straight/triplet/quad call (None if no call)
    call_action: dict | None


def resolve_claims(
    discard: Tile,
    from_seat: int,
    claims: dict[int, dict],   # seat -> {'claim': str, ...}
    num_players: int = 4,
) -> ClaimResolution:
    """
    Resolve competing claims according to IMR priority:
      win > direct quad call > triplet call > straight call
    Ties in same priority → smallest circular distance from from_seat (next seat wins).
    Multi-win (一炮多響): ALL win claims succeed simultaneously.
    """
    winners = [s for s, c in claims.items() if c.get('claim') == 'win']
    if winners:
        return ClaimResolution(winners=winners, call_seat=None, call_action=None)

    def priority(claim: str) -> int:
        return {DIRECT_QUAD_CALL: 3, TRIPLET_CALL: 2, STRAIGHT_CALL: 1}.get(claim, 0)

    best_prio = 0
    best_seat: int | None = None
    best_action: dict | None = None

    for seat, action in claims.items():
        claim = action.get('claim', 'skip')
        p = priority(claim)
        if p == 0:
            continue
        if p > best_prio:
            best_prio = p
            best_seat = seat
            best_action = action
        elif p == best_prio:
            # Tie-break: closer to from_seat (circular)
            dist_new = (seat - from_seat) % num_players
            dist_cur = (best_seat - from_seat) % num_players
            if dist_new < dist_cur:
                best_seat = seat
                best_action = action

    return ClaimResolution(winners=[], call_seat=best_seat, call_action=best_action)


# ---------------------------------------------------------------------------
# GameState
# ---------------------------------------------------------------------------

class GameState:
    def __init__(
        self,
        players: list[PlayerState],
        send_fn: Callable[[int, dict], Awaitable[None]] | None = None,
        broadcast_fn: Callable[[dict], Awaitable[None]] | None = None,
        seed: int | None = None,
        hand_complete_fn: Callable[[dict], Awaitable[None]] | None = None,
        timeout_fn: Callable[[str, int], Awaitable[None]] | None = None,
    ):
        self.players = players
        self.num_players = len(players)
        self.send = send_fn or (lambda seat, msg: None)
        self.broadcast = broadcast_fn or (lambda msg: None)
        self._seed = seed
        self.hand_complete_fn = hand_complete_fn
        self.timeout_fn = timeout_fn

        self.state = FSMState.WAITING
        self.wall: Wall | None = None
        self.current_seat: int = 0
        self.dealer: int = 0

        # Pending discard info during AWAIT_CLAIMS
        self._pending_discard: Tile | None = None
        self._pending_from_seat: int = 0
        self._claims: dict[int, dict] = {}     # seat -> claim action
        self._claims_received: int = 0
        self._claim_options: dict[int, list[str]] = {}
        self._no_claim_next_seat: int | None = None
        self._no_claim_quad_draw_seat: int | None = None

        # Monotonic IDs make late client messages harmless, while wall-clock
        # deadlines are sent to clients for reconnect-safe display.
        self.turn_id = 0
        self.turn_deadline_at: float | None = None
        self.window_id = 0
        self.window_deadline_at: float | None = None
        self._timeout_task: asyncio.Task | None = None
        self._turn_flags = WinFlags()
        self._opening_wait: dict[int, bool] = {}
        self._draw_count = 0
        self._pending_robbing_quad = False
        self._called_river_tiles: dict[int, list[int]] = {}

    def _cancel_timeout(self) -> None:
        task = self._timeout_task
        self._timeout_task = None
        if task is not None and task is not asyncio.current_task():
            task.cancel()
        self.turn_deadline_at = None
        self.window_deadline_at = None

    def _open_turn_clock(self, seconds: float = 60.0) -> None:
        self._cancel_timeout()
        self.turn_id += 1
        self.turn_deadline_at = time.time() + seconds
        if self.timeout_fn:
            self._timeout_task = asyncio.create_task(self._timeout_after('turn', self.turn_id, seconds))

    def _open_claim_clock(self, seconds: float) -> None:
        self._cancel_timeout()
        self.window_id += 1
        self.window_deadline_at = time.time() + seconds
        if self.timeout_fn:
            self._timeout_task = asyncio.create_task(self._timeout_after('claim', self.window_id, seconds))

    async def _timeout_after(self, kind: str, serial: int, seconds: float) -> None:
        try:
            await asyncio.sleep(seconds)
            if self.timeout_fn:
                await self.timeout_fn(kind, serial)
        except asyncio.CancelledError:
            return

    async def timeout(self, kind: str, serial: int) -> None:
        """Apply a timeout only if its serial still names the live phase."""
        if kind == 'turn' and self.state == FSMState.PLAYER_TURN and serial == self.turn_id:
            p = self.players[self.current_seat]
            self._cancel_timeout()
            await self.broadcast({'type': 'turn_timeout', 'seat': self.current_seat, 'turn_id': serial})
            if p.hand:
                await self._do_discard(self.current_seat, p.hand[-1], False)
        elif kind == 'claim' and self.state == FSMState.AWAIT_CLAIMS and serial == self.window_id:
            self._cancel_timeout()
            await self.broadcast({'type': 'claim_timeout', 'window_id': serial})
            for seat in range(self.num_players):
                if seat != self._pending_from_seat and seat not in self._claims:
                    self._claims[seat] = {'claim': 'skip'}
                    self._claims_received += 1
            await self._resolve_claims_phase()

    # ------------------------------------------------------------------
    # Entry points
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Transition WAITING → DEALING → PLAYER_TURN."""
        await self._deal()

    async def handle_player_action(self, seat: int, action: dict) -> None:
        """Called when a player (human or bot) submits a self-action."""
        if self.state != FSMState.PLAYER_TURN:
            await self.send(seat, {'type': 'error', 'message': 'Not your turn'})
            return
        if seat != self.current_seat:
            await self.send(seat, {'type': 'error', 'message': 'Not your seat'})
            return
        await self._process_turn_action(seat, action)

    async def handle_claim(self, seat: int, claim_action: dict) -> None:
        """Called when a player submits a claim during AWAIT_CLAIMS."""
        if self.state != FSMState.AWAIT_CLAIMS:
            return
        if seat not in self._claims:
            claim_action = self._sanitize_claim(seat, claim_action)
            self._claims[seat] = claim_action
            self._claims_received += 1
            if self._claims_received == self.num_players - 1:
                await self._resolve_claims_phase()

    # ------------------------------------------------------------------
    # Deal
    # ------------------------------------------------------------------

    async def _deal(self) -> None:
        self._cancel_timeout()
        self.state = FSMState.DEALING
        self.wall = Wall(seed=self._seed)
        self._draw_count = 0
        self._opening_wait = {}
        self._pending_robbing_quad = False
        self._called_river_tiles = {}

        for p in self.players:
            p.reset_for_new_hand()

        hands = self.wall.deal(self.num_players)
        for i, p in enumerate(self.players):
            p.hand = list(hands[i])
            if i != self.dealer:
                self._opening_wait[i] = bool(waits(p.hand, p.calls))
            if p.is_bot:
                await self._debug_log(f"{p.name} opening hand: {''.join(tile_to_str(t) for t in p.hand)}")

        await self.broadcast({
            'type': 'game_start',
            'dealer': self.dealer,
            'wall_count': self.wall.remaining(),
        })
        # Send individual hand info
        for p in self.players:
            await self.send(p.seat, {
                'type': 'game_start',
                'dealer': self.dealer,
                'your_seat': p.seat,
                'your_hand': [tile_to_str(t) for t in p.hand],
                'wall_count': self.wall.remaining(),
            })

        self.current_seat = self.dealer
        await self._begin_player_turn(self.current_seat)

    # ------------------------------------------------------------------
    # Player turn
    # ------------------------------------------------------------------

    async def _begin_player_turn(self, seat: int) -> None:
        self.state = FSMState.PLAYER_TURN
        tile = self.wall.draw()
        if tile is None:
            await self._exhaustive_draw()
            return

        p = self.players[seat]
        p.draw(tile)
        self._turn_flags = WinFlags(
            self_drawn=True,
            last_tile=(self.wall.remaining() == 0),
            heavenly=(self._draw_count == 0 and seat == self.dealer),
            earthly=(self._draw_count == 1 and seat != self.dealer and not p.calls and not p.river),
            heavenly_wait=(self._draw_count == 1 and seat != self.dealer
                           and self._opening_wait.get(seat, False)
                           and not p.calls and not p.river),
        )
        self._draw_count += 1
        self._open_turn_clock()

        await self.broadcast({
            'type': 'tile_drawn',
            'seat': seat,
            'wall_count': self.wall.remaining(),
        })

        # Compute options for this player
        options = self._compute_turn_options(p, tile)

        await self.send(seat, {
            'type': 'your_turn',
            'drawn': tile_to_str(tile),
            'options': options,
            'redraw_eligible': 'redraw' in options,
            'pass_count': p.pass_count,
            'straight_triplet_count': p.straight_triplet_count,
            'turn_id': self.turn_id,
            'deadline_at_ms': int(self.turn_deadline_at * 1000),
        })

        # Let bot discards remain visible before advancing the turn.
        if p.is_bot:
            bot = p.bot
            view = self._build_view(seat)
            view['options'] = options
            action = bot.decide_turn(view)
            await self._debug_log(f"{p.name} turn hand={view['hand']} options={options} action={action}")
            if (action.get('action') or action.get('type')) == 'discard':
                await asyncio.sleep(_bot_delay())
            await self.handle_player_action(seat, action)

    def _compute_turn_options(self, p: PlayerState, drawn_tile: Tile) -> list[str]:
        options: list[str] = ['discard']

        # Tsumo win
        flags = self._turn_flags
        if can_win_self_drawn(p.hand[:-1], p.calls, drawn_tile, flags):
            options.append('tsumo')

        # Concealed quad declare
        concealed_quads = can_concealed_quad_declare(p.hand[:-1], drawn_tile)
        if concealed_quads and (not p.has_declared_wait or any(self._self_quad_keeps_wait(p, t, False) for t in concealed_quads)):
            options.append(CONCEALED_QUAD_DECLARE)

        # Upgraded quad declare
        upgraded_quads = can_upgraded_quad_declare(p.hand[:-1], p.calls, drawn_tile)
        if upgraded_quads and (not p.has_declared_wait or any(self._self_quad_keeps_wait(p, t, True) for t in upgraded_quads)):
            options.append(UPGRADED_QUAD_DECLARE)

        # Redraw
        all_vis = self._all_visible_tiles()
        if is_redraw_eligible(
            drawn_tile,
            own_river=p.all_visible_discards(),
            all_visible_tiles=all_vis,
        ):
            options.append('redraw')

        # Declare wait (报听) — only concealed hands
        if not p.has_declared_wait and self._is_concealed(p):
            if self._can_declare_wait(p):
                options.append(DECLARE_WAIT)

        return options

    async def _process_turn_action(self, seat: int, action: dict) -> None:
        p = self.players[seat]
        act = action.get('action') or action.get('type')

        if act == 'discard':
            tile_str = action.get('tile')
            face_down = bool(action.get('face_down', False))
            tile = next((t for t in p.hand if tile_to_str(t) == tile_str), None)
            if tile is None:
                await self.send(seat, {'type': 'error', 'message': f'Tile {tile_str} not in hand'})
                return
            if p.has_declared_wait and not self._discard_keeps_wait(p, tile):
                if p.is_bot:
                    tile = next((candidate for candidate in p.hand
                                 if self._discard_keeps_wait(p, candidate)), None)
                    if tile is not None:
                        await self._do_discard(seat, tile, face_down)
                        return
                await self.send(seat, {'type': 'error', 'message': 'Discard would break declared-wait hand'})
                return
            await self._do_discard(seat, tile, face_down)

        elif act == 'tsumo':
            tile = p.hand[-1]  # last drawn
            flags = self._turn_flags
            if not can_win_self_drawn(p.hand[:-1], p.calls, tile, flags):
                await self.send(seat, {'type': 'error', 'message': 'Invalid tsumo'})
                return
            await self._do_tsumo(seat, tile)

        elif act in (CONCEALED_QUAD_DECLARE, UPGRADED_QUAD_DECLARE):
            tile_str = action.get('tile')
            tile = next((t for t in p.hand if tile_to_str(t) == tile_str), None)
            if tile is None:
                await self.send(seat, {'type': 'error', 'message': f'Tile {tile_str} not in hand'})
                return
            if p.has_declared_wait and not self._self_quad_keeps_wait(p, tile, is_added=(act == UPGRADED_QUAD_DECLARE)):
                await self.send(seat, {'type': 'error', 'message': 'Quad would break declared-wait hand'})
                return
            await self._do_self_quad(seat, tile, is_added=(act == UPGRADED_QUAD_DECLARE))

        elif act == 'redraw':
            tile = p.hand[-1]
            all_vis = self._all_visible_tiles()
            if not is_redraw_eligible(tile, p.all_visible_discards(), all_vis):
                await self.send(seat, {'type': 'error', 'message': 'Redraw not eligible'})
                return
            await self._do_redraw(seat, tile)

        elif act == DECLARE_WAIT:
            tile_str = action.get('tile')
            tile = next((t for t in p.hand if tile_to_str(t) == tile_str), None)
            # Bots may omit the tile; choose a discard that actually preserves
            # tenpai so the atomic declare+discard cannot strand the hand.
            if tile is None and p.is_bot:
                tile = None
                for candidate in p.hand:
                    hand_after = list(p.hand)
                    hand_after.remove(candidate)
                    if waits(hand_after, p.calls):
                        tile = candidate
                        break
            if tile is None or not self._is_concealed(p):
                await self.send(seat, {'type': 'error', 'message': 'Cannot declare wait'})
                return
            hand_after = list(p.hand)
            hand_after.remove(tile)
            declared_waits = waits(hand_after, p.calls)
            if not declared_waits:
                await self.send(seat, {'type': 'error', 'message': 'Discard must leave a waiting hand'})
                return
            p.has_declared_wait = True
            p.declared_waits = list(declared_waits)
            await self.broadcast({'type': 'wait_declared', 'seat': seat,
                                  'waits': [tile_to_str(t) for t in declared_waits]})
            await self._do_discard(seat, tile, False)

        else:
            await self.send(seat, {'type': 'error', 'message': f'Unknown action: {act}'})

    # ------------------------------------------------------------------
    # Discard
    # ------------------------------------------------------------------

    async def _do_discard(self, seat: int, tile: Tile, face_down: bool) -> None:
        p = self.players[seat]

        if p.has_declared_wait and not self._discard_keeps_wait(p, tile):
            await self.send(seat, {'type': 'error', 'message': 'Discard would break declared-wait hand'})
            return

        # Validate rang_guo legality
        if face_down:
            if not can_add_pass(p.pass_count, p.straight_triplet_count):
                await self.send(seat, {'type': 'error', 'message': 'Pass/call limit reached'})
                return

        p.discard(tile, face_down)

        await self.broadcast({
            'type': 'discarded',
            'seat': seat,
            'tile': tile_to_str(tile) if not face_down else None,
            'face_down': face_down,
            'pass_count': p.pass_count,
            'straight_triplet_count': p.straight_triplet_count,
        })

        if face_down:
            # Face-down discard: no claims, proceed to next player
            self.current_seat = (seat + 1) % self.num_players
            await self._begin_player_turn(self.current_seat)
            return

        # Open discard: enter AWAIT_CLAIMS phase
        await self._begin_await_claims(seat, tile)

    # ------------------------------------------------------------------
    # Claims window
    # ------------------------------------------------------------------

    async def _begin_await_claims(
        self,
        from_seat: int,
        tile: Tile,
        no_claim_next_seat: int | None = None,
    ) -> None:
        self.state = FSMState.AWAIT_CLAIMS
        self._pending_discard = tile
        self._pending_from_seat = from_seat
        self._pending_robbing_quad = False
        self._claims = {}
        self._claims_received = 0
        self._claim_options = {}
        self._no_claim_next_seat = no_claim_next_seat
        self._no_claim_quad_draw_seat = None
        self._open_claim_clock(5.0)

        # Notify each other player of their options
        bot_claims: list[tuple[int, dict]] = []

        for s in range(self.num_players):
            if s == from_seat:
                continue
            p = self.players[s]
            flags = self._claim_win_flags(s, from_seat)
            claims = legal_claims(
                hand=p.hand,
                calls=p.calls,
                discard=tile,
                from_seat=from_seat,
                my_seat=s,
                num_players=self.num_players,
                pass_count=p.pass_count,
                straight_triplet_count=p.straight_triplet_count,
                win_flags=flags,
                face_down=False,
                has_declared_wait=p.has_declared_wait,
            )

            # Build option list for the client
            options = []
            if claims['win']:
                options.append('win')
            if claims['triplet_call']:
                options.append(TRIPLET_CALL)
            if claims['direct_quad_call']:
                options.append(DIRECT_QUAD_CALL)
            for straight_call in claims['straight_call']:
                options.append(STRAIGHT_CALL)
                break  # client picks which tiles; signal availability
            options.append('skip')

            if options == ['skip']:
                self._claims[s] = {'claim': 'skip'}
                self._claims_received += 1
                continue

            self._claim_options[s] = options

            await self.send(s, {
                'type': 'claim_window',
                'tile': tile_to_str(tile),
                'from_seat': from_seat,
                'your_options': options,
                'pass_count': p.pass_count,
                'straight_triplet_count': p.straight_triplet_count,
                'deadline_ms': 5000,
                'window_id': self.window_id,
                'deadline_at_ms': int(self.window_deadline_at * 1000),
            })

            if p.is_bot:
                bot = p.bot
                bot_action = bot.decide_claim(self._build_view(s), options)
                await self._debug_log(f"{p.name} claim tile={tile_to_str(tile)} options={options} action={bot_action}")
                bot_claims.append((s, bot_action))

        # Bots respond immediately
        for s, action in bot_claims:
            await self.handle_claim(s, action)

        if self.state == FSMState.AWAIT_CLAIMS and self._claims_received == self.num_players - 1:
            await self._resolve_claims_phase()

        # If all non-discarder seats are bots, claims may already be resolved
        # (handled inside handle_claim). If there's a human player still
        # waiting, we wait for their claim or the timeout.

    async def _resolve_claims_phase(self) -> None:
        self._cancel_timeout()
        from_seat = self._pending_from_seat
        tile = self._pending_discard
        resolution = resolve_claims(tile, from_seat, self._claims, self.num_players)

        if resolution.winners:
            await self._do_ron(resolution.winners, tile, from_seat)
            return

        if resolution.call_seat is not None:
            await self._do_call(resolution.call_seat, resolution.call_action, tile, from_seat)
            return

        # No claims: normal discard passes to next seat; redraw returns to discarder.
        await self._continue_after_no_claim()

    # ------------------------------------------------------------------
    # Win
    # ------------------------------------------------------------------

    async def _do_tsumo(self, seat: int, tile: Tile) -> None:
        p = self.players[seat]
        flags = WinFlags(
            self_drawn=self._turn_flags.self_drawn,
            last_tile=self._turn_flags.last_tile,
            declared_wait=p.has_declared_wait,
            after_quad=self._turn_flags.after_quad,
            heavenly=self._turn_flags.heavenly,
            earthly=self._turn_flags.earthly,
            heavenly_wait=self._turn_flags.heavenly_wait,
        )
        result = settle_wins(
            winners_data=[(seat, tile, 'tsumo', -1)],
            player_hands={s: self.players[s].hand[:-1] for s in range(self.num_players)},
            player_calls={s: self.players[s].calls for s in range(self.num_players)},
            player_pass_count={s: self.players[s].pass_count for s in range(self.num_players)},
            player_declared_wait={s: self.players[s].has_declared_wait for s in range(self.num_players)},
            flags_extra={seat: flags},
        )
        if not result.winners:
            await self.send(seat, {'type': 'error', 'message': 'Threshold not met'})
            return
        await self._end_hand(result)

    async def _do_ron(self, winner_seats: list[int], tile: Tile, from_seat: int) -> None:
        winners_data = []
        for ws in winner_seats:
            winners_data.append((ws, tile, 'ron', from_seat))

        all_flags = {}
        for ws in winner_seats:
            p = self.players[ws]
            flags = self._claim_win_flags(ws, from_seat)
            flags.declared_wait = p.has_declared_wait
            all_flags[ws] = flags

        result = settle_wins(
            winners_data=winners_data,
            player_hands={s: self.players[s].hand for s in range(self.num_players)},
            player_calls={s: self.players[s].calls for s in range(self.num_players)},
            player_pass_count={s: self.players[s].pass_count for s in range(self.num_players)},
            player_declared_wait={s: self.players[s].has_declared_wait for s in range(self.num_players)},
            flags_extra=all_flags,
        )
        if not result.winners:
            # All claims failed threshold; no claim succeeds
            await self._continue_after_no_claim()
            return
        await self._end_hand(result)

    # ------------------------------------------------------------------
    # Calls (straight/triplet/direct quad)
    # ------------------------------------------------------------------

    async def _do_call(self, seat: int, action: dict, tile: Tile, from_seat: int) -> None:
        p = self.players[seat]
        claim = action.get('claim')
        claimed_index = len(self.players[from_seat].river) - 1

        if claim == TRIPLET_CALL:
            if not can_add_straight_triplet_call(p.pass_count, p.straight_triplet_count):
                await self.send(seat, {'type': 'error', 'message': 'Pass/call limit reached'})
                return
            p.hand.remove(tile)
            p.hand.remove(tile)
            call = Call(CallType.TRIPLET, [tile, tile, tile])
            p.add_call(call, is_straight_or_triplet=True)
            self._called_river_tiles.setdefault(from_seat, []).append(claimed_index)
            await self.broadcast({
                'type': 'call_made', 'seat': seat, 'call': TRIPLET_CALL,
                'tiles': [tile_to_str(tile)] * 3, 'from_seat': from_seat,
                'pass_count': p.pass_count, 'straight_triplet_count': p.straight_triplet_count,
            })

        elif claim == DIRECT_QUAD_CALL:
            if p.has_declared_wait and not self._direct_quad_keeps_wait(p, tile):
                await self.send(seat, {'type': 'error', 'message': 'Quad would break declared-wait hand'})
                return
            for _ in range(3):
                p.hand.remove(tile)
            call = Call(CallType.QUAD, [tile] * 4)
            p.add_call(call, is_straight_or_triplet=False)
            self._called_river_tiles.setdefault(from_seat, []).append(claimed_index)
            await self.broadcast({
                'type': 'call_made', 'seat': seat, 'call': DIRECT_QUAD_CALL,
                'tiles': [tile_to_str(tile)] * 4, 'from_seat': from_seat,
                'pass_count': p.pass_count, 'straight_triplet_count': p.straight_triplet_count,
            })
            await self._begin_quad_draw(seat)
            return

        elif claim == STRAIGHT_CALL:
            if not can_add_straight_triplet_call(p.pass_count, p.straight_triplet_count):
                await self.send(seat, {'type': 'error', 'message': 'Pass/call limit reached'})
                return
            # Find the specific straight call
            chosen_tiles = action.get('tiles', [])
            straight_hand_tiles = [t for t in p.hand if tile_to_str(t) in chosen_tiles]
            if len(straight_hand_tiles) < 2:
                # Fallback: pick first valid straight call
                options = can_straight_call(p.hand, tile, p.pass_count, p.straight_triplet_count)
                if not options:
                    await self.send(seat, {'type': 'error', 'message': 'Invalid straight call'})
                    return
                straight_call = options[0]
                straight_hand_tiles = [t for t in straight_call.tiles if t != tile]
            for t in straight_hand_tiles[:2]:
                p.hand.remove(t)
            straight_tiles_full = sorted([tile] + straight_hand_tiles[:2])
            call = Call(CallType.STRAIGHT, straight_tiles_full)
            p.add_call(call, is_straight_or_triplet=True)
            self._called_river_tiles.setdefault(from_seat, []).append(claimed_index)
            await self.broadcast({
                'type': 'call_made', 'seat': seat, 'call': STRAIGHT_CALL,
                'tiles': [tile_to_str(t) for t in straight_tiles_full], 'from_seat': from_seat,
                'pass_count': p.pass_count, 'straight_triplet_count': p.straight_triplet_count,
            })

        # After triplet/straight call: player must discard
        self.current_seat = seat
        self.state = FSMState.PLAYER_TURN
        self._open_turn_clock()
        options = ['discard']

        await self.send(seat, {
            'type': 'your_turn',
            'drawn': None,
            'options': options,
            'redraw_eligible': False,
            'pass_count': p.pass_count,
            'straight_triplet_count': p.straight_triplet_count,
            'turn_id': self.turn_id,
            'deadline_at_ms': int(self.turn_deadline_at * 1000),
        })

        if p.is_bot:
            bot = p.bot
            view = self._build_view(seat)
            view['options'] = options
            discard_action = bot.decide_turn(view)
            await self._debug_log(f"{p.name} after call hand={view['hand']} options={options} action={discard_action}")
            if (discard_action.get('action') or discard_action.get('type')) == 'discard':
                await asyncio.sleep(_bot_delay())
            await self.handle_player_action(seat, discard_action)

    # ------------------------------------------------------------------
    # Self quad declare
    # ------------------------------------------------------------------

    async def _do_self_quad(self, seat: int, tile: Tile, is_added: bool) -> None:
        p = self.players[seat]

        if is_added:
            # Remove the added tile from hand, upgrade triplet call to quad
            p.hand.remove(tile)
            for i, call in enumerate(p.calls):
                if call.call_type == CallType.TRIPLET and call.tiles[0] == tile:
                    p.calls[i] = Call(CallType.QUAD, [tile] * 4)
                    break
        else:
            # Concealed quad declare
            for _ in range(4):
                p.hand.remove(tile)
            p.calls.append(Call(CallType.CONCEALED_QUAD, [tile] * 4))

        await self.broadcast({
            'type': 'call_made', 'seat': seat,
            'call': UPGRADED_QUAD_DECLARE if is_added else CONCEALED_QUAD_DECLARE,
            'tiles': [tile_to_str(tile)] * 4, 'from_seat': seat,
            'pass_count': p.pass_count, 'straight_triplet_count': p.straight_triplet_count,
        })

        # For an upgraded quad declare, other players may rob the quad.
        if is_added:
            await self._begin_quad_rob_window(seat, tile)
        else:
            await self._begin_quad_draw(seat)

    async def _begin_quad_rob_window(self, quad_seat: int, tile: Tile) -> None:
        """Allow others to rob an upgraded quad declare (搶槓 win)."""
        self.state = FSMState.AWAIT_CLAIMS
        self._pending_discard = tile
        self._pending_from_seat = quad_seat
        self._pending_robbing_quad = True
        self._claims = {}
        self._claims_received = 0
        self._claim_options = {}
        self._no_claim_next_seat = None
        self._no_claim_quad_draw_seat = quad_seat
        self._open_claim_clock(3.0)

        bot_claims = []
        for s in range(self.num_players):
            if s == quad_seat:
                continue
            p = self.players[s]
            flags = WinFlags(robbing_quad=True, last_tile=(self.wall.remaining() == 0))
            can_win = can_win_on_discard(p.hand, p.calls, tile, flags)
            options = ['win'] if can_win else ['skip']

            await self.send(s, {
                'type': 'claim_window',
                'tile': tile_to_str(tile),
                'from_seat': quad_seat,
                'your_options': options,
                'deadline_ms': 3000,
                'window_id': self.window_id,
                'deadline_at_ms': int(self.window_deadline_at * 1000),
            })
            self._claim_options[s] = options

            if p.is_bot:
                bot = p.bot
                bot_action = bot.decide_claim(self._build_view(s), options)
                await self._debug_log(f"{p.name} rob-quad tile={tile_to_str(tile)} options={options} action={bot_action}")
                bot_claims.append((s, bot_action))

        for s, action in bot_claims:
            await self.handle_claim(s, action)

        # If nobody robs: proceed to quad supplement draw
        # (handled in _resolve_claims_phase if all skip or via timeout)

    async def _begin_quad_draw(self, seat: int) -> None:
        """Draw supplement tile from dead wall after a quad."""
        self.state = FSMState.KONG_DRAW
        tile = self.wall.draw_supplement()
        if tile is None:
            await self._exhaustive_draw()
            return

        p = self.players[seat]
        p.draw(tile)

        await self.broadcast({
            'type': 'tile_drawn', 'seat': seat, 'wall_count': self.wall.remaining(),
        })

        # Check win after quad supplement (嶺上開花)
        self._turn_flags = WinFlags(self_drawn=True, after_quad=True,
                                    last_tile=(self.wall.remaining() == 0))
        flags = self._turn_flags
        options = ['discard']
        if can_win_self_drawn(p.hand[:-1], p.calls, tile, flags):
            options.append('tsumo')

        self.state = FSMState.PLAYER_TURN
        self.current_seat = seat
        self._open_turn_clock()

        await self.send(seat, {
            'type': 'your_turn',
            'drawn': tile_to_str(tile),
            'options': options,
            'redraw_eligible': False,
            'pass_count': p.pass_count,
            'straight_triplet_count': p.straight_triplet_count,
            'turn_id': self.turn_id,
            'deadline_at_ms': int(self.turn_deadline_at * 1000),
        })

        if p.is_bot:
            bot = p.bot
            view = self._build_view(seat)
            view['options'] = options
            action = bot.decide_turn(view)
            await self._debug_log(f"{p.name} quad draw hand={view['hand']} options={options} action={action}")
            if (action.get('action') or action.get('type')) == 'discard':
                await asyncio.sleep(_bot_delay())
            await self.handle_player_action(seat, action)

    # ------------------------------------------------------------------
    # Redraw
    # ------------------------------------------------------------------

    async def _do_redraw(self, seat: int, tile: Tile) -> None:
        p = self.players[seat]
        p.discard(tile, face_down=False)

        await self.broadcast({
            'type': 'discarded',
            'seat': seat,
            'tile': tile_to_str(tile),
            'face_down': False,
            'pass_count': p.pass_count,
            'straight_triplet_count': p.straight_triplet_count,
        })
        await self.broadcast({'type': 'redraw', 'seat': seat})
        await self._begin_await_claims(seat, tile, no_claim_next_seat=seat)

    # ------------------------------------------------------------------
    # End states
    # ------------------------------------------------------------------

    async def _end_hand(self, result) -> None:
        self._cancel_timeout()
        self.state = FSMState.HAND_END

        winners_payload = []
        for w in result.winners:
            fans_payload = [
                {'id': af.fan.id, 'name': af.fan.name_c or af.fan.name_e, 'value': af.score}
                for af in w.scoring.achieved_fans
            ]
            winners_payload.append({
                'seat': w.seat,
                'win_type': w.win_type,
                'from_seat': w.from_seat,
                'hand': [tile_to_str(t) for t in self.players[w.seat].hand]
                        + ([tile_to_str(w.scoring.explanation.winning_tile)] if w.win_type == 'ron' else []),
                'calls': [str(c) for c in self.players[w.seat].calls],
                'fans': fans_payload,
                'raw_score': w.scoring.total_score,
                'final_score': w.final_score,
            })

        for p in self.players:
            p.score += result.payments.get(p.seat, 0)

        await self.broadcast({
            'type': 'hand_result',
            'winners': winners_payload,
            'payments': {str(k): v for k, v in result.payments.items()},
            'scores': {str(p.seat): p.score for p in self.players},
        })

        self.state = FSMState.MATCH_END
        if self.hand_complete_fn:
            await self.hand_complete_fn({'type': 'hand_result', 'winners': winners_payload,
                                         'payments': {str(k): v for k, v in result.payments.items()}})

    async def _exhaustive_draw(self) -> None:
        self._cancel_timeout()
        self.state = FSMState.EXHAUSTIVE_DRAW

        result = settle_exhaustive_draw(
            player_pass_count={s: self.players[s].pass_count for s in range(self.num_players)},
            player_straight_triplet_count={s: self.players[s].straight_triplet_count for s in range(self.num_players)},
            player_hands={s: self.players[s].hand for s in range(self.num_players)},
            player_calls={s: self.players[s].calls for s in range(self.num_players)},
        )

        from scoring.api import waits as _waits
        tenpai = [s for s in range(self.num_players) if _waits(self.players[s].hand, self.players[s].calls)]

        for p in self.players:
            p.score += result.payments.get(p.seat, 0)

        await self.broadcast({
            'type': 'draw_result',
            'tenpai_seats': tenpai,
            'payments': {str(k): v for k, v in result.payments.items()},
            'scores': {str(p.seat): p.score for p in self.players},
            'hands': {str(p.seat): [tile_to_str(t) for t in p.hand] for p in self.players},
            'calls': {str(p.seat): [str(c) for c in p.calls] for p in self.players},
        })
        self.state = FSMState.MATCH_END
        if self.hand_complete_fn:
            await self.hand_complete_fn({'type': 'draw_result', 'tenpai_seats': tenpai,
                                         'payments': {str(k): v for k, v in result.payments.items()}})

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _is_concealed(self, p: PlayerState) -> bool:
        return not any(
            c.call_type in (CallType.STRAIGHT, CallType.TRIPLET, CallType.QUAD)
            for c in p.calls
        )

    def _claim_win_flags(self, seat: int, from_seat: int) -> WinFlags:
        """Flags applicable to a discard win, including first/final turns."""
        first_discard = self._draw_count == 1 and from_seat == self.dealer
        return WinFlags(
            last_tile=(self.wall.remaining() == 0) if self.wall else False,
            robbing_quad=self._pending_robbing_quad,
            heavenly_wait=(first_discard and seat != self.dealer
                           and self._opening_wait.get(seat, False)),
        )

    def _can_declare_wait(self, p: PlayerState) -> bool:
        if not self._is_concealed(p):
            return False
        for tile in set(p.hand):
            hand = list(p.hand)
            hand.remove(tile)
            if waits(hand, p.calls):
                return True
        return False

    def _discard_keeps_wait(self, p: PlayerState, tile: Tile) -> bool:
        if not p.has_declared_wait or tile not in p.hand:
            return True
        hand = list(p.hand)
        hand.remove(tile)
        return set(waits(hand, p.calls)) == set(p.declared_waits)

    def _self_quad_keeps_wait(self, p: PlayerState, tile: Tile, is_added: bool) -> bool:
        hand = list(p.hand)
        calls = list(p.calls)
        if is_added:
            if tile not in hand:
                return False
            hand.remove(tile)
            for i, call in enumerate(calls):
                if call.call_type == CallType.TRIPLET and call.tiles[0] == tile:
                    calls[i] = Call(CallType.QUAD, [tile] * 4)
                    result = waits(hand, calls)
                    return set(result) == set(p.declared_waits) if p.has_declared_wait else bool(result)
            return False

        if hand.count(tile) < 4:
            return False
        for _ in range(4):
            hand.remove(tile)
        result = waits(hand, calls + [Call(CallType.CONCEALED_QUAD, [tile] * 4)])
        return set(result) == set(p.declared_waits) if p.has_declared_wait else bool(result)

    def _direct_quad_keeps_wait(self, p: PlayerState, tile: Tile) -> bool:
        hand = list(p.hand)
        if hand.count(tile) < 3:
            return False
        for _ in range(3):
            hand.remove(tile)
        result = waits(hand, p.calls + [Call(CallType.QUAD, [tile] * 4)])
        return set(result) == set(p.declared_waits) if p.has_declared_wait else bool(result)

    def _all_visible_tiles(self) -> list[Tile]:
        visible = []
        for p in self.players:
            visible.extend(p.all_visible_discards())
            for call in p.calls:
                if call.call_type != CallType.CONCEALED_QUAD:
                    visible.extend(call.tiles)
        return visible

    def _build_view(self, seat: int) -> dict:
        """Build the view dict that bots and the personal state use."""
        p = self.players[seat]
        others = []
        for s in range(self.num_players):
            if s == seat:
                continue
            op = self.players[s]
            others.append({
                'seat': s, 'name': op.name, 'is_bot': op.is_bot,
                'hand_count': len(op.hand),
                'calls': [str(c) for c in op.calls],
                'river': [tile_to_str(t) if not fd else None
                          for t, fd in zip(op.river, op.river_face_down)],
                'pass_count': op.pass_count,
                'straight_triplet_count': op.straight_triplet_count,
                'has_declared_wait': op.has_declared_wait,
            })
        return {
            'seat': seat,
            'hand': [tile_to_str(t) for t in p.hand],
            'calls': [str(c) for c in p.calls],
            'river': [tile_to_str(t) if not fd else None
                      for t, fd in zip(p.river, p.river_face_down)],
            'others': others,
            'wall_count': self.wall.remaining() if self.wall else 0,
            'current_seat': self.current_seat,
            'turn_id': self.turn_id,
            'turn_deadline_at_ms': int(self.turn_deadline_at * 1000) if self.turn_deadline_at else None,
            'window_id': self.window_id,
            'window_deadline_at_ms': int(self.window_deadline_at * 1000) if self.window_deadline_at else None,
        }

    def snapshot(self, seat: int) -> dict:
        """Complete reconnect view without revealing opponents' concealed hands."""
        view = self._build_view(seat)
        p = self.players[seat]
        if self.state == FSMState.PLAYER_TURN and seat == self.current_seat and p.hand:
            legal_options = self._compute_turn_options(p, p.hand[-1])
        elif self.state == FSMState.AWAIT_CLAIMS and seat != self._pending_from_seat:
            legal_options = self._claim_options.get(seat, ['skip'])
        else:
            legal_options = []
        players = []
        for op in self.players:
            players.append({
                'seat': op.seat,
                'name': op.name,
                'is_bot': op.is_bot,
                'score': op.score,
                'hand_count': len(op.hand),
                'calls': [str(c) for c in op.calls],
                'river': [tile_to_str(t) if not fd else None
                          for t, fd in zip(op.river, op.river_face_down)],
                'pass_count': op.pass_count,
                'straight_triplet_count': op.straight_triplet_count,
                'has_declared_wait': op.has_declared_wait,
            })
        return {
            'state': self.state.name,
            'dealer': self.dealer,
            'current_seat': self.current_seat,
            'wall': self.wall.snapshot() if self.wall else None,
            'players': players,
            'scores': {str(op.seat): op.score for op in self.players},
            'rivers': {str(op.seat): [tile_to_str(t) if not fd else None
                                      for t, fd in zip(op.river, op.river_face_down)]
                       for op in self.players},
            'calls': {str(op.seat): [str(c) for c in op.calls] for op in self.players},
            'called_river_tiles': {str(seat): indexes for seat, indexes in self._called_river_tiles.items()},
            'your_seat': seat,
            'your_hand': [tile_to_str(t) for t in p.hand],
            'your_calls': view['calls'],
            'your_river': view['river'],
            'pass_count': p.pass_count,
            'straight_triplet_count': p.straight_triplet_count,
            'has_declared_wait': p.has_declared_wait,
            'legal_options': legal_options,
            'drawn_tile': tile_to_str(p.hand[-1]) if self.state == FSMState.PLAYER_TURN and seat == self.current_seat and p.hand else None,
            'claim_tile': tile_to_str(self._pending_discard) if self._pending_discard else None,
            'claim_from_seat': self._pending_from_seat if self.state == FSMState.AWAIT_CLAIMS else None,
            'turn_id': self.turn_id,
            'turn_deadline_at_ms': view['turn_deadline_at_ms'],
            'window_id': self.window_id,
            'window_deadline_at_ms': view['window_deadline_at_ms'],
            'waits': [tile_to_str(t) for t in p.declared_waits],
        }

    async def _debug_log(self, message: str) -> None:
        if self.players and not self.players[0].is_bot:
            await self.send(0, {'type': 'debug_log', 'message': message})

    def _sanitize_claim(self, seat: int, claim_action: dict) -> dict:
        claim = claim_action.get('claim', 'skip')
        if claim == 'skip':
            return {'claim': 'skip'}

        tile = self._pending_discard
        if tile is None or seat == self._pending_from_seat:
            return {'claim': 'skip'}

        p = self.players[seat]
        flags = self._claim_win_flags(seat, self._pending_from_seat)
        claims = legal_claims(
            hand=p.hand,
            calls=p.calls,
            discard=tile,
            from_seat=self._pending_from_seat,
            my_seat=seat,
            num_players=self.num_players,
            pass_count=p.pass_count,
            straight_triplet_count=p.straight_triplet_count,
            win_flags=flags,
            face_down=False,
            has_declared_wait=p.has_declared_wait,
        )

        if claim == 'win' and claims['win']:
            return claim_action
        normalized = {**claim_action, 'claim': claim}

        if claim == TRIPLET_CALL and claims['triplet_call']:
            return normalized
        if claim == DIRECT_QUAD_CALL and claims['direct_quad_call']:
            return normalized
        if claim == STRAIGHT_CALL and claims['straight_call']:
            chosen = claim_action.get('tiles') or []
            if not chosen:
                return normalized
            chosen_key = sorted(chosen)
            if any(sorted(tile_to_str(t) for t in c.tiles) == chosen_key for c in claims['straight_call']):
                return normalized

        return {'claim': 'skip'}

    async def _continue_after_no_claim(self) -> None:
        quad_seat = self._no_claim_quad_draw_seat
        next_seat = self._no_claim_next_seat
        from_seat = self._pending_from_seat
        self._no_claim_next_seat = None
        self._no_claim_quad_draw_seat = None

        if quad_seat is not None:
            await self._begin_quad_draw(quad_seat)
            return

        self.current_seat = next_seat if next_seat is not None else (from_seat + 1) % self.num_players
        await self._begin_player_turn(self.current_seat)
