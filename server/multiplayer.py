"""In-memory lobby/match coordination for the single-server deployment."""
from __future__ import annotations

import asyncio
import secrets
import time
import uuid
from dataclasses import dataclass, field
from typing import Awaitable, Callable

from bots.auto_call_bot import AutoCallBot
from bots.efficiency_bot import EfficiencyBot
from db import save_match
from game.fsm import GameState, FSMState
from game.player_state import PlayerState
from game.tiles import tile_to_str

SendUser = Callable[[int, dict], Awaitable[None]]
BroadcastUsers = Callable[[list[int], dict], Awaitable[None]]


@dataclass
class Seat:
    user_id: int | None = None
    username: str = ''
    bot: str | None = None
    connected: bool = False

    @property
    def is_bot(self) -> bool:
        return self.bot is not None

    def payload(self, seat: int) -> dict:
        return {'seat': seat, 'user_id': self.user_id, 'name': self.username or self.bot or 'Open',
                'is_bot': self.is_bot, 'bot': self.bot, 'connected': self.connected or self.is_bot}


@dataclass
class Room:
    id: str
    owner_id: int
    owner_name: str
    length: int = 1
    visibility: str = 'public'
    code: str | None = None
    seats: list[Seat] = field(default_factory=lambda: [Seat() for _ in range(4)])

    def __post_init__(self) -> None:
        self.seats[0] = Seat(self.owner_id, self.owner_name)

    def users(self) -> list[int]:
        return [s.user_id for s in self.seats if s.user_id is not None]

    def view(self) -> dict:
        return {'id': self.id, 'owner_id': self.owner_id, 'owner_name': self.owner_name,
                'length': self.length, 'visibility': self.visibility, 'code': self.code,
                'seats': [s.payload(i) for i, s in enumerate(self.seats)]}


