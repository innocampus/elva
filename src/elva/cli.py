"""
Module providing the main command line interface functionality.
"""

import logging
import sqlite3
import tomllib
import uuid
from functools import wraps
from pathlib import Path
from typing import Any, Callable

import click
from click.core import ParameterSource
from deepmerge import always_merger

from elva.auth import Password
from elva.core import APP_NAME, CONFIG_NAME, FILE_SUFFIX, LOG_SUFFIX
from elva.store import get_metadata

#
# CONSTANTS
#

PATH_TYPE = click.Path(path_type=Path, dir_okay=False, readable=False)
"""Default type of path parameters in the CLI API."""

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
"""Logging level sorted by verbosity."""

#
# GENERAL
#


def warn(message: str):
    """
    Emit a warning to stderr.

    Arguments:
        message: the message to include in the warning.
    """
    click.echo(f"WARNING: {message}", err=True)


def get_composed_decorator(*decorators: Callable) -> Callable:
    """
    Compose a decorator out of many.

    Given keyword arguments are used to include or exclude decorators by name.

    Arguments:
        decorators: mapping of the decorator functions to their names.

    Returns:
        a decorator applying all given decorators.
    """

    def composed(f: Callable) -> Callable:
        """
        Decorator applying multiple decorators.

        Arguments:
            f: the callable to decorate.

        Returns:
            the decoratored callable `f`.
        """
        for dec in reversed(decorators):
            f = dec(f)

        return f

    return composed


#
# PATHS
#


def get_data_file_path(path: Path) -> Path:
    """
    Ensure a correct and resolved data file path.

    Arguments:
        path: the path to the data file.

    Returns:
        the correct and resolved data file path.
    """
    # resolve given path
    path = path.resolve()

    # append the ELVA data file suffix if necessary
    if FILE_SUFFIX not in path.suffixes:
        path = path.with_name(path.name + FILE_SUFFIX)

    return path


def derive_stem(path: Path, extension: None | str = None) -> Path:
    """
    Derive the data file stem.

    Arguments:
        path: the path to the data file.
        extension: the extension to add to the stem.

    Returns:
        the data file stem.
    """
    # collect all present suffixes
    suffixes = "".join(path.suffixes)

    # get the data file basename
    name = path.name.removesuffix(suffixes)

    # strip all suffixes after the data file suffix
    suffixes = suffixes.split(FILE_SUFFIX, maxsplit=1)[0]

    # translate absent extension definition
    if extension is None:
        extension = ""

    # exchange the file name
    return path.with_name(name + suffixes + extension)


def get_render_file_path(path: Path) -> Path:
    """
    Derive the render file path from the path to a data file.

    Arguments:
        path: the path to the data file.

    Returns:
        the path to the rendered file.
    """
    return derive_stem(path)


def get_log_file_path(path: Path) -> Path:
    """
    Derive the log file path from the path to a data file.

    Arguments:
        path: the path to the data file.

    Returns:
        the path to the log file.
    """
    return derive_stem(path, extension=LOG_SUFFIX)


#
# CONFIGURATION READING AND MERGING
#


def read_data_file(path: str | Path) -> dict:
    """
    Get metadata from file as parameter mapping.

    Arguments:
        path: path where the ELVA SQLite database is stored.

    Returns:
        parameter mapping stored in the ELVA SQLite database.
    """
    try:
        return get_metadata(path)
    except (
        FileNotFoundError,
        PermissionError,
        sqlite3.DatabaseError,
    ) as exc:
        warn(f"Ignoring {path}: {exc}")

        return dict()


def read_config_files(paths: list[Path]) -> tuple[list[Path], dict]:
    """
    Get parameters defined in configuration files.

    Arguments:
        paths: list of paths to ELVA configuration files.

    Returns:
        parameter mapping from all configuration files.
        The value from the highest priority configuration overwrites all other parameter values.
    """
    config = dict()

    # filter only first occurences while maintaining order with respect to highest precedence
    unique_paths = list()
    for path in paths:
        path = path.resolve()
        if path not in unique_paths:
            unique_paths.append(path)

    # read and apply each config
    checked_paths = list()

    # go in reversed order because last paths have lowest precedence
    for path in reversed(unique_paths):
        try:
            with path.open(mode="rb") as file:
                data = tomllib.load(file)
        except (
            FileNotFoundError,
            PermissionError,
            tomllib.TOMLDecodeError,
        ) as exc:
            warn(f"Ignoring {path}: {exc}")
        else:
            # perform a deep merge to merge also app tables
            config = always_merger.merge(config, data)

            # add this path to our list of successful checks
            checked_paths.append(path)

    checked_paths.reverse()

    return checked_paths, config


