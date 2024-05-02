import anyio
from anyio import Event, TASK_STATUS_IGNORED
from anyio.abc import TaskStatus
from pycrdt import Doc
from pycrdt_websocket.yutils import (
    process_sync_message,
    read_message,
    YMessageType,
    YSyncMessageType,
    create_sync_step1_message,
    create_sync_step2_message,
    create_update_message,
    write_var_uint
)
from pycrdt_websocket.websocket import Websocket 
import contextlib
from logging import Logger, getLogger
from functools import partial
from typing import Type

log = getLogger(__name__)

class ElvaProvider():

    def __init__(self, ydocs: dict[str, Doc], connection: Websocket, log: Logger | None = None):
        self.log = log or getLogger(__name__)
        self.ydocs = ydocs
        self.is_synced = dict()
        self.connection = connection
        for uuid in ydocs.keys():
            self.is_synced.update({uuid: False})
            self.ydocs[uuid].observe(partial(self.observe, uuid=uuid))


    async def __aenter__(self) -> 'ElvaProvider':
        async with contextlib.AsyncExitStack() as exit_stack:
            tg = anyio.create_task_group()
            self.task_group = await exit_stack.enter_async_context(tg)
            self.exit_stack = exit_stack.pop_all()
           # for uuid, ydoc in self.ydocs.items():
           #     print(f"> observing YDoc {ydoc} with UUID {uuid}")
            self.task_group.start_soon(self.recv)
            self.task_group.start_soon(self.sync_all) 
        return self

    async def __aexit__(self, exc_type, exc_value, exc_tb):
        self.task_group.cancel_scope.cancel()
        self.task_group = None
        return await self.exit_stack.__aexit__(exc_type, exc_value, exc_tb)

    async def sync_all(self):
        for uuid, ydoc in self.ydocs.items():
            print(f"> syncing YDoc {ydoc} with UUID {uuid}")
            await self.sync(uuid)

    async def sync(self, uuid):
        ydoc = self.ydocs[uuid]
        state = ydoc.get_state()
        msg = create_sync_step1_message(state)
        print("> sending SYNC_STEP1 message")
        await self.send(msg, uuid)

    def create_uuid_message(self, message, uuid) -> bytes:
        buuid = uuid.encode()
        return write_var_uint(len(buuid)) + buuid + message

    def observe(self, event, uuid):
        if event.update != b"\x00\x00":
            message = create_update_message(event.update)
            print(f"> update message {message} from observe callback")
            self.task_group.start_soon(self.send, message, uuid)

    async def send(self, message, uuid):
        message = self.create_uuid_message(message, uuid)
        print(f"> sending {message} for {uuid}")
        await self.connection.send(message)

    def process_uuid_message(self, message: bytes) -> tuple[str, bytes]:
        buuid = read_message(message)
        print(f"> binary uuid {buuid} extracted")
        return buuid.decode(), message[len(buuid) + 1:]

    async def process_sync_message(self, message: bytes, uuid: str):
        message_type = message[0]
        msg = message[1:]
        try:
            ydoc = self.ydocs[uuid]
        except:
            return
        sync_message_type = YSyncMessageType(message_type).name
        print(f"> received {sync_message_type} message")
        if message_type == YSyncMessageType.SYNC_STEP1:
            state = read_message(msg)
            update = ydoc.get_update(state)
            reply = create_sync_step2_message(update)
            print(f"> sending SYNC_STEP2 message {reply}")
            await self.send(reply, uuid)
            if not self.is_synced[uuid]:
                await self.sync(uuid)
        elif message_type in (
            YSyncMessageType.SYNC_STEP2,
            YSyncMessageType.SYNC_UPDATE,
        ):
            update = read_message(msg)
            print(f">>> got update {update}")
            if update != b"\x00\x00":
                ydoc.apply_update(update)
            if message_type == YSyncMessageType.SYNC_STEP2:
                self.is_synced.update({uuid: True})

    async def process_update_message(self, message: bytes, uuid: str):
        message_type = message[0]
        msg = message[1:]
        if message_type == YMessageType.SYNC:
            print("> processing sync message")
            await self.process_sync_message(msg, uuid)
        elif message_type == YMessageType.AWARENESS:
            print("> received awareness message")

    async def recv(self):
        async for message in self.connection:
            print(f"> received {message}")
            uuid, message = self.process_uuid_message(message)
            print(f"> received {message} for {uuid}")
            await self.process_update_message(message, uuid)


class WebsocketProvider:
    def __init__(self, ydoc: Doc, websocket: Websocket, log: Logger | None = None) -> None:
        ...

    @property
    def started(self) -> Event:
        ...

    async def __aenter__(self) -> 'WebsocketProvider':
        ...

    async def __aexit__(self, exc_type, exc_value, exc_tb):
        ...

    async def _run(self):
        ...

    async def _send(self):
        ...

    async def start(self, *, task_status: TaskStatus[None] = TASK_STATUS_IGNORED):
        ...

    def stop(self):
        ...

def get_websocket_like_elva_provider(uuid: str) -> WebsocketProvider:
    class ElvaProviderSingle(ElvaProvider):
        def __init__(self, ydoc: Doc, ws: Websocket, log: Logger | None = None):
            super().__init__({uuid:ydoc}, ws)
    return ElvaProviderSingle