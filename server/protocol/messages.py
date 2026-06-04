"""
Pydantic v2 message schemas for the IMR Online WebSocket protocol.
Every message has a 'type' discriminator field.
"""
from __future__ import annotations
from typing import Literal, Optional, Any
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Client → Server
# ---------------------------------------------------------------------------

class JoinMsg(BaseModel):
    type: Literal['join'] = 'join'
    name: str


class ReadyMsg(BaseModel):
    type: Literal['ready'] = 'ready'


class DiscardMsg(BaseModel):
    type: Literal['discard'] = 'discard'
    tile: str
    face_down: bool = False


class ClaimMsg(BaseModel):
    type: Literal['claim'] = 'claim'
    claim: str                     # 'chow' | 'pong' | 'kong' | 'win' | 'skip'
    tiles: list[str] = Field(default_factory=list)  # for chow: tiles used from hand


class SelfActionMsg(BaseModel):
    type: Literal['self_action'] = 'self_action'
    action: str    # 'tsumo'|'concealed_kong'|'added_kong'|'redraw'|'declare_ready'
    tile: Optional[str] = None


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
}


def parse_client_message(data: dict) -> BaseModel:
    """Parse and validate a client message dict, raising ValidationError on bad input."""
    msg_type = data.get('type')
    cls = C2S_MESSAGE_TYPES.get(msg_type)
    if cls is None:
        raise ValueError(f"Unknown message type: {msg_type!r}")
    return cls.model_validate(data)
