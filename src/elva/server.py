"""
Module containing server components.
"""

import logging
import re
import socket
import ssl
from contextlib import closing
from http import HTTPStatus
from pathlib import Path
from typing import Callable, Iterable

import anyio
from pycrdt import Doc
from websockets import (
    ConnectionClosed,
    broadcast,
    serve,
)
from websockets.asyncio.server import ServerConnection
from websockets.datastructures import Headers
from websockets.http11 import Request, Response

from elva.component import Component, create_component_state
from elva.protocol import YMessage
from elva.store import SQLiteStore


def free_tcp_port(host: None | str = None) -> int:
    """
    Let the OS select a free TCP port for IPv4 addresses.

    Arguments:
        host: the interface to search a free TCP port on.

    Returns:
        a recently free tcp port.
    """
    # see https://docs.python.org/3/library/socket.html#socket-families
    if host is None:
        host = ""  # represents socket.INADDR_ANY internally

    while True:
        # call `sock.close()` on break, return or an exception;
        # use `closing` as `sock` does not support the context manager protocol
        with closing(
            socket.socket(family=socket.AF_INET, type=socket.SOCK_STREAM)
        ) as sock:
            # AF_INET address family specific address;
            # a port of `0` let the OS use its default behavior;
            # see https://docs.python.org/3/library/socket.html#socket.create_connection
            port = 0
            address = (host, port)

            # try to bind to the address
            try:
                sock.bind(address)
            except OSError:
                break

            # prevent OSError due to "address already in use" where
            # socket is in `TIME_WAIT` state; SO_REUSEADDR tells to not wait for
            # the socket timeout to expire;
            # see last example in https://docs.python.org/3/library/socket.html#example
            level = socket.SOL_SOCKET
            optname = socket.SO_REUSEADDR
            value = 1
            sock.setsockopt(level, optname, value)

            # returns `(address, port)` for AF_INET address family;
            # filter out port
            _, port = sock.getsockname()

            return port


RE_IDENTIFIER = re.compile(r"^[A-Za-z0-9\-_]{10,250}$")
"""Regular expression for a valid Y Doc identifier."""


class TLSProbeFilter(logging.Filter):
    """Filter to suppress TLS probe errors from websockets handshake failures."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Return False to suppress TLS probe noise, True otherwise."""
        # Suppress "did not receive a valid HTTP request" errors
        # These are typically from TLS probes or port scanners
        if record.levelno >= logging.ERROR:
            msg = record.getMessage()
            if "did not receive a valid HTTP request" in msg:
                return False
            if "connection closed while reading HTTP request" in msg:
                return False
            # Also check exception text (for tracebacks)
            if record.exc_text:
                if "did not receive a valid HTTP request" in record.exc_text:
                    return False
                if "connection closed while reading HTTP request" in record.exc_text:
                    return False
            # Check exc_info if exc_text not yet formatted
            if record.exc_info and record.exc_info[1]:
                exc_str = str(record.exc_info[1])
                if "did not receive a valid HTTP request" in exc_str:
                    return False
        return True


class RequestProcessor:
    """
    Collector class of HTTP request processing functions.
    """

    def __init__(self, *funcs: Iterable[Callable]):
        """
        Arguments:
            funcs: HTTP request processing functions.
        """
        self.funcs = funcs

    def process_request(
        self, websocket: ServerConnection, request: Request
    ) -> None | Response:
        """
        Process a HTTP request for given functions.

        This function is designed to be given to [`serve`][websockets.asyncio.server.serve].

        Arguments:
            websocket: connection object.
            request: HTTP request header object.

        Returns:
            `None` if no processing functions returned anything, or the first [`Response`][websockets.http11.Response] returned.
        """
        for func in self.funcs:
            out = func(websocket, request)
            if out is not None:
                return out


RoomState = create_component_state("RoomState")
"""The states of a [`Room`][elva.server.Room] component."""


