"""
Widget definition.
"""

from collections import deque
from typing import Self, Literal

from pycrdt import Text, UndoManager, ReadTransaction
from rich.segment import Segment
from rich.style import Style
from textual.strip import Strip
from textual.widgets import TextArea
from textual.widgets.text_area import Location, EditResult

from elva.awareness import Awareness
from elva.parser import TextEventParser


class YTextArea(TextArea, TextEventParser):
    """
    Widget for displaying and manipulating text synchronized in realtime.
    """

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

    ytext: Text
    """The Y Text data type holding the text."""

    origin: int
    """The own origin of edits."""

    yhistory: UndoManager
    """The history manager for undo and redo operations."""

    cursor_cache_size: int
    """The maxmimum number of cursor positions saved in the cache."""

    default_cursor_color: str
    """Color used for remote cursors when there is no color information in the awareness document."""

    def __init__(
        self,
        ytext: Text,
        *args: tuple,
        awareness: Awareness | None = None,
        cursor_cache_size: int = 100,
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

        # initialize remote cursor tracking
        self._remote_cursor_caches = dict()
        self.cursor_cache_size = cursor_cache_size

        # default color for remote cursors
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

    def _on_edit(
        self,
        retain: int = 0,
        delete: int = 0,
        insert: str = "",
        txn: ReadTransaction | None = None,
    ) -> None:
        """
        Hook called from the [`parse`][elva.parser.TextEventParser] method.

        Arguments:
            retain: the cursor to position at which the deletio and insertion range starts.
            delete: the length of the deletion range.
            insert: the insert text.
            txn: the transaction associated with the ytext update.
        """
        if txn.origin == self.origin:
            # this update was done locally and the UI has already been updated
            return

        # convert from binary index to document locations
        start = self.get_location_from_binary_index(retain)
        end = self.get_location_from_binary_index(retain + delete)

        # perform the edit and update the app state
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

            # send an awareness update when ready
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
    ) -> EditResult:
        """
        Replace part of the text in the Y text data type.

        Arguments:
            insert: the characters to insert.
            start: the start location of the deletion range.
            end: the end location of the deletion range.

        Returns:
            the result of the performed edit.
        """
        _start, _end = sorted((start, end))

        istart = self.get_binary_index_from_location(_start)
        iend = self.get_binary_index_from_location(_end)

        # don't redo remote updates twice in the ytext
        if origin == "local":
            doc = self.ytext.doc

            # perform an atomic edit
            with doc.transaction(origin=self.origin):
                if not istart == iend:
                    del self.ytext[istart:iend]

                if insert:
                    self.ytext.insert(istart, insert)

        # precalculate the new cursor positions as
        # `replace` also refreshes the screen and with it all cursors
        ninsert = len(insert.encode())
        self._update_cursors(istart, iend, ninsert)

        # perform the edit in `document` and update the app state
        edit = super().replace(
            insert,
            start,
            end,
            maintain_selection_offset=maintain_selection_offset,
        )

        # return the result to conform with the superclass
        return edit

    def _update_index(
        self,
        index: int,
        start: int,
        end: int,
        insert: int,
        target: int,
    ) -> int:
        """
        Recalculate an index based on edit metrics.

        Arguments:
            index: the index to update.
            start: start of the deletion range.
            end: end of the deletion range.
            target: the index to return when `index` is within the deletion range.

        Returns:
            the updated index.
        """
        if index < start:
            # the index is before the deletion range,
            # so not influenced by deletion and insertion and left as is
            pass
        elif start <= index < end:
            # the index is with the deletion range,
            # reset index to `target`
            index = target
        elif end <= index:
            # the index is behind the deletion range,
            # move by difference in length of deleted and inserted text
            index += insert - (end - start)

        return index

    def _update_cursors(self, start: int, end: int, insert: int) -> None:
        """
        Recalculate the remote cursor positions based on edit metrics.

        Arguments:
            start: start of the deletion range.
            end: end of the deletion range.
            insert: the length of the inserted text.
        """
        insert_end = start + insert

        for client, cache in self._remote_cursor_caches.items():
            # use the latest known cursor position
            anchor, head = cache[-1]

            # set the target index, for indices within a deletion range, accordingly
            if anchor > head:
                target_anchor, target_head = start, insert_end
            else:
                target_anchor, target_head = insert_end, start

            # update the cursor indices
            anchor = self._update_index(anchor, start, end, insert, target_anchor)
            head = self._update_index(head, start, end, insert, target_head)

            # append the new cursor positions
            cache.append((anchor, head))

    def delete(
        self,
        start: Location,
        end: Location,
        maintain_selection_offset: bool = True,
    ) -> EditResult:
        """
        Delete text between a start and an end location.

        Arguments:
            start: start of the deletion range.
            end: end of the deletion range.
            maintain_selection_offset: keep the selection or reset it the the end of the edit.

        Returns:
            the result of the performed edit.
        """
        return self.replace(
            "",
            start,
            end,
            maintain_selection_offset=maintain_selection_offset,
        )

    def undo(self) -> None:
        """
        Undo an edit done by this widget.
        """
        self.yhistory.undo()

    def redo(self) -> None:
        """
        Redo an edit done by this widget.
        """
        self.yhistory.redo()

    def _handle_awareness_update(
        self,
        topic: Literal["update", "change"],
        data: tuple[dict[str, tuple], str],
    ) -> None:
        """
        Called in changes in the awareness document.

        Arguments:
            topic: the kind of awareness update, either `"update"` or `"change"`.
            data: a tuple with the changes and the origin of the awareness update.
        """
        changes, origin = data

        # update remote cursors only when we got a `"change"` update from remote
        if topic == "change" and origin == "remote":
            self._update_cursor_caches(changes)

            # refresh the UI
            self.refresh()

    def _update_cursor_caches(self, changes: dict[str, tuple]) -> None:
        """
        Extract cursor information from the awareness states and compare them
        to the local cursor history.

        Arguments:
            changes: a mapping of `"added"`, `"updated"` and `"removed"` clients.
        """
        states = self.awareness.client_states
        caches = self._remote_cursor_caches

        for client in changes["removed"]:
            caches.pop(client, None)

        for client in changes["added"] + changes["updated"]:
            state = states.get(client, {})
            cursor = state.get("cursor", {})

            ianchor = cursor.get("anchor", None)
            ihead = cursor.get("head", None)

            if ianchor is None or ihead is None:
                # the awareness state does not provide cursor information
                continue

            received = (ianchor, ihead)

            # set a maximum length to avoid unbound growing, e.g. while offline
            cache = caches.setdefault(client, deque(maxlen=self.cursor_cache_size))

            # remove the first cursor position, i.e. the next one expected, from
            # the cache if possible and compare it to the received one:
            # if they are the same, add this position back if the cache has been
            # emptied for the comparison;
            # if not, invalidate the cache and add the received position;
            # if the cache was empty in the first place, just add the received
            # cursor position

            if cache and received != cache.popleft():
                # invalidate cache
                cache.clear()

            if not cache:
                # add the last known cursor position
                cache.append(received)

    def _set_cursor_state(self):
        """
        Set cursor information in own awareness state.
        """
        # get the positions from the current selection in the UI
        anchor, head = self.selection

        ianchor = self.get_binary_index_from_location(anchor)
        ihead = self.get_binary_index_from_location(head)

        # define the whole cursor struct
        cursor = dict(
            cursor=dict(
                anchor=ianchor,
                head=ihead,
            ),
        )

        # update the local state
        state = self.awareness.get_local_state()
        state.update(cursor)

        # set the new state and trigger an awareness update
        self.awareness.set_local_state(state)

    def _get_cursor_color(self, client: int) -> str:
        """
        Get a consistent color for a client ID.

        Arguments:
            client: the client identifier.

        Returns:
            a hex color string.
        """
        # try to retrieve a client's color
        states = self.awareness.client_states
        state = states.get(client, {})
        user = state.get("user", {})
        color = user.get("color", None)

        return color or self.default_cursor_color

    def _watch_selection(self):
        """
        Hook called when selection changes.
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

        caches = self._remote_cursor_caches

        if not caches:
            return strip

        # Screen row accounting for scroll
        screen_row = y + self.scroll_offset.y

        # Collect cursor positions on this line
        cursor_positions = []

        for client, cache in caches.items():
            color = self._get_cursor_color(client)

            ianchor, ihead = cache[-1]
            anchor = self.get_location_from_binary_index(ianchor)

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

            # divide at cursor position and cursor + 1
            end_col = min(screen_col + 1, strip_len)
            parts = strip.divide([screen_col, end_col, strip_len])

            if len(parts) >= 2:
                # define background color style
                cursor_style = Style(bgcolor=color)

                # apply styles to segments instead of to the strip directly since
                # `Strip.apply_style` doesn't override existing bgcolor:
                # its `style` gets overwritten by the inner segment styles;
                # a fix by exposing the `post_style` parameter has been proposed;
                # see https://github.com/Textualize/textual/issues/6448
                segments = [seg for seg in parts[1]]
                segments = Segment.apply_style(segments, post_style=cursor_style)
                parts[1] = Strip(segments)

                # rejoin the strip
                strip = Strip.join(parts)

        return strip
