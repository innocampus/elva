"""
Module holding provider components.
"""

import logging
from inspect import Signature, isawaitable, signature
from typing import Any, Awaitable, Callable, Literal
from urllib.parse import urlunparse

from anyio import CancelScope, WouldBlock, create_memory_object_stream
from pycrdt import Doc, Subscription, TransactionEvent
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, WebSocketException

from elva.awareness import Awareness
from elva.component import Component, create_component_state
from elva.protocol import YMessage

WebsocketProviderState = create_component_state(
    "WebsocketProviderState", ("CONNECTED",)
)
"""The states for the [`WebsocketProvider`][elva.provider.WebsocketProvider] component."""


class WebsocketProvider(Component):
    """
    Handler for Y messages sent and received over a websocket connection.

    This component follows the [Yjs protocol spec](https://github.com/yjs/y-protocols/blob/master/PROTOCOL.md).
    """

    ydoc: Doc
    """Instance of the synchronized Y Document."""

    awareness: Awareness
    """Instance of the awareness states."""

    options: dict
    """Mapping of arguments to the signature of [`connect`][websockets.asyncio.client.connect]."""

    basic_authorization_header: dict
    """Mapping of `Authorization` HTTP request header to encoded `Basic Authentication` information."""

    tried_credentials: bool
    """Flag whether given credentials have already been tried."""

    on_exception: Callable | Awaitable | None
    """Callback to which the current connection exception and a reference to the connection option mapping is given."""

    _signature: Signature
    """Object holding the positional and keyword arguments for [`connect`][websockets.asyncio.client.connect]."""

    _ydoc_subscription: Subscription
    """(while running) Object holding subscription information to changes in [`ydoc`][elva.provider.WebsocketProvider.ydoc]."""

    _awareness_subscription: str
    """(while running) Identifier for the callback to which changes in [`awareness`][elva.provider.WebsocketProvider.awareness] are sent to ."""

    def __init__(
        self,
        ydoc: Doc,
        identifier: str,
        host: str,
        *args: tuple[Any],
        port: int = None,
        safe: bool = True,
        on_exception: Awaitable | None = None,
        **kwargs: dict[Any],
    ):
        """
        Arguments:
            ydoc: instance if the synchronized Y Document.
            identifier: identifier of the synchronized Y Document.
            host: hostname or IP address of the Y Document synchronizing websocket server.
            port: port of the Y Document synchronizing websocket server.
            safe: flag whether to establish a secured (`True`) or unsecured (`False`) connection.
            on_exception: callback to which the current connection exception and a reference to the connection option mapping is given.
            *args: positional arguments passed to [`connect`][websockets.asyncio.client.connect].
            **kwargs: keyword arguments passed to [`connect`][websockets.asyncio.client.connect].
        """
        self.ydoc = ydoc
        self.awareness = Awareness(ydoc)
        self.awareness.log = logging.getLogger(f"{self.log.name}.Awareness")

        # construct URI
        scheme = "wss" if safe else "ws"
        netloc = f"{host}:{port}" if port is not None else host

        # scheme, netloc, url, params, query, fragment
        uri = urlunparse((scheme, netloc, identifier, None, None, None))
        self.uri = uri

        # construct a dictionary of args and kwargs
        kwargs.setdefault(
            "logger", logging.getLogger(f"{self.log.name}.ClientConnection")
        )
        self._signature = signature(connect).bind(uri, *args, **kwargs)
        self.options = self._signature.arguments

        # callable attribute
        self.on_exception = on_exception

        # buffer for messages to send
        self._buffer_in, self._buffer_out = create_memory_object_stream(
            max_buffer_size=65536
        )

    @property
    def states(self) -> WebsocketProviderState:
        """
        The states the websocket provider can have.
        """
        return WebsocketProviderState

    async def _connect(self):
        """
        Hook running the main connection loop in a shielded cancel scope.
        """
        # accepts only 101 and 3xx HTTP status codes,
        # retries only on 5xx by default
        async for self._connection in connect(
            *self._signature.args, **self._signature.kwargs
        ):
            self.log.info(f"opened connection to {self.uri}")

            # add `CONNECTED` state
            self._change_state(self.states.NONE, self.states.CONNECTED)

            # subscribe to changes in YDoc and Awareness, so that those callbacks
            # can put messages into the send buffer
            self._ydoc_subscription = self.ydoc.observe(self._on_transaction_event)
            self._awareness_subscription = self.awareness.observe(
                self._on_awareness_change
            )

            # perform the cross sync
            self._task_group.start_soon(self._on_connect)

            # immediately refresh the clock on the own local state, thereby
            # triggering the awareness callback and sending an update message
            self.awareness.set_local_state(self.awareness.get_local_state())

            # wait for incoming messages;
            # stops on (ab)normally closed connection
            # or when the CancelScope was cancelled
            await self._recv()

            #
            # the following part is only reached on (ab)normally closed connection,
            # i.e. when the CancelScope has NOT been cancelled
            #

            self.log.info(f"closed connection to {self.uri}")

            # remove `CONNECTED` state
            self._change_state(self.states.CONNECTED, self.states.NONE)

            # remove reference to closed connection; we need a new one anyways
            del self._connection

            # remove subscriptions as no updates can be sent on a closed connection
            self.ydoc.unobserve(self._ydoc_subscription)
            del self._ydoc_subscription

            self.awareness.unobserve(self._awareness_subscription)
            del self._awareness_subscription

    async def _handle_connection(self):
        """
        Hook connecting and listening for incoming data.

        It retries on HTTP response status codes `3xx` and `5xx` automatically
        or gives the opportunity to update the connection options with
        credentials via the [`on_exception`][elva.provider.WebsocketProvider.on_exception] hook.
        """
        # catch exceptions due to HTTP status codes other than 101, 3xx, 5xx
        with CancelScope(shield=True) as self._connection_scope:
            self.log.debug("handling connection")

            # a new connection loop needs to be started for every change
            # in connection options
            while True:
                try:
                    await self._connect()
                # give every possible exception not catched by `connect`s
                # `process_exception` another chance
                except WebSocketException as exc:
                    await self._on_exception(exc)

    async def _on_exception(self, exc: WebSocketException):
        """
        Wrapper method around the [`on_exception`][elva.provider.WebsocketProvider.on_exception] attribute.

        If `on_exception` was not given, it defaults to re-raising `exc`.

        Arguments:
            exc: exception raised by [`connect`][websockets.asyncio.client.connect].
        """
        if self.on_exception is not None:
            # res is either `None` or an awaitable yielding `None`
            res = self.on_exception(exc, self.options)

            if isawaitable(res):
                await res
        else:
            # unhandled connection exceptions should be fatal
            raise exc

    async def before(self):
        """
        Hook subscribing to changes in the Y Document and starting the Awareness component.
        """
        # wait for messages to send
        self._task_group.start_soon(self._send)

        # start the Awareness component
        await self._task_group.start(self.awareness.start)

    async def run(self):
        """
        Hook starting the connection loop as task.
        """
        # the connection loop is run as task, so this method returns right away
        # and the `cleanup` coroutine can be reached on cancellation.
        self._task_group.start_soon(self._handle_connection)

    async def cleanup(self):
        """
        Hook cancelling the subscriptions to changes in [`ydoc`][elva.provider.WebsocketProvider.ydoc] and [`awareness`][elva.provider.WebsocketProvider.awareness],
        draining the buffer, sending the last messages and
        closing the websocket connection gracefully.
        """
        # we might have no `_ydoc_subscription` anymore
        # when this component was cancelled while we had no active connection
        if hasattr(self, "_ydoc_subscription"):
            self.ydoc.unobserve(self._ydoc_subscription)
            del self._ydoc_subscription

        # wait for the Awareness component to stop and thereby
        # for the awareness disconnect message to be sent
        sub = self.awareness.subscribe()
        while self.awareness.states.ACTIVE in self.awareness.state:
            await sub.receive()
        self.awareness.unsubscribe(sub)

        # there might be no `_awareness_subscription` anymore
        # when this component was cancelled while we had no active connection
        if hasattr(self, "_awareness_subscription"):
            self.awareness.unobserve(self._awareness_subscription)
            del self._awareness_subscription

        # drain the buffer while no new messages are queued,
        # since subscriptions to YDoc and Awareness are cancelled at this point
        while True:
            try:
                message = self._buffer_out.receive_nowait()
            except WouldBlock:
                self.log.debug("drained the buffer")

                # cancel the connection loop
                self._connection_scope.cancel()
                del self._connection_scope
                self.log.debug("cancelled connection scope")

                break
            else:
                # same as hasattr(self, "_connection")
                if self.states.CONNECTED in self.state:
                    await self._connection.send(message)
                    self.log.debug(f"sent message {message}")

        # same as hasattr(self, "_connection")
        if self.states.CONNECTED in self.state:
            await self._connection.close()
            del self._connection
            self.log.info(f"closed connection to {self.uri}")

    async def _send(self):
        """
        Hook listening for messages on the internal buffer
        and sending them.
        """
        self.log.info("listening for outgoing data")
        try:
            async for message in self._buffer_out:
                await self._connection.send(message)
                self.log.debug(f"sent message {message}")
        except ConnectionClosed:
            pass

    async def _recv(self):
        """
        Hook listening for incoming messages on the websocket connection
        and processing them.
        """
        self.log.info("listening for incoming data")
        try:
            async for data in self._connection:
                self.log.debug(f"received data {data}")
                await self._on_recv(data)
        except ConnectionClosed:
            pass

    def _on_transaction_event(self, event: TransactionEvent):
        """
        Hook called on changes in [`ydoc`][elva.provider.WebsocketProvider.ydoc].

        When called, the `event` data are encoded as Y update message and sent over the established websocket connection.

        Arguments:
            event: object holding event information.
        """
        if event.update != b"\x00\x00":
            message, _ = YMessage.SYNC_UPDATE.encode(event.update)
            self._buffer_in.send_nowait(message)
            self.log.debug("queued YDoc update")

    def _on_awareness_change(
        self, topic: Literal["update", "change"], change: tuple[dict, str]
    ):
        """
        Hook called on changes in [`awareness`][elva.provider.WebsocketProvider.awareness].

        When called, updates from origin `local` are encoded as [`AWARENESS`][elva.protocol.YMessage.AWARENESS] update message.
        Messages from every other origin are ignored, as they came from remote and were already applied.

        Arguments:
            topic: The categorization of the awareness state change, either `"update"` for all updates, even only renewals, or `"change"` for changes in the state itself.
            change: a tuple of actions (`"added"`, `"updated"`, `"removed"`) and the origin of the awareness state change.
        """
        actions, origin = change

        # only encode data on `update` topic and `local` origin,
        # all other ones are either doubled under the `change` topic or
        # applied updates from remote
        #
        # the `update` topic includes the `change` topic;
        # `local` origin is hardcoded in `pycrdt._awareness` module
        if topic == "update" and origin == "local":
            # include all mentioned clients in the update message
            client_ids = actions["added"] + actions["updated"] + actions["removed"]

            # encode the awareness update message
            payload = self.awareness.encode_awareness_update(client_ids)
            message, _ = YMessage.AWARENESS.encode(payload)

            # send the awareness update message
            self._buffer_in.send_nowait(message)

            # log awareness disconnect message separately
            if self.awareness.get_local_state() is None:
                self.log.debug("queued disconnect awareness update")
            else:
                self.log.debug("queued awareness update")

    async def _on_connect(self):
        """
        Hook initializing cross synchronization.

        When called, it sends a Y sync step 1 message and a Y sync step 2 message with respect to the null state, effectively doing a pro-active cross synchronization.
        """
        # init sync
        state = self.ydoc.get_state()
        step1, _ = YMessage.SYNC_STEP1.encode(state)
        await self._buffer_in.send(step1)
        self.log.debug("queued sync step 1")

        # proactive cross sync
        update = self.ydoc.get_update(b"\x00")
        step2, _ = YMessage.SYNC_STEP2.encode(update)
        await self._buffer_in.send(step2)
        self.log.debug("queued proactive sync step 2")

    async def _on_recv(self, data: bytes):
        """
        Hook called on received `data` over the websocket connection.

        When called, `data` is assumed to be a [`YMessage`][elva.protocol.YMessage] and tried to be decoded.
        On successful decoding, the payload is dispatched to the appropriate method.

        Arguments:
            data: message received from the synchronizing server.
        """
        try:
            message_type, payload, _ = YMessage.infer_and_decode(data)
        except Exception as exc:
            self.log.debug(f"failed to infer message: {exc}")
            return

        match message_type:
            case YMessage.SYNC_STEP1:
                await self._on_sync_step1(payload)
            case YMessage.SYNC_STEP2 | YMessage.SYNC_UPDATE:
                await self._on_sync_update(payload)
            case YMessage.AWARENESS:
                await self._on_awareness(payload)
            case _:
                self.log.warning(
                    f"message type '{message_type}' does not match any YMessage"
                )

    async def _on_sync_step1(self, state: bytes):
        """
        Dispatch method called on received Y sync step 1 message.

        It answers the message with a Y sync step 2 message according to the [Yjs protocol spec](https://github.com/yjs/y-protocols/blob/master/PROTOCOL.md).

        Arguments:
            state: payload included in the incoming Y sync step 1 message.
        """
        # answer to sync step 1
        update = self.ydoc.get_update(state)
        step2, _ = YMessage.SYNC_STEP2.encode(update)
        await self._buffer_in.send(step2)
        self.log.debug("queued sync step 2")

    async def _on_sync_update(self, update: bytes):
        """
        Dispatch method called on received Y sync update message.

        The `update` gets applied to the internal Y Document instance.

        Arguments:
            update: payload included in the incoming Y sync update message.
        """
        if update != b"\x00\x00":
            self.ydoc.apply_update(update)
            self.log.debug("applied YDoc update")

    async def _on_awareness(self, state: bytes):
        """
        Dispatch method called on received Y awareness message.

        Currently, this is defined as a no-op.

        Arguments:
            state: payload included in the incoming Y awareness message.
        """
        # mark these updates coming from `remote` origin
        self.awareness.apply_awareness_update(state, origin="remote")
        self.log.debug("applied awareness update")
