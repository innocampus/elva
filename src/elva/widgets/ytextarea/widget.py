"""
Widget definition.
"""

from typing import Self

from pycrdt import Text, UndoManager
from rich.segment import Segment
from rich.style import Style
from textual.strip import Strip
from textual.widgets import TextArea
from textual.widgets.text_area import Selection

from elva.awareness import Awareness
from elva.parser import TextEventParser


class YTextArea(TextArea, TextEventParser):
    """
    Widget for displaying and manipulating text synchronized in realtime.
    """

    ytext: Text
    """The Y Text data type holding the text."""

    origin: int
    """The own origin of edits."""

    history: UndoManager
    """The history manager for undo and redo operations."""

    DEFAULT_CSS = """
        YTextArea {
          border: none;
          padding: 0;
          background: transparent;

          &:focus {
            border: none;
          }
        }
        """
    """Default CSS."""

    default_cursor_color: str
    """Color used for remote cursors when there is no color information in the awareness document."""

    def __init__(
        self,
        ytext: Text,
        *args: tuple,
        awareness: Awareness | None = None,
        **kwargs: dict,
    ):
        """
        Arguments:
            ytext: Y text data type holding the text.
            args: positional arguments passed to [`TextArea`][textual.widgets.TextArea].
            kwargs: keyword arguments passed to [`TextArea`][textual.widgets.TextArea].
        """
        super().__init__(str(ytext), *args, **kwargs)
        self.ytext = ytext
        self.awareness = awareness
        self.origin = ytext.doc.client_id

        # record changes in the YText;
        # overwrites TextArea.history
        self.yhistory = UndoManager(
            scopes=[ytext],
            capture_timeout_millis=300,
        )

        # perform undo and redo solely on our contributions
        self.yhistory.include_origin(self.origin)

        self._remote_cursors = dict()

        # Initialize remote cursor tracking
        self.default_cursor_color = "#808080"

    @classmethod
    def code_editor(cls, ytext: Text, *args: tuple, **kwargs: dict) -> Self:
        """
        Construct a text area with coding specific settings.

        Arguments:
            ytext: the Y Text data type holding the text.
            args: positional arguments passed to [`TextArea`][textual.widgets.TextArea].
            kwargs: keyword arguments passed to [`TextArea`][textual.widgets.TextArea].

        Returns:
            an instance of [`YTextArea`][elva.widgets.ytextarea.YTextArea].
        """
        return cls(ytext, *args, **kwargs)

    def get_index_from_binary_index(self, index: int) -> int:
        """
        Convert the index in UTF-8 encoding to character index.

        Arguments:
            index: index in UTF-8 encoded text.

        Returns:
            index in the UTF-8 decoded form of `btext`.
        """
        return len(self.document.text.encode()[:index].decode())

    def get_binary_index_from_index(self, index: int) -> int:
        """
        Convert the character index to index in UTF-8 encoding.

        Arguments:
            index: index in UTF-8 decoded text.

        Returns:
            index in the UTF-8 encoded form of `text`.
        """
        return len(self.document.text[:index].encode())

    def get_location_from_binary_index(self, index: int) -> tuple:
        """
        Convert binary index to document location.

        Arguments:
            index: index in the UTF-8 encoded text.

        Returns:
            a location with containing row and column coordinates.
        """
        index = self.get_index_from_binary_index(index)
        return self.document.get_location_from_index(index)

    def get_binary_index_from_location(self, location: tuple) -> int:
        """
        Convert location to binary index.

        Arguments:
            location: row and column coordinates.

        Returns:
            the index in the UTF-8 encoded text.
        """
        index = self.document.get_index_from_location(location)
        return self.get_binary_index_from_index(index)

    def _on_edit(self, retain: int = 0, delete: int = 0, insert: str = "", txn=None):
        """
        Hook called from the [`parse`][elva.parser.TextEventParser] method.

        Arguments:
            retain: the cursor to position at which the deletio and insertion range starts.
            delete: the length of the deletion range.
            insert: the insert text.
        """
        if txn.origin == self.origin:
            return

        # convert from binary index to document locations
        start = self.get_location_from_binary_index(retain)
        end = self.get_location_from_binary_index(retain + delete)

        # update UI
        self.replace(insert, start, end, origin="remote")

    def on_mount(self):
        """
        Hook called on mounting.

        It adds a subscription to changes in the Y text data type.
        """
        self.subscription_textevent = self.ytext.observe(self.parse)

        if self.awareness is not None:
            self.subscription_awareness = self.awareness.observe(
                self._handle_awareness_update
            )
            self._set_cursor_state()

    def on_unmount(self):
        """
        Hook called on unmounting.

        It cancels the subscription to changes in the Y text data type.
        """
        self.ytext.unobserve(self.subscription_textevent)
        del self.subscription_textevent

        if self.awareness is not None:
            self.awareness.unobserve(self.subscription_awareness)

    def replace(
        self,
        insert: str,
        start: tuple,
        end: tuple,
        maintain_selection_offset: bool = True,
        origin: str = "local",
    ):
        """
        Replace part of the text in the Y text data type.

        Arguments:
            insert: the characters to insert.
            start: the start location of the deletion range.
            end: the end location of the deletion range.
        """
        _start, _end = sorted((start, end))

        istart = self.get_binary_index_from_location(_start)
        iend = self.get_binary_index_from_location(_end)

        if origin == "local":
            doc = self.ytext.doc

            # perform an atomic edit
            with doc.transaction(origin=self.origin):
                if not istart == iend:
                    del self.ytext[istart:iend]

                if insert:
                    self.ytext.insert(istart, insert)

        ninsert = len(insert.encode())

        self._update_cursors(istart, iend, ninsert)

        return super().replace(
            insert,
            start,
            end,
            maintain_selection_offset=maintain_selection_offset,
        )

    def update_index(self, index, start, end, insert, target):
        if index < start:
            pass
        elif start <= index <= end:
            index = target
        elif end < index:
            index += insert - (end - start)

        return index

    def _update_cursors(self, start, end, insert):
        insert_end = start + insert

        for client, cursor in self._remote_cursors.copy().items():
            anchor, head = cursor

            if anchor > head:
                target_anchor, target_head = start, insert_end
            else:
                target_anchor, target_head = insert_end, start

            anchor = self.update_index(anchor, start, end, insert, target_anchor)
            head = self.update_index(head, start, end, insert, target_head)

            self._remote_cursors[client] = (anchor, head)

    def delete(self, start, end, maintain_selection_offset=True):
        return self.replace(
            "",
            start,
            end,
            maintain_selection_offset=maintain_selection_offset,
        )

    def undo(self):
        """
        Undo an edit done by this widget.
        """
        self.yhistory.undo()

    def redo(self):
        """
        Redo an edit done by this widget.
        """
        self.yhistory.redo()

    def _handle_awareness_update(self, topic, data):
        """
        Called in changes in the awareness document.
        """
        changes, origin = data

        if origin == "remote":
            self._remote_cursors = self._get_cursor_states()
            self.refresh()

    def _get_cursor_states(self):
        """
        Extract cursor information from the awareness states.
        """
        me = self.awareness.client_id
        states = self.awareness.client_states

        cursors = dict()

        for client, state in states.items():
            # skip own id
            if client == me:
                continue

            cursor = state.get("cursor")

            if cursor is not None:
                ianchor = cursor["anchor"]
                ihead = cursor["head"]
                cursors[client] = (ianchor, ihead)

        return cursors

    def _set_cursor_state(self):
        """
        Set cursor information in own awareness state.
        """
        anchor, head = self.selection

        ianchor = self.get_binary_index_from_location(anchor)
        ihead = self.get_binary_index_from_location(head)

        cursor = dict(cursor=dict(anchor=ianchor, head=ihead))

        state = self.awareness.get_local_state()
        state.update(cursor)

        self.awareness.set_local_state(state)

    def _get_cursor_color(self, client: int) -> str:
        """
        Get a consistent color for a client ID.

        Arguments:
            client_id: the client identifier.

        Returns:
            a hex color string.
        """
        states = self.awareness.client_states
        state = states.get(client, {})
        user = state.get("user", {})
        color = user.get("color", None)

        return color or self.default_cursor_color

    def _watch_selection(self, old: Selection, new: Selection):
        """
        Hook called when selection changes.

        Arguments:
            selection: the new selection.
        """
        if hasattr(self, "awareness") and self.awareness is not None:
            self._set_cursor_state()

    def render_line(self, y: int) -> Strip:
        """
        Render a line with remote cursor indicators.

        Arguments:
            y: the line index (in screen coordinates).

        Returns:
            the rendered strip.
        """
        strip = super().render_line(y)

        if self.awareness is None:
            return strip

        cursors = self._remote_cursors

        if not cursors:
            return strip

        # Screen row accounting for scroll
        screen_row = y + self.scroll_offset.y

        # Collect cursor positions on this line
        cursor_positions = []

        for client, (anchor, head) in cursors.items():
            color = self._get_cursor_color(client)

            anchor = self.get_location_from_binary_index(anchor)

            # cap the maximum location, just to be sure
            anchor = min(anchor, self.document.end)

            # Convert document location to screen offset (handles wrapping)
            screen_offset = self.wrapped_document.location_to_offset(anchor)

            # run calculations only for the screen row containing the cursor
            if screen_offset.y == screen_row:
                # Account for gutter width and scroll
                gutter_width = self.gutter_width
                scroll_x = self.scroll_offset.x
                screen_col = screen_offset.x + gutter_width - scroll_x

                if 0 <= screen_col < strip.cell_length:
                    cursor_positions.append((screen_col, color))

        # Apply cursor highlights by dividing and rejoining the strip
        for screen_col, color in cursor_positions:
            strip_len = strip.cell_length
            if screen_col >= strip_len:
                continue

            # Divide at cursor position and cursor+1
            end_col = min(screen_col + 1, strip_len)
            parts = strip.divide([screen_col, end_col, strip_len])

            if len(parts) >= 2:
                # Apply background color to the cursor character.
                # We combine styles since apply_style doesn't override existing bgcolor.
                cursor_style = Style(bgcolor=color)
                cursor_part = parts[1]
                # NOTE: _segments is a Textual private API; Strip doesn't expose
                # a public way to iterate or restyle individual segments.
                new_segments = []
                for seg in cursor_part._segments:
                    combined_style = (seg.style or Style()) + cursor_style
                    new_segments.append(Segment(seg.text, combined_style))
                styled_part = Strip(new_segments)
                # Rejoin the strip
                strip = Strip.join([parts[0], styled_part] + parts[2:])

        return strip