class Room(Component):
    """
    Connection handler for one Y Document following the Yjs protocol.
    """

    identifier: str
    """Identifier of the synchronized Y Document."""

    persistent: bool
    """Flag whether to store received Y Document updates."""

    path: None | Path
    """Path where to save a Y Document on disk."""

    clients: set[ServerConnection]
    """Set of active connections."""

    ydoc: Doc
    """Y Document instance holding received updates."""

    store: SQLiteStore
    """Component responsible for writing received Y updates to disk."""

    def __init__(
        self,
        identifier: str,
        persistent: bool = False,
        path: None | Path = None,
    ):
        """
        If `persistent = False` and `path = None`, messages will be broadcasted only.
        Nothing is saved.

        If `persistent = True` and `path = None`, a Y Document will be present in this room, saving all incoming Y updates in there. This happens only in volatile memory.

        If `persistent = True` and `path = Path(to/some/directory)`, a Y Document will be present and its contents will be saved to disk under the given directory.
        The name of the corresponding file is derived from [`identifier`][elva.server.Room.identifier].

        Arguments:
            identifier: identifier for the used Y Document.
            persistent: flag whether to store received Y Document updates.
            path: path where to save a Y Document on disk.
        """
        self.identifier = identifier
        self.persistent = persistent

        if path is not None:
            self.path = path / f"{identifier}.y"
        else:
            self.path = None

        self.clients = set()

        if persistent:
            self.ydoc = Doc()
            if path is not None:
                self.store = SQLiteStore(self.ydoc, identifier, self.path)

    @property
    def states(self) -> RoomState:
        """The states this component can have."""
        return RoomState

    async def before(self):
        """
        Hook runnig before the `RUNNING` state is set.

        Used to start the Y Document store.
        """
        if hasattr(self, "store"):
            await self._task_group.start(self.store.start)

    async def cleanup(self):
        """
        Hook running after the component got cancelled and before it states become unset to `NONE`.

        Used to close all client connections gracefully.
        The store is closed automatically and calls its cleanup method separately.
        """
        clients = self.clients.copy()
        async with anyio.create_task_group() as tg:
            for client in clients:
                tg.start_soon(client.close)

        for client in clients:
            try:
                self.remove(client)
            except KeyError:
                pass

        self.log.info("closed all connections")

    def add(self, client: ServerConnection):
        """
        Add a client connection.

        Arguments:
            client: connection to add the list of connections.
        """
        nclients = len(self.clients)
        self.clients.add(client)
        if nclients < len(self.clients):
            self.log.info(f"added connection {id(client)}")

    def remove(self, client: ServerConnection):
        """
        Remove a client connection.

        Arguments:
            client: connection to remove from the list of connections.
        """
        self.clients.remove(client)
        self.log.info(f"removed connection {id(client)}")

    def broadcast(self, data: bytes, client: ServerConnection):
        """
        Broadcast `data` to all clients except `client`.

        Arguments:
            data: data to send.
            client: connection from which `data` came and thus to exclude from broadcasting.
        """
        # copy current state of clients and remove calling client
        clients = self.clients.copy()
        clients.remove(client)

        if clients:
            # broadcast to all other clients
            # TODO: set raise_exceptions=True and catch with ExceptionGroup
            broadcast(clients, data)
            client_ids = set(id(client) for client in clients)
            self.log.debug(f"broadcasted {data} from {id(client)} to {client_ids}")

    async def process(self, data: bytes, client: ServerConnection):
        """
        Process incoming messages from `client`.

        If `persistent = False`, just call [`broadcast(data, client)`][elva.server.Room.broadcast].

        If `persistent = True`, `data` is assumed to be a Y message and tried to be decomposed.
        On successful decomposition, actions are taken according to the [Yjs protocol spec](https://github.com/yjs/y-protocols/blob/master/PROTOCOL.md).

        Arguments:
            data: data received from `client`.
            client: connection from which `data` was received.
        """
        if self.persistent:
            # properly dispatch message
            try:
                message_type, payload, _ = YMessage.infer_and_decode(data)
            except ValueError:
                return

            match message_type:
                case YMessage.SYNC_STEP1:
                    await self.process_sync_step1(payload, client)
                case YMessage.SYNC_STEP2 | YMessage.SYNC_UPDATE:
                    await self.process_sync_update(payload, client)
                case YMessage.AWARENESS:
                    await self.process_awareness(payload, client)
        else:
            # simply forward incoming messages to all other clients
            self.broadcast(data, client)

    async def process_sync_step1(self, state: bytes, client: ServerConnection):
        """
        Process a sync step 1 payload `state` from `client`.

        Answer it with a sync step 2.
        Also, start a reactive cross-sync by answering with a sync step 1 additionally.

        Arguments:
            state: payload of the received sync step 1 message from `client`.
            client: connection from which the sync step 1 message came.
        """
        # answer with sync step 2
        update = self.ydoc.get_update(state)
        message, _ = YMessage.SYNC_STEP2.encode(update)
        await client.send(message)

        # reactive cross sync
        state = self.ydoc.get_state()
        message, _ = YMessage.SYNC_STEP1.encode(state)
        await client.send(message)

    async def process_sync_update(self, update: bytes, client: ServerConnection):
        """
        Process a sync update message payload `update` from `client`.

        Apply the update to the internal [`ydoc`][elva.server.Room.ydoc] instance and broadcast the same update to all other clients than `client`.

        Arguments:
            update: payload of the received sync update message from `client`.
            client: connection from which the sync update message came.
        """
        if update != b"\x00\x00":
            self.ydoc.apply_update(update)

            # reencode sync update message and selectively broadcast
            # to all other clients
            message, _ = YMessage.SYNC_UPDATE.encode(update)
            self.broadcast(message, client)

    async def process_awareness(self, state: bytes, client: ServerConnection):
        """
        Process an awareness message payload `state` from `client`.
        """
        message, _ = YMessage.AWARENESS.encode(state)
        self.broadcast(message, client)


