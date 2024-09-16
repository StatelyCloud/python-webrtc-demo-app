#!/usr/bin/env python


import asyncio
import json
from collections import defaultdict
from websockets.asyncio.server import serve, ServerConnection
from websockets.exceptions import ConnectionClosedOK
from dataclasses import dataclass
from typing import Any
from datetime import datetime
from .schema.generated import (
    Client,
    Participant,
    SignalingMessage,
    SignalingMessageType,
)
from statelydb import AuthTokenProvider, key_path
from statelydb.src.list import ListToken
from dotenv import load_dotenv
import os
import uuid

load_dotenv(dotenv_path=".env.local")


def token_provider(token: str) -> AuthTokenProvider:
    async def get_token() -> str:
        return token

    return get_token


client = Client(
    token_provider=token_provider(os.environ["API_KEY"]),
    endpoint=os.environ["ENDPOINT"],
    store_id=int(os.environ["STORE_ID"]),
)

# keys of the form <username>-<session-id>
connections: dict[str, ServerConnection] = {}
subscribed_rooms: dict[str, dict[str, Participant]] = {}

# async def broadcast(room_id: str, sender: str, message: Any):
#     broadcast_users = [
#         user for user in rooms[room_id].users.values() if user.username != sender
#     ]

#     for user in broadcast_users:
#         try:
#             await user.connection.send(json.dumps(message))
#         except ConnectionClosedOK:
#             print(f"Broadcast failed because user: {user.username} disconnected")
#             await remove_user(room_id, user.username)


# async def send_to(room_id: str, recipient: str, message: Any):
#     user = rooms[room_id].users[recipient]
#     await user.connection.send(json.dumps(message))


async def add_user(
    room: str, username: str, connection: ServerConnection, session_id: uuid.UUID
):
    connections[f"{username}-{session_id}"] = connection
    txn = await client.transaction()
    async with txn:
        # get the participant. if one exists for this user, then update them and add a removal to the message list
        # we assume that its impossible for our random session ID to match an existing one
        participants: list[Participant] = []
        list_resp = await txn.begin_list(
            key_path_prefix=key_path("/Room-{room_id}/Participant-", username=username)
        )
        token = None
        while True:
            async for item in list_resp:
                if isinstance(item, Participant):
                    participants.append(item)

            token = list_resp.token
            if token is None:
                raise Exception("Token is None")
            if token.can_continue:
                list_resp = await client.continue_list(token)
            else:
                break

        duplicate_usernames = list(
            filter(lambda x: x.username == username, participants)
        )
        if len(duplicate_usernames):
            for du in duplicate_usernames:
                # if an existing participant has the same username, then we need to remove them
                # so that peers drop their video stream
                await txn.put(
                    SignalingMessage(
                        # TODO: fix constructor so that we can omit this
                        message_id=0,
                        message_type=SignalingMessageType.SignalingMessageType_Leave,
                        room=room,
                        payload_json=json.dumps(
                            {
                                "username": username,
                                "session_id": du.session_id,
                            }
                        ),
                    )
                )

        # now put the new state for the participant
        await txn.put(
            SignalingMessage(
                # TODO: fix constructor so that we can omit this
                message_id=0,
                message_type=SignalingMessageType.SignalingMessageType_Join,
                room=room,
                payload_json=json.dumps(
                    {
                        "username": username,
                        "session_id": session_id,
                    }
                ),
            )
        )
        await txn.put(
            Participant(
                room=room,
                username=username,
                session_id=session_id,
            )
        )

        # now start a listener for the room.
        # needs to be done before the transaction is committed
        # so that we don't miss other listeners responses to the join message
        asyncio.create_task(subscribe_room(room))


async def remove_user(room_id: str, username: str):
    # print(f"Removing user {username} from room {room_id}")

    # if username in rooms[room_id].users:
    #     await rooms[room_id].users[username].connection.close()
    #     del rooms[room_id].users[username]
    # await broadcast(room_id, username, {"type": "user_left", "username": username})
    # # remove the room if it's empty
    # if len(rooms[room_id].users) == 0:
    #     del rooms[room_id]
    pass


async def handle_sdp(room_id: str, username: str, msg: dict[str, Any]):
    # recipient = msg["to"]
    # del msg["to"]
    # msg["from"] = username
    # msg["polite"] = (
    #     rooms[room_id].users[recipient].joined > rooms[room_id].users[username].joined
    # )
    # await send_to(room_id, recipient, msg)
    pass


async def handler(websocket: ServerConnection) -> None:
    # wait for the initial message
    while True:
        try:
            initial_message_json = await websocket.recv()
        except ConnectionClosedOK:
            print("User disconnected before sending initial message")
            return

        # make sure we get a join message first
        initial_message = json.loads(initial_message_json)
        if initial_message["type"] == "ping":
            # this is just the keepalive
            # we can ignore it
            continue
        elif initial_message["type"] != "join":
            await websocket.close()
            print(f"initial message is not join. was {initial_message}. booting user.")
            return
        else:
            # get the user's info
            session_id = uuid.uuid4()
            username = initial_message["username"]
            room_id = initial_message["room"]
            break

    # add the user to the room
    await add_user(room_id, username, websocket, session_id)

    try:
        async for msg_json in websocket:
            msg = json.loads(msg_json)
            if msg["type"] == "sdp":
                await handle_sdp(room_id, username, msg)
    except ConnectionClosedOK:
        print(f"User {username} disconnected")
    except Exception as e:
        print(f"Error for user {username}: {e}")
    finally:
        await remove_user(room_id, username)


async def subscribe_room(room: str) -> None:
    if room in subscribed_rooms:
        return
    subscribed_rooms[room] = {}
    token = None
    while token is None or token.can_continue:
        # TODO: pull everything since now. we dont care about the past
        list_resp = await client.begin_list(key_path_prefix=key_path("/Room-{room_id}"))

        async for item in list_resp:
            if isinstance(item, SignalingMessage):
                # msg = item
                # if msg.message_type == SignalingMessageType.SignalingMessageType_Join:
                #     payload = json.loads(msg.payload_json)
                #     subscribed_rooms[room][payload["username"]] = payload["session_id"]
                # elif msg.message_type == SignalingMessageType.SignalingMessageType_Leave:
                #     payload = json.loads(msg.payload_json)
                #     del subscribed_rooms[room][payload["username"]]
                pass
            elif isinstance(item, Participant):
                subscribed_rooms[room][item.username] = item
        token = list_resp.token
        if token is None:
            raise Exception("Token is None")
        elif token.can_continue:
            list_resp = await client.continue_list(token)
        elif token.can_sync:
            break

    while token is not None and token.can_sync:
        pass


async def main():
    async with serve(handler, "localhost", 8765, ping_interval=10, ping_timeout=5):
        # run forever
        try:
            await asyncio.get_running_loop().create_future()
        except asyncio.CancelledError:
            pass
            print("Server stopped")


if __name__ == "__main__":
    asyncio.run(main())
