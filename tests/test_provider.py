import logging
import uuid

import anyio
import pytest
from pycrdt import Doc, Text
from websockets.asyncio.server import basic_auth
from websockets.exceptions import InvalidStatus

from elva.auth import DummyAuth, basic_authorization_header
from elva.log import LOGGER_NAME
from elva.provider import WebsocketProvider
from elva.server import WebsocketServer


@pytest.fixture(scope="module")
def manage_logger_name():
    reset_token = LOGGER_NAME.set(__name__)
    yield
    LOGGER_NAME.reset(reset_token)


log = logging.getLogger(__name__)

pytestmark = pytest.mark.anyio


# `websockets` runs only on `asyncio`, thus the `trio` backend of `anyio` fails
@pytest.fixture(scope="module")
def anyio_backend():
    return "asyncio"


LOCALHOST = "127.0.0.1"


def get_identifier():
    return str(uuid.uuid4())


def ydoc_updates_are_empty(ydoc_a, ydoc_b):
    update_a = ydoc_a.get_update(ydoc_b.get_state())
    update_b = ydoc_b.get_update(ydoc_a.get_state())

    is_equal = update_a == update_b
    is_empty = update_a == b"\x00\x00" and update_b == b"\x00\x00"

    return is_equal and is_empty


async def test_connect(free_tcp_port, tmp_path):
    """A provider connects to a server and the server spawns a room."""
    # setup local YDoc
    ydoc = Doc()

    # setup connection details
    identifier = get_identifier()

    # run the server
    async with WebsocketServer(
        LOCALHOST, free_tcp_port, persistent=True, path=tmp_path
    ) as server:
        # run the provider
        async with WebsocketProvider(
            ydoc, identifier, LOCALHOST, port=free_tcp_port,
        ) as provider:
            # wait for the provider to be connected
            sub_provider = provider.subscribe()
            while provider.states.CONNECTED not in provider.state:
                await sub_provider.receive()
            provider.unsubscribe(sub_provider)

            # the server spawned a room
            assert identifier in server.rooms
            room = server.rooms[identifier]
            assert room.states.ACTIVE in room.state

            # wait for the room to run
            sub_room = room.subscribe()
            while room.states.RUNNING not in room.state:
                await sub_room.receive()
            room.unsubscribe(sub_room)

            # the room has started a file store
            assert hasattr(room, "store")
            store = room.store
            assert store.states.ACTIVE in store.state
            assert store.states.RUNNING in store.state


async def test_multiple_connect_no_history(free_tcp_port):
    """Two providers sync with each other on some changes after being connected."""
    # setup local YDocs
    ydoc_a = Doc()
    ydoc_a["text"] = text_a = Text()

    ydoc_b = Doc()
    ydoc_b["text"] = Text()

    # setup connection details
    identifier = get_identifier()

    # run the server
    async with WebsocketServer(LOCALHOST, free_tcp_port, persistent=False) as server:
        # run the providers
        async with (
            WebsocketProvider(
                ydoc_a, identifier, LOCALHOST, port=free_tcp_port,
            ) as provider_a,
            WebsocketProvider(
                ydoc_b, identifier, LOCALHOST, port=free_tcp_port,
            ) as provider_b,
        ):
            # the YDocs contain both nothing
            assert ydoc_a.get_state() == ydoc_b.get_state() == b"\x00"

            # wait for each provider to be connected to the server
            for provider in (provider_a, provider_b):
                sub = provider.subscribe()
                while provider.states.CONNECTED not in provider.state:
                    await sub.receive()
                provider.unsubscribe(sub)

            # check that we serve indeed our clients
            assert len(server.rooms) == 1
            assert identifier in server.rooms
            room = server.rooms[identifier]
            assert len(room.clients) == 2

            # still nothing in the YDocs
            assert ydoc_a.get_state() == ydoc_b.get_state() == b"\x00"

            # now change something in `provider_a`
            text_a += "this is going from `provider_a` to `provider_b`"

            # both YDocs have different contents
            assert ydoc_a.get_state() != b"\x00"

            # wait for the YDocs to be in sync again
            while not ydoc_updates_are_empty(ydoc_a, ydoc_b):
                await anyio.sleep(1e-6)

            # both YDocs hold the same content now
            assert ydoc_b.get_state() != b"\x00"
            assert str(ydoc_a["text"]) == str(ydoc_b["text"])


