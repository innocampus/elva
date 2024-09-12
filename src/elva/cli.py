import importlib
import logging
from pathlib import Path

import click
import platformdirs
from click.core import ParameterSource
from rich import print

from elva.utils import gather_context_information

###
#
# global defaults
#
# names
APP_NAME = "elva"
CONFIG_NAME = APP_NAME + ".toml"

# sort logging levels by verbosity
# source: https://docs.python.org/3/library/logging.html#logging-levels
LEVEL = [
    # no -v/--verbose flag
    # different from logging.NOTSET
    None,
    # -v
    logging.CRITICAL,
    # -vv
    logging.ERROR,
    # -vvv
    logging.WARNING,
    # -vvvv
    logging.INFO,
    # -vvvvv
    logging.DEBUG,
]


###
#
# paths
#

CONFIG_PATHS = list()

default_config_path = Path(platformdirs.user_config_dir(APP_NAME)) / CONFIG_NAME
if default_config_path.exists():
    CONFIG_PATHS.append(default_config_path)


def find_config_path():
    cwd = Path.cwd()
    for path in [cwd] + list(cwd.parents):
        config = path / CONFIG_NAME
        if config.exists():
            return config


config_path = find_config_path()

if config_path is not None:
    CONFIG_PATHS.insert(0, config_path)
    PROJECT_PATH = config_path.parent
else:
    PROJECT_PATH = None


###
#
# cli input callbacks
#


def resolve_configs(
    ctx: click.Context, param: click.Parameter, paths: None | tuple[Path]
):
    if paths is not None:
        paths = [path.resolve() for path in paths]
        param_source = ctx.get_parameter_source(param.name)
        if not param_source == ParameterSource.DEFAULT:
            paths.extend(CONFIG_PATHS)

    return paths


def resolve_log(ctx, param, log):
    if log is not None:
        log = log.resolve()

    return log


###
#
# cli interface definition
#
@click.group(
    context_settings=dict(
        ignore_unknown_options=True,
        allow_extra_args=True,
    )
)
@click.pass_context
#
# paths
#
@click.option(
    "--config",
    "-c",
    "configs",
    help="path to config file or directory",
    envvar="ELVA_CONFIG_PATH",
    multiple=True,
    show_envvar=True,
    # a list, as multiple=True
    default=CONFIG_PATHS,
    show_default=True,
    type=click.Path(path_type=Path),
    callback=resolve_configs,
)
@click.option(
    "--log",
    "-l",
    "log",
    help="path to logging file",
    type=click.Path(path_type=Path, dir_okay=False),
    callback=resolve_log,
)
# logging
@click.option(
    "--verbose",
    "-v",
    "verbose",
    help="verbosity of logging output",
    count=True,
    type=click.IntRange(0, 5, clamp=True),
)
#
# connection information
#
@click.option(
    "--user",
    "-u",
    "user",
    help="username",
)
@click.option(
    "--password",
    "-p",
    "password",
    help="password",
)
@click.option(
    "--server",
    "-s",
    "server",
    help="URI of the syncing server",
)
@click.option(
    "--identifier",
    "-i",
    "identifier",
)
@click.option(
    "--messages",
    "-m",
    "messages",
    help="protocol used to connect to the syncing server",
    envvar="ELVA_MESSAGE_TYPE",
    show_envvar=True,
    type=click.Choice(["yjs", "elva"], case_sensitive=False),
)
#
# function definition
#
def elva(
    ctx: click.Context,
    configs: Path,
    log: Path,
    verbose: int,
    user: str,
    password: str,
    server: str | None,
    identifier: str | None,
    messages: str,
):
    """ELVA - A suite of real-time collaboration TUI apps."""

    ctx.ensure_object(dict)
    c = ctx.obj

    # paths
    c["project"] = PROJECT_PATH
    c["configs"] = configs
    c["file"] = None
    c["render"] = None
    c["log"] = log

    # logging
    c["level"] = LEVEL[verbose]

    # connection
    c["user"] = user
    c["password"] = password
    c["identifier"] = identifier
    c["server"] = server
    c["messages"] = messages


###
#
# config
#
@elva.command
@click.pass_context
@click.option(
    "--file",
    "-f",
    "file",
    help="Include the parameters defined in FILE.",
    type=click.Path(path_type=Path, dir_okay=False),
)
@click.option(
    "--app",
    "-a",
    "app",
    metavar="APP",
    help="Include the parameters defined in the app.APP config file section.",
)
def context(ctx: click.Context, file: None | Path, app: None | str):
    """Print the parameters passed to apps and other subcommands."""
    c = ctx.obj

    gather_context_information(ctx, file, app)

    # sanitize password output
    if c["password"] is not None:
        c["password"] = "[REDACTED]"

    # TODO: print config in TOML syntax, so that it can be piped directly
    print(c)


###
#
# import `cli` functions of apps
#
apps = [
    ("elva.apps.editor", "edit"),
    ("elva.apps.chat", "chat"),
    ("elva.apps.server", "serve"),
    ("elva.apps.service", "service"),
]
for app, command in apps:
    module = importlib.import_module(app)
    elva.add_command(module.cli, command)

if __name__ == "__main__":
    elva()