class Match:
    def __init__(self, match_id: str, mode: str, length: int, seats: list[Seat], send_user: SendUser,
                 broadcast_users: BroadcastUsers, finished_fn: Callable[[str, list[int]], Awaitable[None]] | None = None):
        self.id = match_id
        self.mode = mode
        self.length = length
        self.seats = seats
        self.send_user = send_user
        self.broadcast_users = broadcast_users
        self.finished_fn = finished_fn
        self.hand_no = 0
        self.seed = secrets.randbits(64)
        self.replay: list[dict] = []
        self.finished = False
        self.offline_since: dict[int, float] = {}
        self.offline_used: dict[int, float] = {}
        self.takeover: set[int] = set()
        self._offline_tasks: dict[int, asyncio.Task] = {}
        self._lock = asyncio.Lock()
        players: list[PlayerState] = []
        for seat, slot in enumerate(seats):
            p = PlayerState(seat=seat, name=slot.username or slot.bot or f'Seat {seat}', is_bot=slot.is_bot)
            if slot.bot == 'auto_call':
                p.bot = AutoCallBot()
            elif slot.bot == 'discard_only':
                from bots.discard_only_bot import DiscardOnlyBot
                p.bot = DiscardOnlyBot()
            else:
                p.bot = EfficiencyBot()
            players.append(p)
        self.game = GameState(players, self._send_seat, self._broadcast, seed=self.seed,
                              hand_complete_fn=self._hand_complete, timeout_fn=self._game_timeout)

    def user_ids(self) -> list[int]:
        return [s.user_id for s in self.seats if s.user_id is not None]

    async def _send_seat(self, seat: int, msg: dict) -> None:
        self.replay.append({'scope': 'seat', 'seat': seat, 'message': msg})
        user_id = self.seats[seat].user_id
        if user_id is not None:
            await self.send_user(user_id, msg)
        if seat in self.offline_since and msg.get('type') == 'your_turn' and seat not in self._offline_tasks:
            await self._broadcast({'type': 'match_paused', 'seat': seat,
                                   'seconds_left': max(0, 60 - self.offline_used.get(seat, 0))})
            self._offline_tasks[seat] = asyncio.create_task(self._takeover_after_timeout(seat))
        if seat in self.offline_since and msg.get('type') == 'claim_window':
            claim = 'win' if 'win' in msg.get('your_options', []) else 'skip'
            asyncio.create_task(self.game.handle_claim(seat, {'claim': claim}))

    async def _broadcast(self, msg: dict) -> None:
        self.replay.append({'scope': 'all', 'message': msg})
        await self.broadcast_users(self.user_ids(), msg)

    async def start(self) -> None:
        async with self._lock:
            self.hand_no = 1
            self.replay.append({'type': 'wall_seed', 'hand': self.hand_no, 'seed': self.seed})
            await self._broadcast({'type': 'match_started', 'match_id': self.id, 'length': self.length,
                                   'players': [slot.payload(i) for i, slot in enumerate(self.seats)]})
            await self.game.start()

    async def _game_timeout(self, kind: str, serial: int) -> None:
        async with self._lock:
            if not self.finished:
                await self.game.timeout(kind, serial)

    async def _hand_complete(self, result: dict) -> None:
        if self.hand_no < self.length:
            self.hand_no += 1
            self.seed = secrets.randbits(64)
            self.game._seed = self.seed
            self.replay.append({'type': 'wall_seed', 'hand': self.hand_no, 'seed': self.seed})
            self.game.dealer = (self.game.dealer + 1) % 4
            self.game.state = FSMState.WAITING
            await self._broadcast({'type': 'next_hand', 'hand': self.hand_no, 'total_hands': self.length,
                                   'dealer': self.game.dealer})
            await self.game._deal()
            return

        self.finished = True
        ordered = sorted(enumerate(self.game.players), key=lambda pair: pair[1].score, reverse=True)
        ranks: dict[int, int] = {}
        for index, (seat, player) in enumerate(ordered):
            ranks[seat] = 1 + sum(other.score > player.score for other in self.game.players)
        results = [{'seat': seat, 'name': self.game.players[seat].name, 'score': self.game.players[seat].score,
                    'rank': ranks[seat]} for seat in range(4)]
        players = [{'user_id': slot.user_id, 'seat': seat, 'score': self.game.players[seat].score,
                    'rank': ranks[seat]} for seat, slot in enumerate(self.seats) if slot.user_id is not None]
        save_match(self.id, self.mode, self.length, self.replay, results, players)
        await self._broadcast({'type': 'match_finished', 'match_id': self.id, 'results': results,
                               'formal': self.mode == 'matchmaking'})
        if self.finished_fn:
            await self.finished_fn(self.id, self.user_ids())

    async def action(self, user_id: int, action: dict) -> None:
        seat = next((i for i, slot in enumerate(self.seats) if slot.user_id == user_id), None)
        if seat is None:
            return
        async with self._lock:
            if action.get('turn_id') != self.game.turn_id:
                await self.send_user(user_id, {'type': 'error', 'message': 'Expired turn'})
                return
            if self.game.turn_deadline_at is not None and time.time() >= self.game.turn_deadline_at:
                await self.send_user(user_id, {'type': 'error', 'message': 'Expired turn'})
                return
            await self.game.handle_player_action(seat, action)

    async def claim(self, user_id: int, action: dict) -> None:
        seat = next((i for i, slot in enumerate(self.seats) if slot.user_id == user_id), None)
        if seat is not None:
            async with self._lock:
                if action.get('window_id') != self.game.window_id:
                    await self.send_user(user_id, {'type': 'error', 'message': 'Expired claim window'})
                    return
                if self.game.window_deadline_at is not None and time.time() >= self.game.window_deadline_at:
                    await self.send_user(user_id, {'type': 'error', 'message': 'Expired claim window'})
                    return
                await self.game.handle_claim(seat, action)

    async def disconnect_user(self, user_id: int) -> None:
        async with self._lock:
            seat = next((i for i, slot in enumerate(self.seats) if slot.user_id == user_id), None)
            if seat is None or self.finished:
                return
            self.seats[seat].connected = False
            self.offline_since[seat] = asyncio.get_running_loop().time()
            if seat not in self._offline_tasks:
                await self._broadcast({'type': 'match_paused', 'seat': seat,
                                       'seconds_left': max(0, 60 - self.offline_used.get(seat, 0))})
                self._offline_tasks[seat] = asyncio.create_task(self._takeover_after_timeout(seat))

    async def reconnect_user(self, user_id: int) -> None:
        async with self._lock:
            await self._reconnect_user_locked(user_id)

    async def _reconnect_user_locked(self, user_id: int) -> None:
        seat = next((i for i, slot in enumerate(self.seats) if slot.user_id == user_id), None)
        if seat is None:
            return
        self.seats[seat].connected = True
        task = self._offline_tasks.pop(seat, None)
        if task:
            task.cancel()
        if seat in self.offline_since:
            elapsed = asyncio.get_running_loop().time() - self.offline_since.pop(seat)
            if self.game.current_seat == seat:
                self.offline_used[seat] = self.offline_used.get(seat, 0) + elapsed
            await self._broadcast({'type': 'match_resumed', 'seat': seat})
        self.takeover.discard(seat)
        self.game.players[seat].is_bot = self.seats[seat].is_bot

    async def _takeover_after_timeout(self, seat: int) -> None:
        remaining = max(0, 60 - self.offline_used.get(seat, 0))
        try:
            await asyncio.sleep(remaining)
        except asyncio.CancelledError:
            return
        async with self._lock:
            if seat not in self.offline_since or self.finished:
                return
            self.takeover.add(seat)
            self.offline_used[seat] = 60
            self.offline_since.pop(seat, None)
            self.game.players[seat].is_bot = True
            await self._broadcast({'type': 'player_takeover', 'seat': seat})
            if self.game.current_seat == seat and self.game.state == FSMState.PLAYER_TURN:
                p = self.game.players[seat]
                if p.hand:
                    await self.game.handle_player_action(seat, {
                        'action': 'discard', 'tile': tile_to_str(p.hand[-1]),
                    })

    async def resume_state(self, user_id: int) -> None:
        async with self._lock:
            seat = next((i for i, slot in enumerate(self.seats) if slot.user_id == user_id), None)
            if seat is None:
                return
            await self._reconnect_user_locked(user_id)
            snapshot = self.game.snapshot(seat)
            snapshot.update({
                'match_id': self.id,
                'hand': self.hand_no,
                'total_hands': self.length,
                'mode': self.mode,
                'takeover_seats': sorted(self.takeover),
                'players': [{**slot.payload(i), **snapshot['players'][i],
                             'is_bot': slot.is_bot or self.game.players[i].is_bot,
                             'connected': slot.connected or slot.is_bot}
                            for i, slot in enumerate(self.seats)],
            })
            await self.send_user(user_id, {'type': 'match_snapshot', **snapshot})
            await self.send_user(user_id, {'type': 'match_resume', 'match_id': self.id,
                                           'hand': self.hand_no, 'snapshot': snapshot})