async def test_multiple_connect_divergent_history(free_tcp_port):
    """Two providers sync their divergent histories with each other on connect."""
    # setup local YDocs
    content_a = r"a few words by `a`\n"
    ydoc_a = Doc()
    ydoc_a["text"] = Text(content_a)

    content_b = r"some more from `b`\n"
    ydoc_b = Doc()
    ydoc_b["text"] = Text(content_b)

    # setup connection details
    identifier = get_identifier()

    # run the server
    async with WebsocketServer(LOCALHOST, free_tcp_port, persistent=False) as server:
        # run the providers
        async with (
            WebsocketProvider(
                ydoc_a, identifier, LOCALHOST, port=free_tcp_port,
            ) as provider_a,
            WebsocketProvider(
                ydoc_b, identifier, LOCALHOST, port=free_tcp_port,
            ) as provider_b,
        ):
            # the YDocs hold some differing content
            assert ydoc_a.get_state() != b"\x00"
            assert ydoc_b.get_state() != b"\x00"

            # wait for each provider to be connected to the server
            for provider in (provider_a, provider_b):
                sub = provider.subscribe()
                while provider.states.CONNECTED not in provider.state:
                    await sub.receive()
                provider.unsubscribe(sub)

            # check that we serve indeed our clients
            assert len(server.rooms) == 1
            assert identifier in server.rooms
            room = server.rooms[identifier]
            assert len(room.clients) == 2

            # wait for the YDocs to sync
            while not ydoc_updates_are_empty(ydoc_a, ydoc_b):
                await anyio.sleep(1e-6)

            # we have identical content as the union of our divergent histories
            assert str(ydoc_a["text"]) == str(ydoc_b["text"])
            assert content_a in str(ydoc_a["text"])
            assert content_a in str(ydoc_b["text"])
            assert content_b in str(ydoc_b["text"])
            assert content_b in str(ydoc_a["text"])


async def test_manual_reconnect(free_tcp_port):
    """A provider can be stopped and started in sequence."""
    # setup local YDoc
    ydoc = Doc()
    ydoc["text"] = Text("foo bar baz")

    # setup connection details
    identifier = get_identifier()

    async with WebsocketServer(LOCALHOST, free_tcp_port, persistent=True) as server:
        provider = WebsocketProvider(
            ydoc, identifier, LOCALHOST, port=free_tcp_port,
        )
        sub = provider.subscribe()
        async with anyio.create_task_group() as tg:
            # connect a couple of times
            for _ in range(2):
                # start the provider as task
                await tg.start(provider.start)

                # the provider is now running
                assert provider.states.RUNNING in provider.state

                # wait for it to be connected
                while provider.states.CONNECTED not in provider.state:
                    await sub.receive()

                # we are now connected
                assert provider.states.CONNECTED in provider.state
                assert len(server.rooms) == 1
                assert identifier in server.rooms
                room = server.rooms[identifier]

                # wait for the ydoc states to get synced
                while not ydoc_updates_are_empty(ydoc, room.ydoc):
                    await anyio.sleep(1e-6)

                # stop the provider
                await provider.stop()

                # wait for the connection to end
                while provider.states.CONNECTED in provider.state:
                    await sub.receive()

                # the provider is neither `ACTIVE` nor `RUNNING` nor `CONNECTED` anymore
                assert provider.state == provider.states.NONE


