# -*- coding: utf-8 -*-
# Generated by the protocol buffer compiler.  DO NOT EDIT!
# NO CHECKED-IN PROTOBUF GENCODE
# source: schema.proto
# Protobuf Python Version: 5.27.2
"""Generated protocol buffer code."""
from google.protobuf import descriptor as _descriptor
from google.protobuf import descriptor_pool as _descriptor_pool
from google.protobuf import runtime_version as _runtime_version
from google.protobuf import symbol_database as _symbol_database
from google.protobuf.internal import builder as _builder
_runtime_version.ValidateProtobufRuntimeVersion(
    _runtime_version.Domain.PUBLIC,
    5,
    27,
    2,
    '',
    'schema.proto'
)
# @@protoc_insertion_point(imports)

_sym_db = _symbol_database.Default()




DESCRIPTOR = _descriptor_pool.Default().AddSerializedFile(b'\n\x0cschema.proto\x12\x11stately.generated\"\x97\x01\n\x0bParticipant\x12\x1a\n\x08username\x18\x01 \x01(\tR\x08username\x12\x12\n\x04room\x18\x02 \x01(\tR\x04room\x12\x16\n\x06joined\x18\x03 \x01(\x12R\x06joined\x12\x1e\n\nsession_id\x18\x04 \x01(\x0cR\nsession_id\x12 \n\x0bpending_sdp\x18\x05 \x03(\tR\x0bpending_sdpb\x06proto3')

_globals = globals()
_builder.BuildMessageAndEnumDescriptors(DESCRIPTOR, _globals)
_builder.BuildTopDescriptorsAndMessages(DESCRIPTOR, 'schema_pb2', _globals)
if not _descriptor._USE_C_DESCRIPTORS:
  DESCRIPTOR._loaded_options = None
  _globals['_PARTICIPANT']._serialized_start=36
  _globals['_PARTICIPANT']._serialized_end=187
# @@protoc_insertion_point(module_scope)