def merge_configs(ctx: click.Context, app: None | str = None) -> dict:
    """
    Update the user-defined parameters with parameters from files.

    Order of Precedence (from highest to lowest)

    1. CLI, explicitely given values
    2. data file metadata
    3. additional config files, first has highest precedence
    4. project config files, nearest has highest precedence
    5. app directory config file
    6. CLI defaults

    Arguments:
        ctx: object holding the parameter mapping to be updated.
        app: parameters from the same named table in the configuration files.

    Returns:
        a merged and cleaned mapping of configuration parameters to their values.
    """
    # container of merged config
    config = dict()

    # get all CLI parameters with their respective values
    cli = ctx.params.copy()

    # CLI defaults
    for name in ctx.params:
        source = ctx.get_parameter_source(name)
        if source == ParameterSource.DEFAULT or source == ParameterSource.DEFAULT_MAP:
            config[name] = cli.pop(name)

    # user home, project config files and additional config files
    paths = []
    for param in ("additional_configs", "configs"):
        paths += cli.pop(param, []) or config.pop(param, [])

    checked_paths, config_file_config = read_config_files(paths)
    config.update(config_file_config)

    # only add non-empty list of checked paths
    if checked_paths:
        config["configs"] = checked_paths

    # config defined in an app section
    if app is not None:
        app_config = config.pop(app, dict())
        config.update(app_config)

    # config defined in the metadata of an ELVA data file
    file = ctx.params.get("file")
    if file is not None:
        # derive render and log file paths if not already present
        for param, get_param_path in (
            ("render", get_render_file_path),
            ("log", get_log_file_path),
        ):
            if ctx.params.get(param) is None:
                path = get_param_path(file)
                config[param] = path

        # read in config from data file
        data_file_config = read_data_file(file)
        config.update(data_file_config)

    # merge with arguments *explicitly* given via CLI
    config.update(cli)

    # remove `None` values and unused app sections,
    # resolve paths
    for key, val in config.copy().items():
        if val is None or isinstance(val, dict):
            config.pop(key)
        elif isinstance(val, Path):
            config[key] = val.resolve()

    # complain when two pairs of writable file paths are the same
    for name_left, name_right in (
        ("file", "render"),
        ("file", "log"),
        ("render", "log"),
    ):
        path_left = config.get(name_left)
        path_right = config.get(name_right)

        if path_left is not None and path_right is not None:
            if path_left == path_right:
                raise click.BadArgumentUsage(
                    (
                        f"{name_left} path and {name_right} path "
                        f"are both set to '{path_left}'"
                    )
                )

    return config


#
# CLI CALLBACKS
#


def find_default_config_paths() -> list[Path]:
    """
    CLI default callback finding config files from highest to lowest precedence.

    It first searches project files in the current working directory and in its parents,
    then in the OS-specific app directory.

    Returns:
        a list paths to found config files, sorted by descending precedence.
    """
    paths = []

    # find project config files
    cwd = Path.cwd()

    for path in [cwd] + list(cwd.parents):
        config = path / CONFIG_NAME

        if config.exists():
            paths.append(config)

    # find user home config file
    app_dir = Path(click.get_app_dir(APP_NAME.lower()))
    app_dir_config = app_dir / CONFIG_NAME

    if app_dir_config.exists():
        paths.append(app_dir_config)

    return paths


def resolve_verbosity(
    ctx: click.Context, param: click.Parameter, value: None | int
) -> None | str:
    """
    CLI callback converting counts of verbosity flags to log level names.

    Arguments:
        ctx: the context of the current command invokation.
        param: the verbosity CLI parameter object.
        value: the value of the verbosity CLI parameter.

    Returns:
        the level name if the verbosity flag was given else `None`.
    """
    if value == 0:
        return None

    level = logging.getLevelName(LEVEL[value])

    return level


def resolve_data_file_path(
    ctx: click.Context, param: click.Parameter, path: Path
) -> None | Path:
    """
    CLI callback ensuring a correct and resolved data file path.

    Arguments:
        ctx: the context of the current command invokation.
        param: the data file CLI parameter object.
        path: the value of the data file CLI parameter.

    Returns:
        the correct and resolved data file path if given else `None`.
    """
    if path is not None:
        path = get_data_file_path(path)

    return path


#
# CLI API
#


def pass_config_for(app: None | str = None) -> Callable:
    """
    Configure the [`pass_config`][elva.cli.pass_config] decorator to respect the `app` table in configurations.

    Arguments:
        app: the name of the app table to take configuration parameters from.

    Raises:
        ValueError: if `app` is callable.

    Returns:
        the [`pass_config`][elva.cli.pass_config] decorator configured for `app`.
    """
    if callable(app):
        raise ValueError("'app' argument is not supposed to be callable")

    def pass_config(cmd: click.Command) -> Callable:
        """
        Command decorator passing the merged configuration dictionary as the first positional argument.

        Arguments:
            cmd: the command to pass the configuration to.

        Returns:
            the wrapped command.
        """

        # wrap the command to let `wrapper` look like `cmd`
        # (same name and docstring) but with altered signature
        @wraps(cmd)
        @click.pass_context
        def wrapper(ctx: click.Context, *args: tuple, **kwargs: dict) -> Any:
            """
            Command wrapper passing the merged ELVA configuration dictionary as the first positional argument.

            Arguments:
                ctx: the context of the current command invokation.
                args: positional arguments passed to the command.
                kwargs: keyword arguments passed to the command.

            Returns:
                the return value of the command.
            """
            # retrieve app either from code or CLI
            nonlocal app
            app = app or ctx.params.pop("app", None)

            # get the merged config from context
            config = merge_configs(ctx, app=app)

            # invoke the *callable* `cmd` with parameters;
            # see point 1. in https://click.palletsprojects.com/en/stable/api/#click.Context.invoke
            return ctx.invoke(cmd, config, *args, **kwargs)

        return wrapper

    return pass_config


