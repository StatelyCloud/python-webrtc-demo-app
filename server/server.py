#!/usr/bin/env python


import asyncio
import json
from collections import defaultdict
from websockets.asyncio.server import serve, ServerConnection
from websockets.exceptions import ConnectionClosedOK
from dataclasses import dataclass
from typing import Any
from datetime import datetime


@dataclass
class UserState:
    username: str
    connection: ServerConnection
    joined: datetime
    audio: bool = True
    video: bool = True


@dataclass
class RoomState:
    users: dict[str, UserState]

    def __init__(self):
        self.users = {}


rooms = defaultdict[str, RoomState](RoomState)


async def broadcast(room_id: str, sender: str, message: Any):
    broadcast_users = [
        user for user in rooms[room_id].users.values() if user.username != sender
    ]

    for user in broadcast_users:
        try:
            await user.connection.send(json.dumps(message))
        except ConnectionClosedOK:
            print(f"Broadcast failed because user: {user.username} disconnected")
            await remove_user(room_id, user.username)


async def send_to(room_id: str, recipient: str, message: Any):
    user = rooms[room_id].users[recipient]
    await user.connection.send(json.dumps(message))


async def add_user(room_id: str, username: str, connection: ServerConnection):
    if username in rooms[room_id].users:
        print(f"User {username} already in room {room_id}. Booting old user")
        await remove_user(room_id, username)

    # overwrite the user
    rooms[room_id].users[username] = UserState(
        username=username, connection=connection, joined=datetime.now()
    )
    print(
        f"User {username} joined room {room_id}: {", ".join(rooms[room_id].users.keys())}"
    )
    # tell the other users about the new user
    await broadcast(room_id, username, {"type": "user_joined", "username": username})


async def remove_user(room_id: str, username: str):
    print(f"Removing user {username} from room {room_id}")

    if username in rooms[room_id].users:
        await rooms[room_id].users[username].connection.close()
        del rooms[room_id].users[username]
    await broadcast(room_id, username, {"type": "user_left", "username": username})
    # remove the room if it's empty
    if len(rooms[room_id].users) == 0:
        del rooms[room_id]


async def handle_sdp(room_id: str, username: str, msg: dict[str, Any]):
    recipient = msg["to"]
    del msg["to"]
    msg["from"] = username
    msg["polite"] = (
        rooms[room_id].users[recipient].joined > rooms[room_id].users[username].joined
    )
    await send_to(room_id, recipient, msg)


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
            username = initial_message["username"]
            room_id = initial_message["room"]
            break

    # add the user to the room
    await add_user(room_id, username, websocket)

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
