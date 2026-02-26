"""
[`Textual`](https://textual.textualize.io/) screens for ELVA apps.
"""

from textual.binding import Binding
from textual.message import Message
from textual.screen import ModalScreen, Screen
from textual.widgets import DataTable, Input, Static

from elva.widgets.awareness import AwarenessView
from elva.widgets.config import ConfigView


class Dashboard(Screen):
    """
    Screen for displaying session information.

    It features a [`ConfigView`][elva.widgets.config.ConfigView] widget for
    displaying the current configuration parameters as well as
    an [`AwarenessView`][elva.widgets.awareness.AwarenessView] widget
    showing the active clients in the current session.
    """

    def compose(self):
        """
        Hook adding child widgets.
        """
        yield ConfigView()
        yield AwarenessView()

    def key_escape(self):
        """
        Hook executed on pressing the `Esc` key.

        It dismisses the screen.
        """
        self.dismiss()


class RoomBrowserScreen(Screen):
    """
    Screen for browsing and selecting available rooms on the server.
    """

    BINDINGS = [
        Binding("escape", "dismiss_screen", "Back"),
        Binding("g", "refresh_rooms", "Refresh"),
    ]

    def __init__(self, host: str, port: int, *args, **kwargs):
        """
        Arguments:
            host: the server hostname.
            port: the server port.
        """
        super().__init__(*args, **kwargs)
        self.host = host
        self.port = port

    def compose(self):
        """
        Hook adding child widgets.
        """
        table = DataTable(id="room-table")
        table.cursor_type = "row"
        table.add_columns("Room", "Clients", "Persistent")
        yield table

    async def on_mount(self):
        """
        Hook called on mounting the screen. Populates the room table.
        """
        self._populate_rooms()

    def _populate_rooms(self):
        """
        Fetch rooms from the server and populate the table.
        """
        from elva.apps.editor.cli import fetch_rooms_info

        table = self.query_one(DataTable)
        table.clear()

        rooms = fetch_rooms_info(self.host, self.port)
        for room in rooms:
            table.add_row(
                room["identifier"],
                str(room["clients"]),
                "yes" if room["persistent"] else "no",
                key=room["identifier"],
            )

        if not rooms:
            table.add_row("(no rooms found)", "", "", key="__empty__")

    def on_data_table_row_selected(self, event: DataTable.RowSelected):
        """
        Hook called when a row is selected.
        """
        if event.row_key.value == "__empty__":
            return
        self.dismiss(event.row_key.value)

    def action_dismiss_screen(self):
        """
        Dismiss the screen without selection.
        """
        self.dismiss(None)

    def action_refresh_rooms(self):
        """
        Refresh the room list.
        """
        self._populate_rooms()


class InputScreen(ModalScreen):
    """
    A plain modal screen with a single input field.
    """

    def compose(self):
        """
        Hook adding child widgets.
        """
        yield Input()

    def on_input_submitted(self, event: Message):
        """
        Hook executed on an [`Input.Submitted`][textual.widgets.Input.Submitted] message.

        Arguments:
            event: the message containing the submitted value.
        """
        self.dismiss(event.value)

    def key_escape(self):
        """
        Hook executed on pressing the `Esc` key.

        It dismisses the screen.
        """
        self.dismiss()


class ErrorScreen(ModalScreen):
    """
    Modal screen displaying an exception message.
    """

    exc: str
    """The exception message to display."""

    def __init__(self, exc: str, *args: tuple, **kwargs: dict):
        """
        Arguments:
            exc: the exception message to display.
            args: positional arguments passed to [`ModalScreen`][textual.screen.ModalScreen]
            kwargs: keyword arguments passed to [`ModalScreen`][textual.screen.ModalScreen]
        """
        super().__init__(*args, **kwargs)
        self.exc = exc

    def compose(self):
        """
        Hook arranging child widgets.
        """
        yield Static("The following error occured and the app will close now:")
        yield Static(self.exc)
        yield Static("Press any key or click to continue.")

    def on_button_pressed(self):
        """
        Hook called on a button pressed event.

        It dismisses the screen.
        """
        self.dismiss(self.exc)

    def on_key(self):
        """
        Hook called on a pressed key.

        It dismisses the screen.
        """
        self.dismiss(self.exc)

    def on_mouse_up(self):
        """
        Hook called on a released mouse button.

        It dismisses the screen.
        """
        self.dismiss(self.exc)
