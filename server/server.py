#!/usr/bin/env python


import asyncio
import json
from collections import defaultdict
from websockets.asyncio.server import serve, ServerConnection
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
        await user.connection.send(json.dumps(message))


async def send_to(room_id: str, sender: str, recipient: str, message: Any):
    user = rooms[room_id].users[recipient]
    await user.connection.send(json.dumps(message))


async def handler(websocket: ServerConnection) -> None:
    # wait for the initial message
    initial_message_json = await websocket.recv()
    initial_message = json.loads(initial_message_json)

    # make sure it's a join message
    if initial_message["type"] != "join":
        await websocket.close()
        print(f"initial message is not join. was {initial_message}. booting user.")
        return

    # add the user to the room
    room_id = initial_message["room"]
    username = initial_message["username"]
    print(f"User {username} joined room {room_id}")
    rooms[room_id].users[username] = UserState(
        username=username, connection=websocket, joined=datetime.now()
    )

    # tell the other users about the new user
    await broadcast(room_id, username, {"type": "user_joined", "username": username})

    async for msg_json in websocket:
        msg = json.loads(msg_json)
        if msg["type"] == "sdp":
            to_username = msg["to"]
            del msg["to"]
            msg["from"] = username
            msg["polite"] = (
                rooms[room_id].users[to_username].joined
                > rooms[room_id].users[username].joined
            )
            await send_to(room_id, username, to_username, msg)

    print(f"User {username} left room {room_id}")
    del rooms[room_id].users[username]
    await broadcast(room_id, username, {"type": "user_left", "username": username})
    # remove the room if it's empty
    if len(rooms[room_id].users) == 0:
        del rooms[room_id]


async def main():
    async with serve(handler, "localhost", 8765):
        # run forever
        try:
            await asyncio.get_running_loop().create_future()
        except asyncio.CancelledError:
            pass
            print("Server stopped")


if __name__ == "__main__":
    asyncio.run(main())
