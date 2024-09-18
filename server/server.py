#!/usr/bin/env python


import asyncio
import json
from websockets.asyncio.server import serve, ServerConnection
from websockets.exceptions import ConnectionClosedOK
from typing import Any
from schema.generated import (
    Client,
    Participant,
)
from statelydb import (
    key_path,
    SyncChangedItem,
    SyncDeletedItem,
    SyncReset,
    SyncUpdatedItemKeyOutsideListWindow,
    ListToken,
    StatelyCode,
    StatelyError,
)

from dotenv import load_dotenv
import os
import uuid
import traceback

load_dotenv(dotenv_path=".env.local")

## TODO:
## - cancel room listener when requ ired
## - handle duplicate connections
## - handle room race conditions

client = Client(
    store_id=int(os.environ["STORE_ID"]),
)

# keys of the form <username>-<session-id>
connections: dict[str, ServerConnection] = {}
subscribed_rooms: dict[str, dict[str, Participant]] = {}


async def broadcast(room: str, message: str):
    for user in subscribed_rooms[room].values():
        await send_to(user, message)


async def send_to(recipient: Participant, message: str):
    print(f"Sending message to {recipient.username}-{recipient.session_id}")
    connection = connections.get(f"{recipient.username}-{recipient.session_id}", None)
    if connection is not None:
        try:
            await connection.send(message)
        except ConnectionClosedOK:
            print(
                f"Connection to {recipient.username}-{recipient.session_id} closed. Removing user"
            )
            await remove_user(recipient.room, recipient.username, recipient.session_id)
    else:
        # user is not connected to this instance
        print(
            f"{recipient.username}-{recipient.session_id} not connected to this instance"
        )


async def add_user(
    room: str, username: str, connection: ServerConnection, session_id: uuid.UUID
):
    print(f"Adding user {username}-{session_id} to room {room}")
    # add the connection and update the user in the room
    connections[f"{username}-{session_id}"] = connection
    txn = await client.transaction()
    while txn.result is None or not txn.result.committed:
        async with txn:
            await txn.put(
                Participant(
                    room=room,
                    username=username,
                    session_id=session_id,
                )
            )
    print(f"User {username} added to room {room}")
    if room in subscribed_rooms:
        print(f"Already subscribed to room {room}")
        # if we are already subscribed to the room, we dont need to do anything
        return
    # TODO: do this with an atomic
    subscribed_rooms[room] = {}

    # build the initial state
    token: ListToken | None = None
    while token is None or token.can_continue:
        list_resp = await client.begin_list(
            key_path_prefix=key_path("/Room-{room}", room=room)
        )

        async for item in list_resp:
            if isinstance(item, Participant):
                subscribed_rooms[room][item.username] = item
            else:
                raise Exception(f"Unexpected item type: {item}")
        token = list_resp.token
        if token is None:
            raise Exception("Token is None")
        elif token.can_continue:
            list_resp = await client.continue_list(token)
        elif token.can_sync:
            break

    # subscribe to the room now that we have the full state
    asyncio.create_task(subscribe_room(room, token))


async def remove_user(room: str, username: str, session_id: uuid.UUID):
    print(f"Removing user: {username} from room {room}")
    txn = await client.transaction()
    while txn.result is None or not txn.result.committed:
        async with txn:
            await txn.delete(key_path(f"/Room-{room}/Participant-{username}"))
    # let the subscriber handle this
    # del subscribed_rooms[room][username]
    if f"{username}-{session_id}" not in connections:
        print(f"User {username}-{session_id} not connected. expected connection")
        return
    await connections[f"{username}-{session_id}"].close()
    print(f"User {username} removed from room {room}")


async def handle_sdp(room: str, username: str, msg: dict[str, Any]):
    recipient_id = msg["to"]
    del msg["to"]
    msg["from"] = username

    txn = None
    while txn is None or txn.result is None or not txn.result.committed:
        try:
            txn = await client.transaction()
            async with txn:
                sender = await txn.get(
                    Participant, key_path(f"/Room-{room}/Participant-{username}")
                )
                recipient = await txn.get(
                    Participant, key_path(f"/Room-{room}/Participant-{recipient_id}")
                )
                if sender is None or recipient is None:
                    print(
                        f"sender: {sender}, recipient: {recipient}. neither should be None"
                    )
                    return
                msg["polite"] = sender.joined > recipient.joined
                recipient.pending_sdp.append(json.dumps(msg))
                await txn.put(recipient)
                return
        except StatelyError as e:
            if e.stately_code == StatelyCode.CONCURRENT_MODIFICATION:
                print("Conditional check failed. Retrying")
                continue
            raise e


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
            room = initial_message["room"]
            break

    # add the user to the room
    await add_user(room, username, websocket, session_id)

    try:
        async for msg_json in websocket:
            msg = json.loads(msg_json)
            if msg["type"] == "sdp":
                await handle_sdp(room, username, msg)
    except ConnectionClosedOK:
        print(f"User {username} disconnected")
    except Exception as e:
        print(f"Error for user {username}: {e}")
        # print(traceback.format_exc())
    finally:
        await remove_user(room, username, session_id)


async def subscribe_room(room: str, token: ListToken) -> None:
    print(f"Subscribing to room {room}")
    # now periodically sync for state updates
    # loop can be broken by removing the room from subscribed_rooms
    while token.can_sync:
        # TODO: exit this loop if we don't have any users in the room
        sync_resp = await client.sync_list(token)
        async for item in sync_resp:
            if isinstance(item, SyncChangedItem):
                # user added to room or updated offer/answer
                current = item.item
                if not isinstance(current, Participant):
                    raise Exception(f"Unexpected item type: {current}")

                old = subscribed_rooms[room].get(current.username, None)
                if old is None:
                    # user added to room. we need to to notify everyone else
                    await broadcast(
                        room,
                        json.dumps(
                            {"type": "user_joined", "username": current.username}
                        ),
                    )
                elif current.session_id != old.session_id:
                    # if the session id is different, we need to close the old connection
                    if f"{current.username}-{old.session_id}" in connections:
                        await connections[
                            f"{current.username}-{old.session_id}"
                        ].close()
                        del connections[f"{current.username}-{old.session_id}"]
                else:
                    # updated offer/answer. we need to propagate to the user
                    # if they are connected to us.
                    if f"{current.username}-{current.session_id}" in connections:
                        # TODO: do this in a txn
                        print(f"sending pending sdp to {current.username}")
                        for sdp in current.pending_sdp:
                            await send_to(current, sdp)
                        current.pending_sdp = []
                        await client.put(item.item)
                # regardless, we need to update the room state
                subscribed_rooms[room][current.username] = current

            elif isinstance(item, SyncDeletedItem) or isinstance(
                item, SyncUpdatedItemKeyOutsideListWindow
            ):
                deleted_username = item.key_path.removeprefix(
                    f"/Room-{room}/Participant-"
                )
                del subscribed_rooms[room][deleted_username]
                await broadcast(
                    room,
                    json.dumps({"type": "user_left", "username": deleted_username}),
                )

            elif isinstance(item, SyncReset):
                raise Exception("SyncReset is not implemented")

        if sync_resp.token is None:
            raise Exception("Sync token is None")
        token = sync_resp.token
        print(
            f"Syncing room {room} success. Current users: {subscribed_rooms[room].keys()}. Current states: {[x.__dict__ for x in subscribed_rooms[room].values()]}"
        )
        await asyncio.sleep(0.5)


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