async def test_auto_reconnect(free_tcp_port):
    """A provider retries to connect automatically when the connection was closed remotely."""
    # setup local YDoc
    ydoc = Doc()
    identifier = get_identifier()

    # subscribe to both provider and server state changes
    provider = WebsocketProvider(
        ydoc, identifier, LOCALHOST, port=free_tcp_port,
    )
    sub_provider = provider.subscribe()

    server = WebsocketServer(LOCALHOST, free_tcp_port, persistent=True)
    sub_server = server.subscribe()

    # run the provider
    async with provider:
        async with anyio.create_task_group() as tg:
            # run a connect and disconnect cycle a couple if times
            for _ in range(2):
                # start the server as task
                await tg.start(server.start)

                # the server is really `RUNNING`
                assert server.states.RUNNING in server.state

                # wait for the provider to retry and connect;
                while provider.states.CONNECTED not in provider.state:
                    await sub_provider.receive()

                # our connection causes a room to be present
                assert len(server.rooms) == 1
                assert identifier in server.rooms
                room = server.rooms[identifier]

                # the room we connected to is `RUNNING`
                assert room.states.RUNNING in room.state

                # stop the server, simulate connection loss
                await server.stop()

                # wait for the server to stop
                while server.state != server.states.NONE:
                    await sub_server.receive()

                assert server.states.ACTIVE not in server.state

                # wait for the provider to recognize the closed connection
                while provider.states.CONNECTED in provider.state:
                    await sub_provider.receive()

                # provider is still `RUNNING`, but not `CONNECTED` anymore,
                # so it handled the closed connection gracefully and retries now again
                assert provider.states.CONNECTED not in provider.state
                assert provider.states.RUNNING in provider.state


async def test_synchronization_from_provider_to_server(free_tcp_port):
    """The server recreates the YDoc state remotely after the provider connected."""
    # setup local YDoc
    ydoc = Doc()
    ydoc["text"] = Text("some local content")

    # we have some history stored in our local YDoc
    assert ydoc.get_state() != b"\x00"

    # setup connection details
    identifier = get_identifier()

    # run both the server and the provider
    async with (
        WebsocketServer(LOCALHOST, free_tcp_port, persistent=True) as server,
        WebsocketProvider(
            ydoc, identifier, LOCALHOST, port=free_tcp_port,
        ) as provider,
    ):
        # wait for the provider to be connected
        sub = provider.subscribe()
        while provider.states.CONNECTED not in provider.state:
            await sub.receive()

        # the server creates a room for us
        assert len(server.rooms) == 1
        assert identifier in server.rooms
        room = server.rooms[identifier]

        # the room is running
        assert room.states.RUNNING in room.state

        # the remote YDoc is not synced yet
        assert room.ydoc.get_state() == b"\x00"

        # wait for the YDocs to get synced, i.e. produced updates are empty
        while not ydoc_updates_are_empty(ydoc, room.ydoc):
            await anyio.sleep(1e-6)

        # now both local and remote YDoc are in the same state
        assert room.ydoc != b"\x00"


async def test_synchronization_from_server_to_provider(free_tcp_port):
    """The provider recreates the remote YDoc state locally on connection."""
    # setup local YDoc
    ydoc = Doc()
    assert ydoc.get_state() == b"\x00"

    # setup connection details
    identifier = get_identifier()

    # run the server
    async with WebsocketServer(LOCALHOST, free_tcp_port, persistent=True) as server:
        # simulate present remote content
        room = await server.get_room(identifier)

        # there is no remote content
        assert room.ydoc.get_state() == b"\x00"

        # now there is remote content
        room.ydoc["text"] = Text("a bit of remote content already present")
        assert room.ydoc.get_state() != b"\x00"

        # run the provider
        async with WebsocketProvider(
            ydoc, identifier, LOCALHOST, port=free_tcp_port,
        ) as provider:
            # wait for the provider to be connected
            sub = provider.subscribe()
            while provider.states.CONNECTED not in provider.state:
                await sub.receive()

            # the provider is connected now
            assert provider.states.CONNECTED in provider.state

            # wait for the YDocs to sync state
            while not ydoc_updates_are_empty(ydoc, room.ydoc):
                await anyio.sleep(1e-6)


