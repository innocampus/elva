"""
App definition.
"""

import anyio
from websockets.asyncio.server import basic_auth

from elva.auth import DummyAuth, LDAPAuth
from elva.server import WebsocketServer, free_tcp_port


async def main(config: dict):
    """
    Main app routine.

    Starts a server component and handles process signals.

    Arguments:
        config: configuration parameter mapping.
    """
    c = config

    host = c.get("host", "0.0.0.0")
    port = c.get("port") or free_tcp_port()
    persistent = c.get("persistent", False)
    path = c.get("path")
    ldap = c.get("ldap")
    dummy = c.get("dummy", False)

    if ldap is not None:
        process_request = LDAPAuth(*ldap).check
    elif dummy:
        process_request = DummyAuth().check
    else:
        process_request = None

    if process_request is not None:
        process_request = basic_auth(
            realm="ELVA WebSocket Server",
            check_credentials=process_request,
        )

    server = WebsocketServer(
        host=host,
        port=port,
        persistent=persistent,
        path=path,
        process_request=process_request,
        ssl_context=c.get("ssl_context"),
    )

    async with anyio.create_task_group() as tg:
        await tg.start(server.start)
