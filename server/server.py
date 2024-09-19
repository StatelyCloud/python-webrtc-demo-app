#!/usr/bin/env python


import asyncio
import json
import os
import random
import traceback
import uuid
from typing import Any

from dotenv import load_dotenv
from schema.generated import (
    Client,
    Participant,
)
from statelydb import (
    ListToken,
    StatelyCode,
    StatelyError,
    SyncChangedItem,
    SyncDeletedItem,
    SyncReset,
    SyncUpdatedItemKeyOutsideListWindow,
    key_path,
)
from websockets.asyncio.server import ServerConnection, serve
from websockets.exceptions import ConnectionClosedError, ConnectionClosedOK


load_dotenv(dotenv_path=".env.local")

# TODO: add a heartbeat and TTL to handle zombie connections
# that can arise from the server dying unexpectedly before we can
# remove the participant from the room.
client = Client(
    store_id=int(os.environ["STORE_ID"]),
)

# keys of the form <username>-<session-id>
connections: dict[str, ServerConnection] = {}
subscribed_rooms: dict[str, dict[str, Participant]] = {}


async def broadcast(room: str, message: str):
    if room not in subscribed_rooms:
        # the room has been removed before the broadcast could happen
        print("received broadcast for room that doesn't exist. skipping")
        return
    for participant in subscribed_rooms[room].values():
        # non-blocking send to each participant
        asyncio.create_task(send_to(participant, message))


async def send_to(recipient: Participant, message: str):
    print(f"Sending message to {recipient.username}")
    connection = connections.get(f"{recipient.username}-{recipient.session_id}", None)
    if connection is not None:
        try:
            await connection.send(message)
        except ConnectionClosedOK:
            print(f"Connection to {recipient.username} closed. Removing participant")
            await remove_local_participant(
                recipient.room, recipient.username, recipient.session_id
            )
        except ConnectionClosedError:
            print(
                f"Connection to {recipient.username} closed with error. Removing participant"
            )
            # delete this when we finish debugging what causes this
            # it looks like overloaded server tbh
            traceback.print_exc()
            await remove_local_participant(
                recipient.room, recipient.username, recipient.session_id
            )

    else:
        # participant is not connected to this instance
        print(f"{recipient.username} not connected to this instance")


async def load_room(room: str) -> ListToken:
    # build the initial state and return a sync token
    list_resp = await client.begin_list(
        key_path_prefix=key_path("/Room-{room}", room=room)
    )

    async for item in list_resp:
        if isinstance(item, Participant):
            subscribed_rooms[room][item.username] = item
        else:
            raise Exception(f"Unexpected item type: {item}")

    if list_resp.token is None:
        raise Exception("Token is None")
    return list_resp.token


async def add_local_participant(
    room: str, username: str, connection: ServerConnection, session_id: uuid.UUID
):
    print(f"Adding participant {username} to room {room}")
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
        token = await load_room(room)
        asyncio.create_task(subscribe_room(room, token))

    # now put the new participant in stately to notify other subscribed server.py instances
    await client.put(
        Participant(
            room=room,
            username=username,
            session_id=session_id,
        )
    )


async def remove_local_participant(room: str, username: str, session_id: uuid.UUID):
    print(f"Removing participant: {username} from room {room}")
    # we don't need to update the local room state because the subscriber will handle that
    await client.delete(key_path(f"/Room-{room}/Participant-{username}"))
    await delete_connection(username, session_id)


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
        print("participant disconnected before sending initial message")
        return

    # make sure we get a join message first
    initial_message = json.loads(initial_message_json)

    if initial_message["type"] != "join":
        await websocket.close()
        print(
            f"initial message is not join. was {initial_message}. booting participant."
        )
        return

    # get the participant's info and create a session ID for the socket
    # so we can dedupe multiple connections from the same participant
    session_id = uuid.uuid4()
    username = initial_message["username"]
    room = initial_message["room"]

    # add the participant to the room
    await add_local_participant(room, username, websocket, session_id)

    try:
        # start listening for SDP messages on the socket
        async for msg_json in websocket:
            msg = json.loads(msg_json)
            if msg["type"] == "sdp":
                # block on this so the SDP is applied in order
                # the connections seem to work better then we do this.
                await handle_sdp(room, username, msg)
    except ConnectionClosedOK:
        print(f"participant {username} disconnected")
    except Exception as e:
        print(f"Error for participant {username}: {e}")
    finally:
        await remove_local_participant(room, username, session_id)