WebsocketServerState = create_component_state("WebsocketServerState", ("SERVING",))
"""The states of a [`WebsocketServer`][elva.server.WebsocketServer] component."""


class WebsocketServer(Component):
    """
    Serving component using [`Room`][elva.server.Room] as internal connection handler.
    """

    host: str
    """hostname or IP address to be published at."""

    port: int
    """port to listen on."""

    persistent: bool
    """flag whether to save Y Document updates persistently."""

    path: None | Path
    """path where to store Y Document contents on disk."""

    process_request: Callable
    """callable checking the HTTP request headers on new connections."""

    rooms: dict[str, Room]
    """mapping of connection handlers to their corresponding identifiers."""

    tls_context: ssl.SSLContext | None
    """[`SSLContext`][`ssl.SSLContext`] instance for TLS connections."""

    def __init__(
        self,
        host: str,
        port: int,
        persistent: bool = False,
        path: None | Path = None,
        process_request: None | Callable = None,
        tls_context: ssl.SSLContext | None = None,
    ):
        """
        Arguments:
            host: hostname or IP address to be published at.
            port: port to listen on.
            persistent: flag whether to save Y Document updates persistently.
            path: path where to store Y Document contents on disk.
            process_request: callable checking the HTTP request headers on new connections.
            tls_context: [`SSLContext`][`ssl.SSLContext`] instance for TLS connections.
        """
        self.host = host
        self.port = port
        self.persistent = persistent
        self.path = path
        self.tls_context = tls_context

        if path is not None:
            # check whether `path` is writable, OS-agnostic
            try:
                # ensure `path` exists
                path.mkdir(parents=True, exist_ok=True)

                # try to write a test file
                test_file = path / ".permission.test"
                with test_file.open(mode="w"):
                    pass

                # remove test file
                test_file.unlink()
            except PermissionError:
                raise PermissionError(f"'{path}' is not writable") from None

        if process_request is None:
            self.process_request = self.check_path
        else:
            self.process_request = RequestProcessor(
                self.check_path, process_request
            ).process_request

        self.rooms = dict()

    @property
    def states(self) -> WebsocketServerState:
        """The states this component can have."""
        return WebsocketServerState

    async def run(self):
        """
        Hook handling incoming connections and messages.
        """
        # Configure logger to filter TLS probe noise
        conn_logger = logging.getLogger(f"{self.log.name}.ServerConnection")
        conn_logger.addFilter(TLSProbeFilter())

        async with serve(
            self.handle,
            self.host,
            self.port,
            process_request=self.process_request,
            logger=conn_logger,
            ssl=self.tls_context,
        ):
            self._change_state(self.states.NONE, self.states.SERVING)

            if self.persistent:
                if self.path is None:
                    location = "volatile memory"
                else:
                    location = self.path
                self.log.info(f"storing content in {location}")
            else:
                self.log.info("broadcast only and no content will be stored")

            # keep the server active indefinitely
            await anyio.sleep_forever()

    async def cleanup(self):
        """
        Hook running on cancellation and before the component unsets its states to `NONE`.

        It waits for all active rooms being stopped.
        """
        self._change_state(self.states.SERVING, self.states.NONE)

        async with anyio.create_task_group() as tg:
            for identifier in self.rooms:
                tg.start_soon(self.wait_for_room_closed, identifier)

    async def wait_for_room_closed(self, identifier: str):
        """
        Wait for a room corresponding to given identifier to stop.

        Arguments:
            identifier: the identifier to which the room belongs.
        """
        room = self.rooms[identifier]
        sub = room.subscribe()
        while room.states.ACTIVE in room.state:
            await sub.receive()
        room.unsubscribe(sub)

    def check_path(
        self, websocket: ServerConnection, request: Request
    ) -> None | Response:
        """
        Check if a request path is valid.

        This function is a request processing callable and automatically passed to the inner [`serve`][websockets.asyncio.server.serve] function.

        Arguments:
            websocket: connection object.
            request: HTTP request header object.

        Returns:
            `None` if an identifier was given, else a [`Response`][websockets.http11.Response] with HTTP status 403 (forbidden).
        """
        # the request path always includes a `/` as first character
        path = request.path[1:]

        if not RE_IDENTIFIER.match(path):
            if len(path) < 10:
                reason = f"Identifier too short ({len(path)} chars, need 10-250)"
            elif len(path) > 250:
                reason = f"Identifier too long ({len(path)} chars, max 250)"
            else:
                reason = "Identifier must contain only letters, numbers, hyphens, underscores"
            return Response(
                status_code=HTTPStatus.FORBIDDEN,
                headers=Headers(),
                reason_phrase=reason,
            )

    async def get_room(self, identifier: str) -> Room:
        """
        Get or create a [`Room`][elva.server.Room] via its corresponding `identifier`.

        Arguments:
            identifier: string identifiying the underlying Y Document.

        Returns:
            room to the given `identifier`.
        """
        # try to get the room for `identifier`, else create a new one
        try:
            room = self.rooms[identifier]
        except KeyError:
            room = Room(
                identifier,
                persistent=self.persistent,
                path=self.path,
            )
            self.rooms[identifier] = room

        # make sure the room is `ACTIVE`
        if room.states.ACTIVE not in room.state:
            await self._task_group.start(room.start)

        return room

    async def handle(self, websocket: ServerConnection):
        """
        Handle a `websocket` connection.

        Upon connection, a room is provided, to which the data are given for further processing.

        This methods is passed to [`serve`][websockets.asyncio.server.serve] internally.

        Arguments:
            websocket: connection from data are being received.
        """
        # use the connection path as identifier with leading `/` removed
        identifier = websocket.request.path[1:]
        room = await self.get_room(identifier)

        room.add(websocket)

        try:
            async for data in websocket:
                await room.process(data, websocket)
        except ConnectionClosed:
            self.log.info(f"closed connection {id(websocket)}")
        finally:
            room.remove(websocket)
