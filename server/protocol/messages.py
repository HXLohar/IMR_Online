"""
Pydantic v2 message schemas for the IMR Online WebSocket protocol.
Every message has a 'type' discriminator field.
"""
from __future__ import annotations
from typing import Annotated, Literal, Optional, Union
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator


# ---------------------------------------------------------------------------
# Client → Server
# ---------------------------------------------------------------------------

class ProtocolMessage(BaseModel):
    model_config = ConfigDict(extra='forbid')


MatchLength = Literal[1, 4, 8]
BotType = Literal['efficiency', 'auto_call', 'discard_only']


class JoinMsg(ProtocolMessage):
    type: Literal['join'] = 'join'
    name: str = Field(min_length=1, max_length=32)


class ReadyMsg(ProtocolMessage):
    type: Literal['ready'] = 'ready'


class DiscardMsg(ProtocolMessage):
    type: Literal['discard'] = 'discard'
    tile: str
    face_down: bool = False
    turn_id: int | None = None


class ClaimMsg(ProtocolMessage):
    type: Literal['claim'] = 'claim'
    claim: Literal['straight_call', 'triplet_call', 'direct_quad_call', 'win', 'skip']
    tiles: list[str] = Field(default_factory=list)  # for straight_call: tiles used from hand
    window_id: int | None = None


class SelfActionMsg(ProtocolMessage):
    type: Literal['self_action'] = 'self_action'
    action: Literal['tsumo', 'concealed_quad_declare', 'upgraded_quad_declare', 'redraw', 'declare_wait']
    tile: Optional[str] = None
    turn_id: int | None = None


class CreateRoomMsg(ProtocolMessage):
    type: Literal['create_room'] = 'create_room'
    length: MatchLength = 1
    visibility: Literal['public', 'private'] = 'public'


class JoinRoomMsg(ProtocolMessage):
    type: Literal['join_room'] = 'join_room'
    room_id: str | None = None
    code: str | None = None

    @model_validator(mode='after')
    def has_target(self) -> 'JoinRoomMsg':
        if not self.room_id and not self.code:
            raise ValueError('room_id or code is required')
        return self


class SetRoomConfigMsg(ProtocolMessage):
    type: Literal['set_room_config'] = 'set_room_config'
    length: MatchLength = 1
    bots: dict[str, BotType | None] = Field(default_factory=dict)


class StartRoomMsg(ProtocolMessage):
    type: Literal['start_room'] = 'start_room'


class QueueJoinMsg(ProtocolMessage):
    type: Literal['queue_join'] = 'queue_join'
    length: MatchLength = 1


class QueueLeaveMsg(ProtocolMessage):
    type: Literal['queue_leave'] = 'queue_leave'
    length: MatchLength = 1


class LeaveRoomMsg(ProtocolMessage):
    type: Literal['leave_room'] = 'leave_room'


class ResumeMsg(ProtocolMessage):
    type: Literal['resume'] = 'resume'


# ---------------------------------------------------------------------------
# Server → Client (output dicts — not validated on send, informational)
# ---------------------------------------------------------------------------

class PlayerInfo(BaseModel):
    seat: int
    name: str
    is_bot: bool


# Outbound payloads are plain dicts built by the FSM; pydantic is only used
# for *inbound* validation. Outbound types are documented here as reference.

C2S_MESSAGE_TYPES = {
    'join': JoinMsg,
    'ready': ReadyMsg,
    'discard': DiscardMsg,
    'claim': ClaimMsg,
    'self_action': SelfActionMsg,
    'create_room': CreateRoomMsg,
    'join_room': JoinRoomMsg,
    'set_room_config': SetRoomConfigMsg,
    'start_room': StartRoomMsg,
    'queue_join': QueueJoinMsg,
    'queue_leave': QueueLeaveMsg,
    'leave_room': LeaveRoomMsg,
    'resume': ResumeMsg,
}

ClientMessage = Annotated[
    Union[
        JoinMsg, ReadyMsg, DiscardMsg, ClaimMsg, SelfActionMsg,
        CreateRoomMsg, JoinRoomMsg, SetRoomConfigMsg, StartRoomMsg,
        QueueJoinMsg, QueueLeaveMsg, LeaveRoomMsg, ResumeMsg,
    ],
    Field(discriminator='type'),
]

_client_message_adapter = TypeAdapter(ClientMessage)


def parse_client_message(data: dict) -> ClientMessage:
    """Parse every client message through the protocol discriminator."""
    return _client_message_adapter.validate_python(data)
