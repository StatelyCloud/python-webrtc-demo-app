from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class SignalingMessageType(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    SignalingMessageType_UNSPECIFIED: _ClassVar[SignalingMessageType]
    SignalingMessageType_Join: _ClassVar[SignalingMessageType]
    SignalingMessageType_Leave: _ClassVar[SignalingMessageType]
    SignalingMessageType_SDP: _ClassVar[SignalingMessageType]
SignalingMessageType_UNSPECIFIED: SignalingMessageType
SignalingMessageType_Join: SignalingMessageType
SignalingMessageType_Leave: SignalingMessageType
SignalingMessageType_SDP: SignalingMessageType

class Participant(_message.Message):
    __slots__ = ("username", "room", "joined")
    USERNAME_FIELD_NUMBER: _ClassVar[int]
    ROOM_FIELD_NUMBER: _ClassVar[int]
    JOINED_FIELD_NUMBER: _ClassVar[int]
    username: str
    room: str
    joined: int
    def __init__(self, username: _Optional[str] = ..., room: _Optional[str] = ..., joined: _Optional[int] = ...) -> None: ...

class SignalingMessage(_message.Message):
    __slots__ = ("message_id", "message_type", "recipient", "room", "created_at", "payload_json")
    MESSAGE_ID_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_TYPE_FIELD_NUMBER: _ClassVar[int]
    RECIPIENT_FIELD_NUMBER: _ClassVar[int]
    ROOM_FIELD_NUMBER: _ClassVar[int]
    CREATED_AT_FIELD_NUMBER: _ClassVar[int]
    PAYLOAD_JSON_FIELD_NUMBER: _ClassVar[int]
    message_id: int
    message_type: SignalingMessageType
    recipient: str
    room: str
    created_at: int
    payload_json: str
    def __init__(self, message_id: _Optional[int] = ..., message_type: _Optional[_Union[SignalingMessageType, str]] = ..., recipient: _Optional[str] = ..., room: _Optional[str] = ..., created_at: _Optional[int] = ..., payload_json: _Optional[str] = ...) -> None: ...
