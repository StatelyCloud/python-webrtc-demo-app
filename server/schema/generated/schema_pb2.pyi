from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Iterable as _Iterable, Optional as _Optional

DESCRIPTOR: _descriptor.FileDescriptor

class Participant(_message.Message):
    __slots__ = ("username", "room", "joined", "session_id", "pending_sdp")
    USERNAME_FIELD_NUMBER: _ClassVar[int]
    ROOM_FIELD_NUMBER: _ClassVar[int]
    JOINED_FIELD_NUMBER: _ClassVar[int]
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    PENDING_SDP_FIELD_NUMBER: _ClassVar[int]
    username: str
    room: str
    joined: int
    session_id: bytes
    pending_sdp: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, username: _Optional[str] = ..., room: _Optional[str] = ..., joined: _Optional[int] = ..., session_id: _Optional[bytes] = ..., pending_sdp: _Optional[_Iterable[str]] = ...) -> None: ...
