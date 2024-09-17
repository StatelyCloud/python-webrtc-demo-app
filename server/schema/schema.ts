import {
  itemType,
  string,
  timestampMicroseconds,
  uuid,
  arrayOf,
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
    pending_sdp: {
      type: arrayOf(string),
      fieldNum: 5,
      required: false,
    },
  },
});