async def delete_connection(username: str, session_id: uuid.UUID):
    if f"{username}-{session_id}" in connections:
        await connections[f"{username}-{session_id}"].close()
        del connections[f"{username}-{session_id}"]


async def handle_changed_remote_participant(room: str, updated: Participant):
    old = subscribed_rooms[room].get(updated.username, None)
    if old is None:
        # participant added to room. we need to to notify everyone else
        await broadcast(
            room,
            json.dumps({"type": "joined", "username": updated.username}),
        )
    elif updated.session_id != old.session_id:
        # if the session id is different, we need to close the old connection
        await delete_connection(old.username, old.session_id)
    else:
        # updated offer/answer. we need to propagate to the participant
        # if they are connected to us.
        if f"{updated.username}-{updated.session_id}" in connections:
            txn = None
            while txn is None or txn.result is None or not txn.result.committed:
                try:
                    txn = await client.transaction()
                    sdp_to_send = []
                    async with txn:
                        # transactionally clear the participant SDP queue
                        # if we don't do it in a transaction its possible someone
                        # added SDP after the sync but before here which will get lost
                        # when we clear the queue since the queue will be empty before
                        # the next sync.
                        txn_current = await txn.get(Participant, updated.key_path())
                        if txn_current is None:
                            # the participant doesn't exist anymore.
                            # break the loop and keep reading sync updates
                            break
                        sdp_to_send = txn_current.pending_sdp
                        txn_current.pending_sdp = []
                        await txn.put(txn_current)
                    if txn.result is not None and txn.result.committed:
                        for sdp in sdp_to_send:
                            print(f"Sending pending sdp to {updated.username}")
                            await send_to(updated, sdp)
                except StatelyError as e:
                    if e.stately_code == StatelyCode.CONCURRENT_MODIFICATION:
                        await asyncio.sleep(random.uniform(1, 2))
                        continue
                    raise e
    # regardless, we need to update the room state
    subscribed_rooms[room][updated.username] = updated


async def handle_removed_remote_participant(room: str, username: str):
    print(f"sync detected delete participant: {username}")
    del subscribed_rooms[room][username]
    await broadcast(
        room,
        json.dumps({"type": "left", "username": username}),
    )


async def sync_room(room: str, token: ListToken) -> ListToken:
    sync_resp = await client.sync_list(token)
    async for item in sync_resp:
        if isinstance(item, SyncChangedItem):
            # participant added to room or updated offer/answer
            if not isinstance(item.item, Participant):
                raise Exception(f"Unexpected item type: {item.item}")
            await handle_changed_remote_participant(room, item.item)

        elif isinstance(item, SyncDeletedItem) or isinstance(
            item, SyncUpdatedItemKeyOutsideListWindow
        ):
            deleted_username = item.key_path.removeprefix(f"/Room-{room}/Participant-")
            await handle_removed_remote_participant(room, deleted_username)

        elif isinstance(item, SyncReset):
            subscribed_rooms[room] = {}

    if sync_resp.token is None:
        raise Exception("Sync token is None")
    return sync_resp.token


async def subscribe_room(room: str, token: ListToken) -> None:
    print(f"Subscribing to room {room}")
    # now periodically sync for state updates
    while token.can_sync:
        token = await sync_room(room, token)
        print(
            f"Syncing room {room} success. Current participants: {",".join(subscribed_rooms[room].keys())}"
        )
        if len(subscribed_rooms[room]) == 0:
            print(f"No participants in room {room}. Exiting")
            del subscribed_rooms[room]
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
