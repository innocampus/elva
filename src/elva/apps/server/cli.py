"""
CLI definition.
"""

import ssl
from importlib import import_module as import_
from pathlib import Path

import click

from elva.cli import common_options, pass_config_for

LOCAL_HOSTS = frozenset(["localhost", "127.0.0.1", "::1"])
"""Hostnames considered local and allowed to serve without TLS."""

APP_NAME = "server"
"""The name of the app."""


def resolve_persistence(
    ctx: click.Context, param: click.Parameter, persistent: bool | str
) -> bool:
    """
    Derive path and persistence value from the `persistent` CLI option.

    It sets an additional `path` parameter in the context.

    Arguments:
        ctx: the context of the current invokation.
        param: the option parameter object.
        persistent: the value passed from the CLI.

    Returns:
        the derive persistence flag.
    """
    match persistent:
        # no flag given
        case None:
            path = None
            persistent = False
        # flag given, but without a path
        case "":
            path = None
            persistent = True
        # anything else, i.e. a flag given with a path
        case _:
            path = Path(persistent).resolve()

            if path.exists() and not path.is_dir():
                raise click.BadArgumentUsage(
                    f"the given path '{path}' is not a directory"
                )

            persistent = True

    ctx.params["path"] = path

    return persistent


@click.command(name=APP_NAME)
@common_options
@click.option(
    "--persistent",
    # one needs to set this manually here since one cannot use
    # the keyword argument `type=click.Path(...)` as it would collide
    # with `flag_value=""`
    metavar="[DIRECTORY]",
    help=(
        "Hold the received content in a local YDoc in volatile memory "
        "or also save it under DIRECTORY if given. "
        "Without this flag, the server simply broadcasts all incoming messages "
        "within the respective room."
    ),
    # explicitely stating that the argument to this option is optional
    # see: https://github.com/pallets/click/pull/1618#issue-649167183
    is_flag=False,
    # used when no argument is given to flag
    flag_value="",
    callback=resolve_persistence,
)
@click.option(
    "--ldap",
    metavar="REALM SERVER BASE",
    help="Enable Basic Authentication via LDAP self bind.",
    nargs=3,
    type=str,
)
@click.option(
    "--dummy",
    help="Enable Dummy Basic Authentication. DO NOT USE IN PRODUCTION.",
    is_flag=True,
)
@click.option(
    "--tls-certificate",
    "tls_certificate",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Path to TLS certificate file. Required for non-localhost hosts.",
)
@click.option(
    "--tls-key",
    "tls_key",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Path to TLS private key file. Required for non-localhost hosts.",
)
@pass_config_for(APP_NAME)
def cli(config: dict, *args: tuple, **kwargs: dict):
    """
    Run a WebSocket server.
    \f

    Arguments:
        config: the merged configuration parameters from CLI and files.
        args: unused positional arguments.
        kwargs: parameters passed from the CLI.
    """
    # imports
    logging = import_("logging")
    sys = import_("sys")

    anyio = import_("anyio")

    _log = import_("elva.log")
    app = import_("elva.apps.server.app")

    # logging
    _log.LOGGER_NAME.set(__package__)
    log = logging.getLogger(__package__)

    if config.get("log") is not None:
        log_handler = logging.FileHandler(config["log"])
    else:
        log_handler = logging.StreamHandler(sys.stdout)
    log_handler.setFormatter(_log.DefaultFormatter())
    log.addHandler(log_handler)

    level_name = config.get("level") or "INFO"
    level = logging.getLevelNamesMapping()[level_name]
    log.setLevel(level)

    # validate TLS requirements for non-local hosts
    host = config.get("host", "0.0.0.0")
    tls_certificate = config.get("tls_certificate")
    tls_key = config.get("tls_key")

    if host not in LOCAL_HOSTS:
        if tls_certificate is None or tls_key is None:
            raise click.UsageError(
                f"TLS certificate and key are required for non-local host '{host}'. "
                f"Use --tls-certificate and --tls-key options, or bind to localhost."
            )

    # create TLS context if certificates are provided
    if tls_certificate is not None and tls_key is not None:
        tls_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        tls_context.load_cert_chain(tls_certificate, tls_key)
        config["tls_context"] = tls_context
        log.info(f"TLS enabled with certificate {tls_certificate}")
    elif tls_certificate is not None or tls_key is not None:
        raise click.UsageError(
            "Both --tls-certificate and --tls-key must be provided together."
        )

    # run app, catch file permission errors with an appropriate message
    try:
        anyio.run(app.main, config)
    except PermissionError as exc:
        raise click.UsageError(exc)
    except KeyboardInterrupt:
        pass
