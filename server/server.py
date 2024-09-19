#!/usr/bin/env python


import asyncio
import json
from websockets.asyncio.server import serve, ServerConnection
from websockets.exceptions import ConnectionClosedOK, ConnectionClosedError
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
import random
from dotenv import load_dotenv
import os
import uuid
import traceback

load_dotenv(dotenv_path=".env.local")

## TODO:
## - cancel room listener when required
## - handle duplicate connections
## - handle room race conditions
## - try and do more stuff in parallel

client = Client(
    store_id=int(os.environ["STORE_ID"]),
)

# keys of the form <username>-<session-id>
connections: dict[str, ServerConnection] = {}
subscribed_rooms: dict[str, dict[str, Participant]] = {}


async def broadcast(room: str, message: str):
    for user in subscribed_rooms[room].values():
        # non-blocking send to each user
        asyncio.create_task(send_to(user, message))


async def send_to(recipient: Participant, message: str):
    print(f"Sending message to {recipient.username}")
    connection = connections.get(f"{recipient.username}-{recipient.session_id}", None)
    if connection is not None:
        try:
            await connection.send(message)
        except ConnectionClosedOK:
            print(f"Connection to {recipient.username} closed. Removing user")
            await remove_user(recipient.room, recipient.username, recipient.session_id)
        except ConnectionClosedError:
            print(
                f"Connection to {recipient.username} closed with error. Removing user"
            )
            # delete this when we finish debugging what causes this
            # it looks like overloaded server tbh
            traceback.print_exc()
            await remove_user(recipient.room, recipient.username, recipient.session_id)

    else:
        # user is not connected to this instance
        print(f"{recipient.username} not connected to this instance")


async def populate_room(room: str) -> ListToken:
    # build the initial state and return a sync token
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
            return token

    # get here if token cant sync or continue which is a stately bug
    raise Exception("Token is in invalid state. Cannot sync or continue")


async def add_user(
    room: str, username: str, connection: ServerConnection, session_id: uuid.UUID
):
    print(f"Adding user {username} to room {room}")
    # add the connection to the connections dict
    connections[f"{username}-{session_id}"] = connection

    # subscribe to the room if we are not already
    if room not in subscribed_rooms:
        print(f"subscribing to {room}")
        # because we're single threaded and we don't yield or await
        # between reading from subscribed_rooms and writing here
        # we can guarantee that the room has not been added yet.
        # otherwise we'd need a CAS operation here.
        subscribed_rooms[room] = {
            username: Participant(room=room, username=username, session_id=session_id)
        }
        token = await populate_room(room)
        asyncio.create_task(subscribe_room(room, token))

    # now put the new user in stately to notify other servers
    await client.put(
        Participant(
            room=room,
            username=username,
            session_id=session_id,
        )
    )


async def remove_user(room: str, username: str, session_id: uuid.UUID):
    print(f"Removing user: {username} from room {room}")
    # we don't need to update the local room stately because the subscriber will handle that
    await client.delete(key_path(f"/Room-{room}/Participant-{username}"))
    if f"{username}-{session_id}" not in connections:
        print(f"User {username}-{session_id} not connected. expected connection")
        return
    await connections[f"{username}-{session_id}"].close()
    print(f"User {username} removed from room {room}")


async def handle_sdp(room: str, username: str, msg: dict[str, Any]):
    recipient_id = msg["to"]
    del msg["to"]
    msg["from"] = username
    sender = await client.get(
        Participant, key_path(f"/Room-{room}/Participant-{username}")
    )
    txn = None
    while txn is None or txn.result is None or not txn.result.committed:
        try:
            txn = await client.transaction()
            async with txn:
                recipient = await txn.get(
                    Participant, key_path(f"/Room-{room}/Participant-{recipient_id}")
                )
                if sender is None or recipient is None:
                    print(
                        f"sender: {sender}, recipient: {recipient}. neither should be None"
                    )
                    return
                msg["polite"] = sender.joined < recipient.joined
                recipient.pending_sdp.append(json.dumps(msg))
                await txn.put(recipient)
                return
        except StatelyError as e:
            if e.stately_code == StatelyCode.CONCURRENT_MODIFICATION:
                await asyncio.sleep(random.uniform(1, 2))
                continue
            raise e


