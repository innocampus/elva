"""
App definition.
"""

import logging
from pathlib import Path
from typing import Any, Literal

from pycrdt import Doc, Text
from textual.app import App
from textual.binding import Binding
from textual.widgets import Footer, Header
from websockets.exceptions import InvalidStatus, WebSocketException

from elva.cli import get_data_file_path, get_render_file_path
from elva.component import Component, ComponentState
from elva.core import FILE_SUFFIX
from elva.provider import WebsocketProvider
from elva.renderer import TextRenderer
from elva.store import SQLiteStore
from elva.widgets.awareness import AwarenessView
from elva.widgets.config import ConfigView
from elva.widgets.screens import Dashboard, ErrorScreen, InputScreen
from elva.widgets.ytextarea import YTextArea

log = logging.getLogger(__package__)

LANGUAGES = {
    "py": "python",
    "md": "markdown",
    "sh": "bash",
    "js": "javascript",
    "rs": "rust",
    "yml": "yaml",
}
"""Supported languages."""


class UI(App):
    """
    User interface.
    """

    CSS_PATH = "style.tcss"
    """The path to the default CSS."""

    SCREENS = {
        "dashboard": Dashboard,
        "input": InputScreen,
    }
    """The installed screens."""

    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit"),
        Binding("ctrl+b", "toggle_dashboard", "Dashboard"),
        Binding("ctrl+s", "render", "Save Document"),
        Binding("ctrl+shift+s", "save", "Save Yjs", key_display="^S"),
    ]
    """Key bindings for actions of the app."""

    def __init__(self, config: dict):
        """
        Arguments:
            config: mapping of configuration parameters to their values.
        """
        self.config = c = config

        ansi_color = c.get("ansi_color", False)
        super().__init__(ansi_color=ansi_color)

        # Build title for header
        host = c.get("host")
        port = c.get("port")
        identifier = c.get("identifier", "")
        if host and identifier:
            if port:
                self.title = f"{host}:{port}/{identifier}"
            else:
                self.title = f"{host}/{identifier}"
        elif identifier:
            self.title = identifier
        else:
            self.title = "Elva"

        # document structure
        self.ydoc = Doc()
        self.ytext = Text()
        self.ydoc["ytext"] = self.ytext

        self.components = list()

        if c.get("host") is not None:
            self.provider = WebsocketProvider(
                self.ydoc,
                c["identifier"],
                c["host"],
                port=c.get("port"),
                safe=c.get("safe"),
                on_exception=self.on_provider_exception,
            )

            data = {}
            if c.get("name") is not None:
                data = {"user": {"name": c["name"]}}

            self.provider.awareness.set_local_state(data)

            self.components.append(self.provider)

        if c.get("file") is not None:
            self.store = SQLiteStore(
                self.ydoc,
                c["identifier"],
                c["file"],
            )
            self.components.append(self.store)

        if c.get("render") is not None:
            self.renderer = TextRenderer(
                self.ytext,
                c["render"],
                c.get("auto_save", False),
                c.get("timeout", 300),
            )
            self.components.append(self.renderer)

        self._language = c.get("language")

    def on_provider_exception(self, exc: WebSocketException, config: dict):
        """
        Wrapper method around the provider exception handler
        [`_on_provider_exception`][elva.apps.editor.app.UI._on_provider_exception].

        Arguments:
            exc: the exception raised by the provider.
            config: the configuration stored in the provider.
        """
        self.run_worker(self._on_provider_exception(exc, config))

    async def _on_provider_exception(self, exc: WebSocketException, config: dict):
        """
        Handler for exceptions raised by the provider.

        It exits the app after displaying the error message to the user.

        Arguments:
            exc: the exception raised by the provider.
            config: the configuration stored in the provider.
        """
        await self.provider.stop()

        if type(exc) is InvalidStatus:
            response = exc.response
            exc = f"HTTP {response.status_code}: {response.reason_phrase}"

        await self.push_screen_wait(ErrorScreen(exc))
        self.exit(return_code=1)

    def on_awareness_update(
        self, topic: Literal["update", "change"], data: tuple[dict, Any]
    ):
        """
        Wrapper method around the
        [`_on_awareness_update`][elva.apps.editor.app.UI._on_awareness_update]
        callback.

        Arguments:
            topic: the topic under which the changes are published.
            data: manipulation actions taken as well as the origin of the changes.
        """
        # Handle dashboard updates via worker
        if topic == "change":
            self.run_worker(self._on_awareness_update(topic, data))

    async def _on_awareness_update(
        self, topic: Literal["update", "change"], data: tuple[dict, Any]
    ):
        """
        Hook called on a change in the awareness states.

        It pushes client states to the dashboard.

        Arguments:
            topic: the topic under which the changes are published.
            data: manipulation actions taken as well as the origin of the changes.
        """
        if self.screen == self.get_screen("dashboard"):
            self.push_client_states()

    async def wait_for_component_state(
        self, component: Component, state: ComponentState
    ):
        """
        Wait for a component to set a specific state.

        Arguments:
            component: the component of interest.
            state: the awaited state.
        """
        sub = component.subscribe()
        while state != component.state:
            await sub.receive()
        component.unsubscribe(sub)

    async def on_mount(self):
        """
        Hook called on mounting the app.
        """
        if hasattr(self, "provider"):
            self.subscription = self.provider.awareness.observe(
                self.on_awareness_update
            )

        # load text from rendered file
        c = self.config

        text = ""

        render_file_path = c.get("render")
        if render_file_path is not None and render_file_path.exists():
            # we found some content on disk;
            # now check whether this has precedence over the data file
            data_file_path = c.get("file")
            if data_file_path is None or not data_file_path.exists():
                # there is no data file on disk associated with this
                # file name; we load the content
                with render_file_path.open(mode="r") as fd:
                    text = fd.read()

        # wait for components to run
        for comp in self.components:
            self.run_worker(comp.start())
            await self.wait_for_component_state(
                comp, comp.states.ACTIVE | comp.states.RUNNING
            )

        # now add the text to save updates to disk and send them over wire
        if text:
            ytextarea = self.query_one(YTextArea)
            ytextarea.load_text(text)

    async def on_unmount(self):
        """
        Hook called on unmounting the app.
        """
        if hasattr(self, "subscription"):
            self.provider.awareness.unobserve(self.subscription)
            del self.subscription

        for comp in self.components:
            await self.wait_for_component_state(comp, comp.states.NONE)

    def compose(self):
        """
        Hook arranging child widgets.
        """
        if hasattr(self, "provider"):
            awareness = self.provider.awareness
        else:
            awareness = None

        yield YTextArea(
            self.ytext,
            tab_behavior="indent",
            show_line_numbers=True,
            id="editor",
            language=self.language,
            awareness=awareness,
        )
        yield Header(show_clock=False, icon="")
        yield Footer()

    @property
    def language(self) -> str:
        """
        The language the text document is written in.
        """
        c = self.config
        file_path = c.get("file")
        if file_path is not None and file_path.suffix:
            suffixes = "".join(file_path.suffixes)
            suffix = suffixes.split(FILE_SUFFIX)[0].removeprefix(".")
            if str(file_path).endswith(suffix):
                log.info("continuing without syntax highlighting")
            else:
                try:
                    language = LANGUAGES[suffix]
                    log.info(f"enabled {language} syntax highlighting")
                    return language
                except KeyError:
                    log.info(
                        f"no syntax highlighting available for file type '{suffix}'"
                    )
        else:
            return self._language

    async def action_save(self):
        """
        Action performed on triggering the `save` key binding.
        """
        if self.config.get("file") is None:
            self.run_worker(self.get_and_set_file_paths())

    async def get_and_set_file_paths(self, data_file: bool = True):
        """
        Get and set the data or render file paths after the input prompt.

        Arguments:
            data_file: flag whether to add a data file path to the config.
        """
        name = await self.push_screen_wait("input")

        if not name:
            return

        path = Path(name)

        data_file_path = get_data_file_path(path)
        if data_file:
            self.config["file"] = data_file_path
            self.store = SQLiteStore(
                self.ydoc, self.config["identifier"], data_file_path
            )
            self.components.append(self.store)
            self.run_worker(self.store.start())

        if self.config.get("render") is None:
            render_file_path = get_render_file_path(data_file_path)
            self.config["render"] = render_file_path

            self.renderer = TextRenderer(
                self.ytext, render_file_path, self.config.get("auto_save", False)
            )
            self.components.append(self.renderer)
            self.run_worker(self.renderer.start())

        if self.screen == self.get_screen("dashboard"):
            self.push_config()

    async def action_render(self):
        """
        Action performed on triggering the `render` key binding.
        """
        if self.config.get("render") is None:
            self.run_worker(self.get_and_set_file_paths(data_file=False))
        else:
            await self.renderer.write()

    async def action_toggle_dashboard(self):
        """
        Action performed on triggering the `toggle_dashboard` key binding.
        """
        if self.screen == self.get_screen("dashboard"):
            self.pop_screen()
        else:
            await self.push_screen("dashboard")
            self.push_client_states()
            self.push_config()

    def push_client_states(self):
        """
        Method pushing the client states to the active dashboard.
        """
        if hasattr(self, "provider"):
            client_states = self.provider.awareness.client_states.copy()
            client_id = self.provider.awareness.client_id
            if client_id not in client_states:
                return
            states = list()
            states.append((client_id, client_states.pop(client_id)))
            states.extend(list(client_states.items()))
            states = tuple(states)

            awareness_view = self.screen.query_one(AwarenessView)
            awareness_view.states = states

    def push_config(self):
        """
        Method pushing the configuration mapping to the active dashboard.
        """
        config = tuple(self.config.items())

        config_view = self.screen.query_one(ConfigView)
        config_view.config = config
