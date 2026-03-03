"""
Definition of library constants.
"""

APP_NAME = "ELVA"
"""Default app name."""

CONFIG_NAME = APP_NAME.lower() + ".toml"
"""Default ELVA configuration file name."""

FILE_SUFFIX = ".y"
"""Default ELVA data file suffix."""

LOG_SUFFIX = ".log"
"""Default log file suffix."""

ELVA_APP_DIR_NAME = "apps"
"""Directory name where app namespace packages are searched for."""


def get_app_import_path(app: str) -> str:
    """
    Get the Python import path for an app.

    Arguments:
        app: the app namespace package name.

    Returns:
        the import path of an app namespace package.
    """
    return f"elva.{ELVA_APP_DIR_NAME}.{app}"


ELVA_WIDGET_DIR_NAME = "widgets"
"""Directory name where widget namespace packages are expected."""

LOCAL_HOSTS = frozenset(["localhost", "127.0.0.1", "::1"])
"""Hostnames considered local and allowed to serve without TLS."""
