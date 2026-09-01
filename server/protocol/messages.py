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
    visibility: Literal['private'] = 'private'


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


class PracticeStartMsg(ProtocolMessage):
    type: Literal['practice_start'] = 'practice_start'


class LeaveRoomMsg(ProtocolMessage):
    type: Literal['leave_room'] = 'leave_room'


class ResumeMsg(ProtocolMessage):
    type: Literal['resume'] = 'resume'


ClientMessage = Annotated[
    Union[
        DiscardMsg, ClaimMsg, SelfActionMsg,
        CreateRoomMsg, JoinRoomMsg, SetRoomConfigMsg, StartRoomMsg,
        QueueJoinMsg, QueueLeaveMsg, PracticeStartMsg, LeaveRoomMsg, ResumeMsg,
    ],
    Field(discriminator='type'),
]

_client_message_adapter = TypeAdapter(ClientMessage)


def parse_client_message(data: dict) -> ClientMessage:
    """Parse every client message through the protocol discriminator."""
    return _client_message_adapter.validate_python(data)