pass_config: Callable = pass_config_for()
"""
Command decorator passing the merged configuration dictionary as the first positional argument to a [`Command`][click.Command].

Returns:
    the wrapped command.
"""


configs_option = click.option(
    "--config",
    "-c",
    "configs",
    help=(
        "Path to config file. "
        "Overwrites default config file paths. "
        "Can be specified multiple times."
    ),
    multiple=True,
    default=find_default_config_paths,
    type=PATH_TYPE,
)
"""A CLI command decorator defining an option for exclusive config file paths."""

additional_configs_option = click.option(
    "--additional-config",
    "-a",
    "additional_configs",
    help=(
        "Path to config file in addition to the default paths. "
        "Can be specified multiple times."
    ),
    multiple=True,
    type=PATH_TYPE,
)
"""A CLI command decorator defining an option for additional config file paths."""

verbosity_option = click.option(
    "--verbose",
    "-v",
    "verbose",
    help="Verbosity of logging output.",
    count=True,
    type=click.IntRange(0, 5, clamp=True),
    callback=resolve_verbosity,
)
"""A CLI command decorator defining an option for log verbosity."""

log_file_path_option = click.option(
    "--log",
    "-l",
    "log",
    help="Path to logging file.",
    type=PATH_TYPE,
)
"""A CLI command decorator defining an option for log file path."""

display_name_option = click.option(
    "--name",
    "-n",
    "name",
    help="User display username.",
)
"""A CLI command decorator defining an option for the display name."""

user_name_option = click.option(
    "--user",
    "-u",
    "user",
    help="Username for authentication.",
)
"""A CLI command decorator defining an option for a user name."""


class PasswordParameter(click.ParamType):
    name = "password"

    def convert(self, value, param, ctx):
        if value is None or isinstance(value, Password):
            return value

        if not isinstance(value, str):
            self.fail(f"{value} is of type {type(value)}, but needs to be 'str'")

        return Password(value)


password_option = click.password_option(
    "--password",
    "password",
    help="Password for authentication",
    metavar="[TEXT]",
    prompt_required=False,
    type=PasswordParameter(),
)
"""A CLI command decorator defining an option for a password."""

host_option = click.option(
    "--host",
    "-h",
    "host",
    metavar="ADDRESS",
    help="Host of the syncing server.",
)
"""A CLI command decorator defining an option for the host to connect to."""

port_option = click.option(
    "--port",
    "-p",
    "port",
    type=click.INT,
    help="Port of the syncing server.",
)
"""A CLI command decorator defining an option for the port to connect to."""

safe_option = click.option(
    "--safe/--unsafe",
    "safe",
    help="Enable or disable secure connection.",
    default=True,
)
"""A CLI command decorator defining a flag for safe or unsafe connections."""

identifier_option = click.option(
    "--identifier",
    "-i",
    "identifier",
    help="Unique identifier of the shared document.",
    default=str(uuid.uuid4()),
)
"""A CLI command decorator defining an option for the YDoc identifier."""

render_auto_save_option = click.option(
    "--auto-save/--no-auto-save",
    "auto_save",
    is_flag=True,
    default=True,
    help="Enable automatic rendering of the file contents.",
)
"""A CLI command decorator defining an option for the renderers auto save feature."""

render_timeout_option = click.option(
    "--timeout",
    "timeout",
    help="The time interval in seconds between consecutive renderings.",
    type=click.IntRange(min=0),
)
"""A CLI command decorator defining an option for the renderers auto save timeout."""

render_file_path_option = click.option(
    "--render",
    "-r",
    "render",
    help="Path to rendered file.",
    required=False,
    type=PATH_TYPE,
)
"""A CLI command decorator defining an option for the render file path."""

render_options = get_composed_decorator(
    render_file_path_option,
    render_auto_save_option,
    render_timeout_option,
)
"""A CLI command decorator defining render options."""

data_file_path_argument = click.argument(
    "file",
    required=False,
    type=PATH_TYPE,
    callback=resolve_data_file_path,
)
"""A CLI command decorator defining an argument for the data file path."""

file_paths_option_and_argument = get_composed_decorator(
    render_options,
    data_file_path_argument,
)
"""A CLI command decorator defining the render options and the data file path."""

common_options = get_composed_decorator(
    configs_option,
    additional_configs_option,
    identifier_option,
    display_name_option,
    user_name_option,
    password_option,
    host_option,
    port_option,
    safe_option,
    verbosity_option,
    log_file_path_option,
)
"""A CLI command decorator holding common CLI options."""
