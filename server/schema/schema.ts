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
      // The self-assigned username of the participant.
      type: string,
      fieldNum: 1,
    },
    room: {
      // The room the participant is in. This is a simple string identifier.
      type: string,
      fieldNum: 2,
    },
    joined: {
      // The server generated timestamp of when the participant joined the room.
      // We use this to determine which peer is the "polite" peer during ICE negotiation.
      type: timestampMicroseconds,
      fieldNum: 3,
      fromMetadata: "createdAtTime",
    },
    session_id: {
      // This is a UUID that is generated by the server when a websocket connection is received
      // Session ID allows us to deduplicate multiple websockets from the same user which can
      // be left hanging after an unexpected disconnect.
      type: uuid,
      fieldNum: 4,
    },
    pending_sdp: {
      // This is an array of SDP strings that are waiting to be sent to the participant.
      // This queue is periodically checked by the server and streamed to the participant
      // over the websocket.
      // This queue contains JSON strings which must be parsed by the client.
      type: arrayOf(string),
      fieldNum: 5,
      required: false,
    },
  },
});
