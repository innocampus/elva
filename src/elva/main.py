"""
Module with the entry point for the `elva` command.

Subcommands are defined in the respective app package.
"""

import importlib
import json
import urllib.request
import urllib.error
from pathlib import Path

import click
import tomli_w
from setuptools import find_namespace_packages

from elva.cli import (
    common_options,
    file_paths_option_and_argument,
    pass_config,
)
from elva.core import APP_NAME, DEFAULT_HOST, DEFAULT_PORT, ELVA_APP_DIR_NAME, get_app_import_path


@click.group()
@click.version_option(prog_name=APP_NAME)
def elva():
    """
    ELVA - A suite of real-time collaboration TUI apps.
    """
    return


@elva.command
@common_options
@click.option(
    "--app",
    "app",
    metavar="APP",
    help="Include the parameters defined in the [APP] config file table.",
)
@file_paths_option_and_argument
@pass_config
def context(config: dict, *args: tuple, **kwargs: dict):
    """
    Print the parameters passed to apps and other subcommands.
    \f

    This command stringifies all parameter values for the TOML serializer.

    Arguments:
        config: mapping of merged configuration parameters from various sources.
        *args: additional positional arguments as container for passed CLI parameters.
        **kwargs: additional keyword arguments as container for passed CLI parameters.
    """
    # convert all non-string objects to strings
    if config.get("configs"):
        config["configs"] = [str(path) for path in config["configs"]]

    for param in ("file", "log", "render", "password"):
        if config.get(param):
            config[param] = str(config[param])

    click.echo(tomli_w.dumps(config))


@elva.command
@click.option(
    "--host",
    "-h",
    "host",
    default=DEFAULT_HOST,
    help=f"Host of the server to query (default: {DEFAULT_HOST}).",
)
@click.option(
    "--port",
    "-p",
    "port",
    type=click.INT,
    default=DEFAULT_PORT,
    help=f"Port of the server to query (default: {DEFAULT_PORT}).",
)
@click.option(
    "--safe/--unsafe",
    "safe",
    default=None,
    help="Use HTTPS (--safe) or HTTP (--unsafe). Default: auto-detect.",
)
def rooms(host: str, port: int, safe: bool | None):
    """
    List active rooms on a server.
    \f

    Arguments:
        host: the server hostname.
        port: the server port.
        safe: whether to use HTTPS.
    """
    # Determine protocol
    if safe is None:
        # For localhost, default to HTTP; otherwise try HTTPS first
        if host in ("localhost", "127.0.0.1", "::1"):
            protocols = ["http", "https"]
        else:
            protocols = ["https", "http"]
    elif safe:
        protocols = ["https"]
    else:
        protocols = ["http"]

    data = None
    last_error = None

    for protocol in protocols:
        url = f"{protocol}://{host}:{port}/rooms"
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                data = json.loads(response.read().decode("utf-8"))
                break
        except urllib.error.HTTPError as e:
            # HTTP error (4xx, 5xx) - don't retry with different protocol
            raise click.ClickException(f"Server error: {e.code} {e.reason}")
        except urllib.error.URLError as e:
            # Connection error - try next protocol
            last_error = e
            continue
        except json.JSONDecodeError as e:
            raise click.ClickException(f"Invalid response from server: {e}")

    if data is None:
        reason = getattr(last_error, 'reason', last_error)
        raise click.ClickException(f"Could not connect to server: {reason}")

    rooms_list = data.get("rooms", [])
    count = data.get("count", len(rooms_list))

    if count == 0:
        click.echo("No active rooms.")
    else:
        click.echo(f"Active rooms ({count}):")
        for room in rooms_list:
            identifier = room.get("identifier", "unknown")
            clients = room.get("clients", 0)
            persistent = "persistent" if room.get("persistent") else "ephemeral"
            click.echo(f"  {identifier} ({clients} client(s), {persistent})")


###
#
# import `cli` functions of apps
#
for app_name in find_namespace_packages(Path(__file__).parent / ELVA_APP_DIR_NAME):
    app = get_app_import_path(app_name)
    module = importlib.import_module(app)
    elva.add_command(module.cli)

if __name__ == "__main__":
    elva()
