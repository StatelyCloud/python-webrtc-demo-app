import {
  enumType,
  itemType,
  string,
  timestampMicroseconds,
  uint,
  uuid,
} from "@stately-cloud/schema";

export const Participant = itemType("Participant", {
  keyPath: ["/Room-:room/Participant-:username"],
  fields: {
    username: {
      type: string,
      fieldNum: 1,
    },
    room: {
      type: string,
      fieldNum: 2,
    },
    joined: {
      type: timestampMicroseconds,
      fieldNum: 3,
      fromMetadata: "createdAtTime",
    },
    session_id: {
      type: uuid,
      fieldNum: 4,
    },
  },
});

export const SignalingMessageType = enumType("SignalingMessageType", {
  Join: 1,
  Leave: 2,
  SDP: 3,
});

export const SignalingMessage = itemType("SignalingMessage", {
  keyPath: ["/Room-:room/SignalingMessage-:message_id"],
  fields: {
    message_id: {
      type: uint,
      fieldNum: 1,
      initialValue: "sequence",
    },
    message_type: {
      type: SignalingMessageType,
      fieldNum: 2,
    },
    room: {
      type: string,
      required: true,
      fieldNum: 3,
    },
    created_at: {
      type: timestampMicroseconds,
      fieldNum: 4,
      fromMetadata: "createdAtTime",
    },
    payload_json: {
      type: string,
      fieldNum: 5,
    },
  },
});
