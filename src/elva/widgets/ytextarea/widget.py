"""
Widget definition.
"""

from typing import Self

from pycrdt import Text, UndoManager
from textual._tree_sitter import TREE_SITTER, get_language
from textual.events import MouseDown
from textual.widgets import TextArea

from elva.parser import TextEventParser

from .location import update_location
from .selection import Selection


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

    def __init__(self, ytext: Text, *args: tuple, **kwargs: dict):
        """
        Arguments:
            ytext: Y text data type holding the text.
            args: positional arguments passed to [`TextArea`][textual.widgets.TextArea].
            kwargs: keyword arguments passed to [`TextArea`][textual.widgets.TextArea].
        """
        super().__init__(str(ytext), *args, **kwargs)
        self.ytext = ytext
        self.origin = ytext.doc.client_id

        # record changes in the YText;
        # overwrites TextArea.history
        self.history = UndoManager(
            scopes=[ytext],
            capture_timeout_millis=300,
        )

        # perform undo and redo solely on our contributions
        self.history.include_origin(self.origin)

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

    def _on_edit(self, retain: int = 0, delete: int = 0, insert: str = ""):
        """
        Hook called from the [`parse`][elva.parser.TextEventParser] method.

        Arguments:
            retain: the cursor to position at which the deletio and insertion range starts.
            delete: the length of the deletion range.
            insert: the insert text.
        """
        # convert from binary index to document locations
        start = self.get_location_from_binary_index(retain)
        end = self.get_location_from_binary_index(retain + delete)

        # apply the update to the UI
        self._apply_update(insert, start, end)

    def on_mount(self):
        """
        Hook called on mounting.

        It adds a subscription to changes in the Y text data type.
        """
        self.subscription_textevent = self.ytext.observe(self.parse)

    def on_unmount(self):
        """
        Hook called on unmounting.

        It cancels the subscription to changes in the Y text data type.
        """
        self.ytext.unobserve(self.subscription_textevent)
        del self.subscription_textevent

    def load_text(self, text: str, language: str | None = None):
        """
        Load a text into the document.

        Arguments:
            text: the text to display.
            language: the tree-sitter syntax highlighting language to use.
        """
        self.replace(text, self.document.start, self.document.end)

        if not self.is_mounted:
            self.document.replace_range(self.document.start, self.document.end, text)

        if language:
            self.language = language

        self.post_message(self.Changed(self).set_sender(self))

    def replace(
        self,
        insert: str,
        start: tuple,
        end: tuple,
    ):
        """
        Replace part of the text in the Y text data type.

        Arguments:
            insert: the characters to insert.
            start: the start location of the deletion range.
            end: the end location of the deletion range.
        """
        start, end = sorted((start, end))

        doc = self.ytext.doc

        istart = self.get_binary_index_from_location(start)
        iend = self.get_binary_index_from_location(end)

        # perform an atomic edit
        with doc.transaction(origin=self.origin):
            if not istart == iend:
                del self.ytext[istart:iend]

            if insert:
                self.ytext.insert(istart, insert)

    def delete(self, start: tuple, end: tuple):
        """
        Delete a range of text.

        Arguments:
            start: the start location of the deletion range.
            end: the end location of the deletion range.
        """
        start, end = sorted((start, end))
        self.replace("", start, end)

    def insert(self, text: str, location: tuple = None):
        """
        Insert characters at a given location.

        Arguments:
            text: the characters to insert.
            location: the start location of the insertion.
        """
        if location is None:
            location = self.cursor_location

        self.replace(text, location, location)

    def clear(self):
        """
        Remove all content from the document.
        """
        self.replace("", self.document.start, self.document.end)

    def _replace_via_keyboard(self, insert: str, start: tuple, end: tuple):
        """
        Guard method respecting the [`read_only`][textual.widgets.TextArea.read_only]
        attribute before calling [`replace`][elva.widgets.ytextarea.YTextArea]
        to replace a range of text.

        Arguments:
            insert: the characters to insert.
            start: the start location of the deletion range.
            end: the end location of the deletion range.
        """
        if self.read_only:
            return

        self.replace(insert, start, end)

    def _delete_via_keyboard(self, start: tuple, end: tuple):
        """
        Guard method respecting the [`read_only`][textual.widgets.TextArea.read_only]
        attribute before calling [`replace`][elva.widgets.ytextarea.YTextArea]
        to delete a range of text.

        Arguments:
            start: the start location of the deletion range.
            end: the end location of the deletion range.
        """
        self._replace_via_keyboard("", start, end)

    def _apply_update(self, text: str, start: tuple, end: tuple):
        """
        Apply a Y text data type update to the document.

        Arguments:
            text: the characters to insert.
            start: the start location of the deletion range.
            end: the end location of the deletion range.
        """
        old_gutter_width = self.gutter_width

        # replaces edit.do(self)
        selection, top, bottom, insert_end = self._edit(text, start, end)

        new_gutter_width = self.gutter_width

        if old_gutter_width != new_gutter_width:
            self.wrapped_document.wrap(
                self.wrap_width,
                self.indent_width,
            )
        else:
            self.wrapped_document.wrap_range(
                top,
                bottom,
                insert_end,
            )

        self._refresh_size()

        # replaces edit.after(self)
        self.selection = selection
        self.record_cursor_width()

        self._build_highlight_map()
        self.post_message(self.Changed(self))

    def _edit(
        self, text: str, top: tuple, bottom: tuple
    ) -> tuple[Selection, tuple, tuple, tuple]:
        """
        Perform the edit operation.

        Args:
            text: the characters to insert.
            top: the minimum of start and end location of the deletion range.
            bottom: the maximum of start and end location of the deletion range.

        Returns:
            the updated selection, top and bottom locations as well as the end location of the insertion range.
        """

        edit_result = self.document.replace_range(top, bottom, text)

        start, end = self.selection
        insert_end = edit_result.end_location

        delete = Selection(top, bottom)
        insert = Selection(top, insert_end)

        if (start in delete) and (end in delete):
            # the current selection has been deleted, i.e. is within the deletion range;
            # reset cursor to end of edit, i.e. insert range
            start, end = insert.end, insert.end
        else:
            # reverse target locations if the current selection is reversed
            if start > end:
                target_start, target_end = insert.start, insert.end
            else:
                target_start, target_end = insert.end, insert.start

            ## start
            # before edit - no-op
            # within edit - shift to end of edit
            #  after edit - shift by edit length

            ## end
            # before edit - no-op
            # within edit - shift to start of edit
            #  after edit - shift by edit length

            start = update_location(start, delete, insert, target_start)
            end = update_location(end, delete, insert, target_end)

        selection = Selection(start, end)
        return selection, top, bottom, insert_end

    def undo(self):
        """
        Undo an edit done by this widget.
        """
        self.history.undo()

    def redo(self):
        """
        Redo an edit done by this widget.
        """
        self.history.redo()

    def _watch_language(self, new: str | None):
        """
        Hook called on change in the [`language`][textual.widgets.TextArea.language] attribute.

        Arguments:
            new: the new language.
        """
        self._highlight_query = None

        if not new:
            return

        if not TREE_SITTER:
            self.log.warning("tree-sitter not supported in this environment")
            return

        registered = self._languages.get(new)

        if registered:
            query = registered.highlight_query
            lang = registered.language or get_language(new)
        else:
            query = self._get_builtin_highlight_query(new)
            lang = get_language(new)

        if lang is not None:
            self._highlight_query = self.document.prepare_query(query)
        else:
            self.log.warning(f"tree-sitter language '{new}' not found")

        self._build_highlight_map()

    def _watch_has_focus(self, new: bool):
        """
        Hook called on change of the [`has_focus`][textual.widget.Widget.has_focus] attribute.

        Arguments:
            new: the new value.
        """
        self._cursor_visible = new

        if new:
            self._restart_blink()
            self.app.cursor_position = self.cursor_screen_offset
        else:
            self._pause_blink(visible=False)

    async def _on_mouse_down(self, event: MouseDown):
        """
        Hook on a pressed mouse button.

        Arguments:
            event: an object containing event information.
        """
        event.stop()
        event.prevent_default()
        target = self.get_target_document_location(event)
        self.selection = Selection.cursor(target)
        self._selecting = True

        self.capture_mouse()
        self._pause_blink(visible=True)

    def move_cursor(
        self,
        location: tuple,
        select: bool = False,
        center: bool = False,
        record_width: bool = True,
    ):
        """
        Move the cursor to a given location and adapt the scroll position.

        Arguments:
            location: the location to move the cursor to
            select: flag whether to expand the current selection or just move the cursor.
            center: flag whether to scroll the view.
            record_width: flag whether to record the cursor width.
        """
        if select:
            start, _ = self.selection
            self.selection = Selection(start, location)
        else:
            self.selection = Selection.cursor(location)

        if record_width:
            self.record_cursor_width()

        if center:
            self.scroll_cursor_visible(center)