class Lobby:
    def __init__(self, send_user: SendUser, broadcast_users: BroadcastUsers):
        self.send_user = send_user
        self.broadcast_users = broadcast_users
        self.rooms: dict[str, Room] = {}
        self.matches: dict[str, Match] = {}
        self.queues: dict[int, list[tuple[int, str]]] = {1: [], 4: [], 8: []}
        self.user_room: dict[int, str] = {}
        self.user_match: dict[int, str] = {}
        self.connected_users: set[int] = set()

    def snapshot(self) -> dict:
        return {'type': 'lobby_state', 'rooms': [r.view() for r in self.rooms.values() if r.visibility == 'public']}

    async def notify_lobby(self) -> None:
        # The application broadcasts this to currently connected users.
        await self.broadcast_users([], self.snapshot())

    async def notify_room(self, room: Room) -> None:
        await self.broadcast_users(room.users(), {'type': 'room_state', 'room': room.view()})

    def room_for(self, user_id: int) -> Room | None:
        return self.rooms.get(self.user_room.get(user_id, ''))

    async def connect_user(self, user_id: int) -> None:
        self.connected_users.add(user_id)
        room = self.room_for(user_id)
        if room is None:
            return
        for seat in room.seats:
            if seat.user_id == user_id:
                seat.connected = True
                break
        await self.notify_room(room)

    async def disconnect_user(self, user_id: int) -> None:
        self.connected_users.discard(user_id)
        queue_changed = False
        for length in self.queues:
            filtered = [(uid, name) for uid, name in self.queues[length] if uid != user_id]
            queue_changed = queue_changed or len(filtered) != len(self.queues[length])
            self.queues[length] = filtered
        room = self.room_for(user_id)
        if room is None:
            if queue_changed:
                await self.notify_lobby()
            return
        for seat in room.seats:
            if seat.user_id == user_id:
                seat.connected = False
                break
        await self.notify_room(room)

    async def create_room(self, user_id: int, username: str, length: int, visibility: str) -> Room:
        if user_id in self.user_room or user_id in self.user_match:
            raise ValueError('Already in a room')
        if length not in (1, 4, 8) or visibility not in ('public', 'private'):
            raise ValueError('Invalid room settings')
        room_id = uuid.uuid4().hex[:8]
        code = secrets.token_urlsafe(6) if visibility == 'private' else None
        room = Room(room_id, user_id, username, length, visibility, code)
        room.seats[0].connected = user_id in self.connected_users
        self.rooms[room_id] = room
        self.user_room[user_id] = room_id
        await self.notify_lobby()
        return room

    async def join_room(self, user_id: int, username: str, room_id: str | None = None, code: str | None = None) -> Room:
        if user_id in self.user_room or user_id in self.user_match:
            raise ValueError('Already in a room')
        room = next((r for r in self.rooms.values() if (room_id and r.id == room_id) or (code and r.code == code)), None)
        if room is None:
            raise ValueError('Room not found')
        seat = next((s for s in room.seats if s.user_id is None and not s.is_bot), None)
        if seat is None:
            raise ValueError('Room is full')
        seat.user_id, seat.username = user_id, username
        seat.connected = user_id in self.connected_users
        self.user_room[user_id] = room.id
        await self.notify_lobby()
        return room

    async def set_config(self, user_id: int, length: int, bots: dict[str, str | None]) -> Room:
        room = self._owned_room(user_id)
        if room.length not in (1, 4, 8) or length not in (1, 4, 8):
            raise ValueError('Invalid length')
        room.length = length
        for key, bot in bots.items():
            seat = int(key)
            if seat <= 0 or seat >= 4 or bot not in (None, 'efficiency', 'auto_call', 'discard_only'):
                raise ValueError('Invalid bot setting')
            slot = room.seats[seat]
            if slot.user_id is not None:
                raise ValueError('Seat is occupied')
            slot.bot = bot
            slot.username = ''
            slot.connected = False
        await self.notify_lobby()
        return room

    async def leave_room(self, user_id: int) -> None:
        room_id = self.user_room.pop(user_id, None)
        room = self.rooms.get(room_id or '')
        if room is None:
            return
        if room.owner_id == user_id:
            user_ids = room.users()
            for uid in user_ids:
                self.user_room.pop(uid, None)
            del self.rooms[room.id]
            for uid in user_ids:
                await self.send_user(uid, {'type': 'room_closed', 'room_id': room.id, 'reason': 'owner_left'})
        else:
            for slot in room.seats:
                if slot.user_id == user_id:
                    slot.user_id, slot.username, slot.connected = None, '', False
                    break
            await self.notify_room(room)
            await self.send_user(user_id, {'type': 'room_left', 'room_id': room.id})
        await self.notify_lobby()

    async def leave_queue(self, user_id: int, length: int) -> None:
        self.queues.get(length, [])[:] = [(uid, name) for uid, name in self.queues.get(length, []) if uid != user_id]
        await self.send_user(user_id, {'type': 'queue_left', 'length': length})

    async def start_room(self, user_id: int) -> Match:
        room = self._owned_room(user_id)
        if any(slot.user_id is None and not slot.is_bot for slot in room.seats):
            raise ValueError('Fill every seat before starting')
        match = self._make_match('room', room.length, room.seats)
        del self.rooms[room.id]
        for uid in room.users():
            self.user_room.pop(uid, None)
            self.user_match[uid] = match.id
        self.matches[match.id] = match
        await self.notify_lobby()
        await match.start()
        return match

    async def queue(self, user_id: int, username: str, length: int) -> Match | None:
        if length not in self.queues or user_id in self.user_room or user_id in self.user_match:
            raise ValueError('Invalid queue request')
        if not any(uid == user_id for uid, _ in self.queues[length]):
            self.queues[length].append((user_id, username))
        if len(self.queues[length]) < 4:
            await self.send_user(user_id, {'type': 'queue_joined', 'length': length, 'size': len(self.queues[length])})
            return None
        users = self.queues[length][:4]
        del self.queues[length][:4]
        seats = [Seat(uid, name) for uid, name in users]
        match = self._make_match('matchmaking', length, seats)
        self.matches[match.id] = match
        for uid, _ in users:
            self.user_match[uid] = match.id
        await match.start()
        return match

    def _make_match(self, mode: str, length: int, seats: list[Seat]) -> Match:
        return Match(uuid.uuid4().hex, mode, length, seats, self.send_user, self.broadcast_users, self._match_finished)

    async def _match_finished(self, match_id: str, user_ids: list[int]) -> None:
        self.matches.pop(match_id, None)
        for uid in user_ids:
            if self.user_match.get(uid) == match_id:
                self.user_match.pop(uid, None)

    def _owned_room(self, user_id: int) -> Room:
        room_id = self.user_room.get(user_id)
        room = self.rooms.get(room_id or '')
        if room is None or room.owner_id != user_id:
            raise ValueError('Only the room owner can do that')
        return room