async def test_bidirectional_synchronization(free_tcp_port):
    """The provider and the server sync their divergent hostories."""
    # setup local YDoc
    content_local = "my important document locally"
    ydoc = Doc()
    ydoc["text"] = Text(content_local)

    # setup connection details
    identifier = get_identifier()

    # run the server
    async with WebsocketServer(LOCALHOST, free_tcp_port, persistent=True) as server:
        # simulate present remote content
        room = await server.get_room(identifier)

        # there is nothing in the remote YDoc
        assert room.ydoc.get_state() == b"\x00"

        # now there is some remote content
        content_remote = "also important stuff on server"
        room.ydoc["text"] = Text(content_remote)
        assert room.ydoc.get_state() != b"\x00"

        # run the provider
        async with WebsocketProvider(
            ydoc, identifier, LOCALHOST, port=free_tcp_port,
        ) as provider:
            # wait for the provider to be connected
            sub = provider.subscribe()
            while provider.states.CONNECTED not in provider.state:
                await sub.receive()

            # the provider is connected now
            assert provider.states.CONNECTED in provider.state

            # wait for the YDoc states to get synced
            while not ydoc_updates_are_empty(ydoc, room.ydoc):
                await anyio.sleep(1e-6)

            # both local and remote YTexts show identical content
            assert str(ydoc["text"]) == str(room.ydoc["text"])

            # local and remote content is present in both local and remote YTexts
            assert content_local in str(ydoc["text"])
            assert content_local in str(room.ydoc["text"])
            assert content_remote in str(ydoc["text"])
            assert content_remote in str(room.ydoc["text"])


def on_invalid_status(exc, options: dict):
    """Callback altering the connection options on InvalidStatus exceptions."""
    assert isinstance(exc, InvalidStatus)
    assert exc.response.status_code == 401  # UNAUTHORIZED

    username = "for-dummy-auth"
    password = "for-dummy-auth"
    headers = basic_authorization_header(username, password)

    options["additional_headers"] = headers


async def test_auth(free_tcp_port):
    """Connection exceptions can be handled with the `on_exception` callback."""
    # required YDoc
    ydoc = Doc()

    # use dummy auth for testing
    auth = DummyAuth()

    # setup connection details
    identifier = get_identifier()

    # run a server with a dummy basic auth check
    async with WebsocketServer(
        LOCALHOST,
        free_tcp_port,
        process_request=basic_auth(
            realm="test server",
            check_credentials=auth.check,
        ),
    ) as server:
        # no authorization header raises InvalidStatus exception
        with pytest.raises(ExceptionGroup) as excinfo:
            async with WebsocketProvider(
                ydoc, identifier, LOCALHOST, port=free_tcp_port,
            ):
                await anyio.sleep_forever()

        # we got indeed a 401 InvalidStatus
        exc_group = excinfo.value
        excs = exc_group.exceptions
        assert isinstance(excs, tuple)
        assert len(excs) == 1
        exc = excs[0]
        assert isinstance(exc, InvalidStatus)
        assert exc.response.status_code == 401  # UNAUTHORIZED

        # no room was created
        assert identifier not in server.rooms

        # the `on_exception` callback alters the connection options
        # by adding the `Authorization` Basic Auth header
        async with WebsocketProvider(
            ydoc,
            identifier,
            LOCALHOST,
            port=free_tcp_port,
            on_exception=on_invalid_status,
        ) as provider:
            assert provider.states.RUNNING in provider.state

            assert "additional_headers" not in provider.options

            sub = provider.subscribe()
            while provider.states.CONNECTED not in provider.state:
                await sub.receive()
            provider.unsubscribe(sub)

            assert "additional_headers" in provider.options
            headers = provider.options["additional_headers"]
            assert "Authorization" in headers
