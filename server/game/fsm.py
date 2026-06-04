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
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Callable, Awaitable

from game.tiles import Tile, tile_to_str
from game.wall import Wall
from game.player_state import PlayerState
from game.legal import (
    can_chow, can_pong, can_open_kong, can_added_kong,
    can_concealed_kong, can_win_on_discard, can_win_self_drawn, legal_claims,
)
from game.redraw import is_redraw_eligible
from game.settle import settle_wins, settle_exhaustive_draw
from scoring.parsing import Call, CallType
from scoring.api import WinFlags, waits


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
    call_seat: int | None # seat making chow/pong/kong (None if no call)
    call_action: dict | None


def resolve_claims(
    discard: Tile,
    from_seat: int,
    claims: dict[int, dict],   # seat -> {'claim': str, ...}
    num_players: int = 4,
) -> ClaimResolution:
    """
    Resolve competing claims according to IMR priority:
      win > pong/kong > chow
    Ties in same priority → smallest circular distance from from_seat (next seat wins).
    Multi-win (一炮多響): ALL win claims succeed simultaneously.
    """
    winners = [s for s, c in claims.items() if c.get('claim') == 'win']
    if winners:
        return ClaimResolution(winners=winners, call_seat=None, call_action=None)

    # Kong > pong > chow
    def priority(claim: str) -> int:
        return {'kong': 3, 'pong': 2, 'chow': 1}.get(claim, 0)

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
    ):
        self.players = players
        self.num_players = len(players)
        self.send = send_fn or (lambda seat, msg: None)
        self.broadcast = broadcast_fn or (lambda msg: None)
        self._seed = seed

        self.state = FSMState.WAITING
        self.wall: Wall | None = None
        self.current_seat: int = 0
        self.dealer: int = 0

        # Pending discard info during AWAIT_CLAIMS
        self._pending_discard: Tile | None = None
        self._pending_discard_face_down: bool = False
        self._pending_from_seat: int = 0
        self._claims: dict[int, dict] = {}     # seat -> claim action
        self._claims_received: int = 0

        # Kong supplement tracking
        self._kong_supplement_seat: int = 0

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
            self._claims[seat] = claim_action
            self._claims_received += 1
            if self._claims_received == self.num_players - 1:
                await self._resolve_claims_phase()

    # ------------------------------------------------------------------
    # Deal
    # ------------------------------------------------------------------

    async def _deal(self) -> None:
        self.state = FSMState.DEALING
        self.wall = Wall(seed=self._seed)

        for p in self.players:
            p.reset_for_new_hand()

        hands = self.wall.deal(self.num_players)
        for i, p in enumerate(self.players):
            p.hand = list(hands[i])

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
        })

        # Bots act immediately
        if p.is_bot:
            from bots.base import Bot
            bot: Bot = p._bot  # type: ignore
            action = bot.decide_turn(self._build_view(seat))
            await self.handle_player_action(seat, action)

    def _compute_turn_options(self, p: PlayerState, drawn_tile: Tile) -> list[str]:
        options: list[str] = ['discard']

        # Tsumo win
        flags = WinFlags(self_drawn=True, last_tile=(self.wall.remaining() == 0))
        if can_win_self_drawn(p.hand[:-1], p.calls, drawn_tile, flags):
            options.append('tsumo')

        # Concealed kong
        if can_concealed_kong(p.hand[:-1], drawn_tile):
            options.append('concealed_kong')

        # Added kong
        if can_added_kong(p.hand[:-1], p.calls, drawn_tile):
            options.append('added_kong')

        # Redraw
        all_vis = self._all_visible_tiles()
        if is_redraw_eligible(
            drawn_tile,
            own_river=p.all_visible_discards(),
            own_open_calls=[c.tiles for c in p.calls],
            all_visible_tiles=all_vis,
        ):
            options.append('redraw')

        # Declare ready (报听) — only concealed hands
        if not p.is_riichi and self._is_concealed(p) and not p.is_riichi:
            if waits(p.hand, p.calls):
                options.append('declare_ready')

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
            await self._do_discard(seat, tile, face_down)

        elif act == 'tsumo':
            tile = p.hand[-1]  # last drawn
            flags = WinFlags(self_drawn=True, last_tile=(self.wall.remaining() == 0))
            if not can_win_self_drawn(p.hand[:-1], p.calls, tile, flags):
                await self.send(seat, {'type': 'error', 'message': 'Invalid tsumo'})
                return
            await self._do_tsumo(seat, tile)

        elif act in ('concealed_kong', 'added_kong'):
            tile_str = action.get('tile')
            tile = next((t for t in p.hand if tile_to_str(t) == tile_str), None)
            if tile is None:
                await self.send(seat, {'type': 'error', 'message': f'Tile {tile_str} not in hand'})
                return
            await self._do_self_kong(seat, tile, is_added=(act == 'added_kong'))

        elif act == 'redraw':
            tile = p.hand[-1]
            all_vis = self._all_visible_tiles()
            if not is_redraw_eligible(tile, p.all_visible_discards(),
                                      [c.tiles for c in p.calls], all_vis):
                await self.send(seat, {'type': 'error', 'message': 'Redraw not eligible'})
                return
            await self._do_redraw(seat, tile)

        elif act == 'declare_ready':
            if not self._is_concealed(p):
                await self.send(seat, {'type': 'error', 'message': 'Cannot declare ready with open calls'})
                return
            p.is_riichi = True
            await self.broadcast({'type': 'ready_declared', 'seat': seat})
            # Fall through to discard (player still needs to discard after declaring ready)
            # The client will prompt for a discard next

        else:
            await self.send(seat, {'type': 'error', 'message': f'Unknown action: {act}'})

    # ------------------------------------------------------------------
    # Discard
    # ------------------------------------------------------------------

    async def _do_discard(self, seat: int, tile: Tile, face_down: bool) -> None:
        p = self.players[seat]

        # Validate rang_guo legality
        if face_down:
            if p.pass_count >= 2:
                await self.send(seat, {'type': 'error', 'message': 'Already rang_guo twice'})
                return

        p.discard(tile, face_down)

        await self.broadcast({
            'type': 'discarded',
            'seat': seat,
            'tile': tile_to_str(tile) if not face_down else None,
            'face_down': face_down,
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

    async def _begin_await_claims(self, from_seat: int, tile: Tile) -> None:
        self.state = FSMState.AWAIT_CLAIMS
        self._pending_discard = tile
        self._pending_discard_face_down = False
        self._pending_from_seat = from_seat
        self._claims = {}
        self._claims_received = 0

        # Notify each other player of their options
        bot_claims: list[tuple[int, dict]] = []

        for s in range(self.num_players):
            if s == from_seat:
                continue
            p = self.players[s]
            flags = WinFlags(last_tile=(self.wall.remaining() == 0))
            claims = legal_claims(
                hand=p.hand,
                calls=p.calls,
                discard=tile,
                from_seat=from_seat,
                my_seat=s,
                num_players=self.num_players,
                pass_count=p.pass_count,
                chow_pong_count=p.chow_pong_count,
                win_flags=flags,
                face_down=False,
            )

            # Build option list for the client
            options = []
            if claims['win']:
                options.append('win')
            if claims['pong']:
                options.append('pong')
            if claims['kong']:
                options.append('kong')
            for chow_call in claims['chow']:
                options.append('chow')
                break  # client picks which tiles; signal availability
            options.append('skip')

            await self.send(s, {
                'type': 'claim_window',
                'tile': tile_to_str(tile),
                'from_seat': from_seat,
                'your_options': options,
                'deadline_ms': 5000,
            })

            if p.is_bot:
                from bots.base import Bot
                bot: Bot = p._bot  # type: ignore
                bot_action = bot.decide_claim(self._build_view(s), options)
                bot_claims.append((s, bot_action))

        # Bots respond immediately
        for s, action in bot_claims:
            await self.handle_claim(s, action)

        # If all non-discarder seats are bots, claims may already be resolved
        # (handled inside handle_claim). If there's a human player still
        # waiting, we wait for their claim or the timeout.

    async def _resolve_claims_phase(self) -> None:
        from_seat = self._pending_from_seat
        tile = self._pending_discard
        resolution = resolve_claims(tile, from_seat, self._claims, self.num_players)

        if resolution.winners:
            await self._do_ron(resolution.winners, tile, from_seat)
            return

        if resolution.call_seat is not None:
            await self._do_call(resolution.call_seat, resolution.call_action, tile, from_seat)
            return

        # No claims: next player draws
        self.current_seat = (from_seat + 1) % self.num_players
        await self._begin_player_turn(self.current_seat)

    # ------------------------------------------------------------------
    # Win
    # ------------------------------------------------------------------

    async def _do_tsumo(self, seat: int, tile: Tile) -> None:
        p = self.players[seat]
        flags = WinFlags(
            self_drawn=True,
            last_tile=(self.wall.remaining() == 0),
            riichi=p.is_riichi,
        )
        result = settle_wins(
            winners_data=[(seat, tile, 'tsumo', -1)],
            player_hands={s: self.players[s].hand[:-1] for s in range(self.num_players)},
            player_calls={s: self.players[s].calls for s in range(self.num_players)},
            player_pass_count={s: self.players[s].pass_count for s in range(self.num_players)},
            player_riichi={s: self.players[s].is_riichi for s in range(self.num_players)},
            flags_extra={seat: flags},
        )
        if not result.winners:
            await self.send(seat, {'type': 'error', 'message': 'Threshold not met'})
            return
        await self._end_hand(result)

    async def _do_ron(self, winner_seats: list[int], tile: Tile, from_seat: int) -> None:
        winners_data = []
        for ws in winner_seats:
            p = self.players[ws]
            flags = WinFlags(
                self_drawn=False,
                last_tile=(self.wall.remaining() == 0),
                riichi=p.is_riichi,
                robbing_kong=False,  # standard ron
            )
            winners_data.append((ws, tile, 'ron', from_seat))

        all_flags = {}
        for ws in winner_seats:
            p = self.players[ws]
            all_flags[ws] = WinFlags(self_drawn=False, riichi=p.is_riichi)

        result = settle_wins(
            winners_data=winners_data,
            player_hands={s: self.players[s].hand for s in range(self.num_players)},
            player_calls={s: self.players[s].calls for s in range(self.num_players)},
            player_pass_count={s: self.players[s].pass_count for s in range(self.num_players)},
            player_riichi={s: self.players[s].is_riichi for s in range(self.num_players)},
            flags_extra=all_flags,
        )
        if not result.winners:
            # All claims failed threshold; no claim succeeds
            self.current_seat = (from_seat + 1) % self.num_players
            await self._begin_player_turn(self.current_seat)
            return
        await self._end_hand(result)

    # ------------------------------------------------------------------
    # Calls (pong/chow/kong)
    # ------------------------------------------------------------------

    async def _do_call(self, seat: int, action: dict, tile: Tile, from_seat: int) -> None:
        p = self.players[seat]
        claim = action.get('claim')

        if claim == 'pong':
            p.hand.remove(tile)
            p.hand.remove(tile)
            call = Call(CallType.TRIPLET, [tile, tile, tile])
            p.add_call(call, is_pong_or_chow=True)
            await self.broadcast({
                'type': 'call_made', 'seat': seat, 'call': 'pong',
                'tiles': [tile_to_str(tile)] * 3, 'from_seat': from_seat,
            })

        elif claim == 'kong':
            for _ in range(3):
                p.hand.remove(tile)
            call = Call(CallType.QUAD, [tile] * 4)
            p.add_call(call, is_pong_or_chow=False)  # kong doesn't count
            await self.broadcast({
                'type': 'call_made', 'seat': seat, 'call': 'kong',
                'tiles': [tile_to_str(tile)] * 4, 'from_seat': from_seat,
            })
            await self._begin_kong_draw(seat)
            return

        elif claim == 'chow':
            # Find the specific chow call
            chosen_tiles = action.get('tiles', [])
            chow_hand_tiles = [t for t in p.hand if tile_to_str(t) in chosen_tiles]
            if len(chow_hand_tiles) < 2:
                # Fallback: pick first valid chow
                options = can_chow(p.hand, tile, p.pass_count, p.chow_pong_count)
                if not options:
                    await self.send(seat, {'type': 'error', 'message': 'Invalid chow'})
                    return
                chow_call = options[0]
                chow_hand_tiles = [t for t in chow_call.tiles if t != tile]
            for t in chow_hand_tiles[:2]:
                p.hand.remove(t)
            chow_tiles_full = sorted([tile] + chow_hand_tiles[:2])
            call = Call(CallType.STRAIGHT, chow_tiles_full)
            p.add_call(call, is_pong_or_chow=True)
            await self.broadcast({
                'type': 'call_made', 'seat': seat, 'call': 'chow',
                'tiles': [tile_to_str(t) for t in chow_tiles_full], 'from_seat': from_seat,
            })

        # After pong/chow: player must discard
        self.current_seat = seat
        self.state = FSMState.PLAYER_TURN
        options = ['discard']

        await self.send(seat, {
            'type': 'your_turn',
            'drawn': None,
            'options': options,
            'redraw_eligible': False,
        })

        if p.is_bot:
            from bots.base import Bot
            bot: Bot = p._bot  # type: ignore
            discard_action = bot.decide_turn(self._build_view(seat))
            await self.handle_player_action(seat, discard_action)

    # ------------------------------------------------------------------
    # Self-kong
    # ------------------------------------------------------------------

    async def _do_self_kong(self, seat: int, tile: Tile, is_added: bool) -> None:
        p = self.players[seat]

        if is_added:
            # Remove the added tile from hand, upgrade triplet call to quad
            p.hand.remove(tile)
            for i, call in enumerate(p.calls):
                if call.call_type == CallType.TRIPLET and call.tiles[0] == tile:
                    p.calls[i] = Call(CallType.QUAD, [tile] * 4)
                    break
        else:
            # Concealed kong
            for _ in range(4):
                p.hand.remove(tile)
            p.calls.append(Call(CallType.CONCEALED_QUAD, [tile] * 4))

        await self.broadcast({
            'type': 'call_made', 'seat': seat,
            'call': 'added_kong' if is_added else 'concealed_kong',
            'tiles': [tile_to_str(tile)] * 4, 'from_seat': seat,
        })

        # For added kong, other players may rob the kong (搶槓)
        if is_added:
            await self._begin_kong_rob_window(seat, tile)
        else:
            await self._begin_kong_draw(seat)

    async def _begin_kong_rob_window(self, kong_seat: int, tile: Tile) -> None:
        """Allow others to rob the added kong (搶槓 win)."""
        self.state = FSMState.AWAIT_CLAIMS
        self._pending_discard = tile
        self._pending_from_seat = kong_seat
        self._claims = {}
        self._claims_received = 0

        bot_claims = []
        for s in range(self.num_players):
            if s == kong_seat:
                continue
            p = self.players[s]
            flags = WinFlags(robbing_kong=True)
            can_win = can_win_on_discard(p.hand, p.calls, tile, flags)
            options = ['win'] if can_win else ['skip']

            await self.send(s, {
                'type': 'claim_window',
                'tile': tile_to_str(tile),
                'from_seat': kong_seat,
                'your_options': options,
                'deadline_ms': 3000,
            })

            if p.is_bot:
                from bots.base import Bot
                bot: Bot = p._bot  # type: ignore
                bot_claims.append((s, bot.decide_claim(self._build_view(s), options)))

        for s, action in bot_claims:
            await self.handle_claim(s, action)

        # If nobody robs: proceed to kong draw
        # (handled in _resolve_claims_phase if all skip or via timeout)

    async def _begin_kong_draw(self, seat: int) -> None:
        """Draw supplement tile from dead wall after kong."""
        self.state = FSMState.KONG_DRAW
        self._kong_supplement_seat = seat
        tile = self.wall.draw_supplement()
        if tile is None:
            await self._exhaustive_draw()
            return

        p = self.players[seat]
        p.draw(tile)

        await self.broadcast({
            'type': 'tile_drawn', 'seat': seat, 'wall_count': self.wall.remaining(),
        })

        # Check win after kong (嶺上開花)
        flags = WinFlags(self_drawn=True, after_kong=True, last_tile=(self.wall.remaining() == 0))
        options = ['discard']
        if can_win_self_drawn(p.hand[:-1], p.calls, tile, flags):
            options.append('tsumo')

        self.state = FSMState.PLAYER_TURN
        self.current_seat = seat

        await self.send(seat, {
            'type': 'your_turn',
            'drawn': tile_to_str(tile),
            'options': options,
            'redraw_eligible': False,
        })

        if p.is_bot:
            from bots.base import Bot
            bot: Bot = p._bot  # type: ignore
            await self.handle_player_action(seat, bot.decide_turn(self._build_view(seat)))

    # ------------------------------------------------------------------
    # Redraw
    # ------------------------------------------------------------------

    async def _do_redraw(self, seat: int, tile: Tile) -> None:
        p = self.players[seat]
        p.hand.remove(tile)
        p.river.append(tile)
        p.river_face_down.append(False)

        await self.broadcast({'type': 'redraw', 'seat': seat})

        # Draw a new tile (normal draw, not supplement)
        new_tile = self.wall.draw()
        if new_tile is None:
            await self._exhaustive_draw()
            return
        p.draw(new_tile)

        await self.broadcast({
            'type': 'tile_drawn', 'seat': seat, 'wall_count': self.wall.remaining(),
        })

        options = self._compute_turn_options(p, new_tile)
        await self.send(seat, {
            'type': 'your_turn',
            'drawn': tile_to_str(new_tile),
            'options': options,
            'redraw_eligible': 'redraw' in options,
        })

        if p.is_bot:
            from bots.base import Bot
            bot: Bot = p._bot  # type: ignore
            await self.handle_player_action(seat, bot.decide_turn(self._build_view(seat)))

    # ------------------------------------------------------------------
    # End states
    # ------------------------------------------------------------------

    async def _end_hand(self, result) -> None:
        self.state = FSMState.HAND_END

        winners_payload = []
        for w in result.winners:
            fans_payload = [
                {'id': af.fan.id, 'name': af.fan.name_e, 'value': af.score}
                for af in w.scoring.achieved_fans
            ]
            winners_payload.append({
                'seat': w.seat,
                'win_type': w.win_type,
                'from_seat': w.from_seat,
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
        })

        self.state = FSMState.MATCH_END

    async def _exhaustive_draw(self) -> None:
        self.state = FSMState.EXHAUSTIVE_DRAW

        result = settle_exhaustive_draw(
            player_pass_count={s: self.players[s].pass_count for s in range(self.num_players)},
            player_chow_pong_count={s: self.players[s].chow_pong_count for s in range(self.num_players)},
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
        })
        self.state = FSMState.MATCH_END

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _is_concealed(self, p: PlayerState) -> bool:
        return not any(
            c.call_type in (CallType.STRAIGHT, CallType.TRIPLET, CallType.QUAD)
            for c in p.calls
        )

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
                'seat': s,
                'hand_count': len(op.hand),
                'calls': [str(c) for c in op.calls],
                'river': [tile_to_str(t) if not fd else None
                          for t, fd in zip(op.river, op.river_face_down)],
                'pass_count': op.pass_count,
                'chow_pong_count': op.chow_pong_count,
                'is_riichi': op.is_riichi,
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
        }