async def handler(websocket: ServerConnection) -> None:
    # wait for the initial message
    try:
        initial_message_json = await websocket.recv()
    except ConnectionClosedOK:
        print("User disconnected before sending initial message")
        return

    # make sure we get a join message first
    initial_message = json.loads(initial_message_json)

    if initial_message["type"] != "join":
        await websocket.close()
        print(f"initial message is not join. was {initial_message}. booting user.")
        return

    # get the user's info and create a session ID for the socket
    # so we can dedupe multiple connections from the same user
    session_id = uuid.uuid4()
    username = initial_message["username"]
    room = initial_message["room"]

    # add the user to the room
    await add_user(room, username, websocket, session_id)

    try:
        # start listening for SDP messages on the socket
        async for msg_json in websocket:
            msg = json.loads(msg_json)
            if msg["type"] == "sdp":
                # block on this so the SDP is applied in order
                await handle_sdp(room, username, msg)
    except ConnectionClosedOK:
        print(f"User {username} disconnected")
    except Exception as e:
        print(f"Error for user {username}: {e}")
    finally:
        await remove_user(room, username, session_id)


async def delete_connection(username: str, session_id: uuid.UUID):
    if f"{username}-{session_id}" in connections:
        await connections[f"{username}-{session_id}"].close()
        del connections[f"{username}-{session_id}"]


async def sync_room(room: str, token: ListToken) -> ListToken:
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
                asyncio.create_task(
                    broadcast(
                        room,
                        json.dumps(
                            {"type": "user_joined", "username": current.username}
                        ),
                    )
                )
            elif current.session_id != old.session_id:
                # if the session id is different, we need to close the old connection
                await delete_connection(old.username, old.session_id)
            else:
                # updated offer/answer. we need to propagate to the user
                # if they are connected to us.
                if f"{current.username}-{current.session_id}" in connections:
                    txn = None
                    while txn is None or txn.result is None or not txn.result.committed:
                        try:
                            txn = await client.transaction()
                            sdp_to_send = []
                            async with txn:
                                # transactionally clear the user SDP queue
                                # if we don't do it in a transaction its possible someone
                                # added SDP after the sync but before here which will get lost
                                # when we clear the queue since the queue will be empty before
                                # the next sync.
                                txn_current = await txn.get(
                                    Participant, current.key_path()
                                )
                                if txn_current is None:
                                    # the user doesn't exist anymore.
                                    # break the loop and keep reading sync updates
                                    break
                                sdp_to_send = txn_current.pending_sdp
                                txn_current.pending_sdp = []
                                await txn.put(txn_current)
                            if txn.result is not None and txn.result.committed:
                                for sdp in sdp_to_send:
                                    print(f"Sending pending sdp to {current.username}")
                                    await send_to(current, sdp)
                        except StatelyError as e:
                            if e.stately_code == StatelyCode.CONCURRENT_MODIFICATION:
                                await asyncio.sleep(random.uniform(1, 2))
                                continue
                            raise e
            # regardless, we need to update the room state
            subscribed_rooms[room][current.username] = current

        elif isinstance(item, SyncDeletedItem) or isinstance(
            item, SyncUpdatedItemKeyOutsideListWindow
        ):
            deleted_username = item.key_path.removeprefix(f"/Room-{room}/Participant-")
            print(f"sync detected delete user: {deleted_username}")
            del subscribed_rooms[room][deleted_username]
            asyncio.create_task(
                broadcast(
                    room,
                    json.dumps({"type": "user_left", "username": deleted_username}),
                )
            )

        elif isinstance(item, SyncReset):
            raise Exception("SyncReset is not implemented")

    if sync_resp.token is None:
        raise Exception("Sync token is None")
    return sync_resp.token


async def subscribe_room(room: str, token: ListToken) -> None:
    print(f"Subscribing to room {room}")
    # now periodically sync for state updates
    while token.can_sync:
        token = await sync_room(room, token)
        print(
            f"Syncing room {room} success. Current users: {",".join(subscribed_rooms[room].keys())}"
        )
        if len(subscribed_rooms[room]) == 0:
            print(f"No users in room {room}. Exiting")
            return
        # wait 1 sec then loop again
        await asyncio.sleep(1)


async def main():
    async with serve(handler, "localhost", 8765, ping_interval=5, ping_timeout=5):
        # run forever
        try:
            await asyncio.get_running_loop().create_future()
        except asyncio.CancelledError:
            pass
            print("Server stopped")


if __name__ == "__main__":
    asyncio.run(main())
