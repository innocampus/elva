"""
Definition of library constants.
"""

# App name
APP_NAME = "ELVA"

# Default port for server and client connections
DEFAULT_PORT = 7654

# Default host for client connections
DEFAULT_HOST = "localhost"

# Default configuration file name
CONFIG_NAME = APP_NAME.lower() + ".toml"

# Default data file suffix
FILE_SUFFIX = ".y"

# Default log file suffix
LOG_SUFFIX = ".log"

# Directory name where app namespace packages are searched for
ELVA_APP_DIR_NAME = "apps"

# Directory name where widget namespace packages are expected
ELVA_WIDGET_DIR_NAME = "widgets"


def get_app_import_path(app: str) -> str:
    """
    Get the Python import path for an app.

    Arguments:
        app: the app namespace package name.

    Returns:
        the import path of an app namespace package.
    """
    return f"elva.{ELVA_APP_DIR_NAME}.{app}"
