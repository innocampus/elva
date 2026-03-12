"""
Tests for cursor awareness logic in the YTextArea widget.

These tests cover remote cursor position adjustment after edits and
cursor change notification suppression. They operate on the widget's
internal data structures directly, without needing a running Textual app.
"""

from unittest.mock import MagicMock

import pytest
from pycrdt import Doc, Text

from elva.widgets.ytextarea import YTextArea


def make_widget(text_content=""):
    """Create a YTextArea with given text content for testing.

    Returns a widget that is NOT mounted (no Textual app), but has
    the internal state needed for cursor logic tests.
    """
    doc = Doc()
    ytext = Text(text_content)
    doc["ytext"] = ytext
    widget = YTextArea(ytext)
    return widget


# ---------------------------------------------------------------------------
# _adjust_remote_cursors
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("cursors", "edit_pos", "delta", "expected_positions"),
    (
        # Insertion (positive delta) after cursor: cursor unchanged
        (
            {1: (5, "#ff0000")},
            10, 3,
            {1: 5},
        ),
        # Insertion before cursor: cursor shifts forward
        (
            {1: (10, "#ff0000")},
            5, 3,
            {1: 13},
        ),
        # Insertion exactly at cursor position: cursor shifts forward
        (
            {1: (5, "#ff0000")},
            5, 3,
            {1: 8},
        ),
        # Deletion (negative delta) after cursor: cursor unchanged
        (
            {1: (5, "#ff0000")},
            10, -3,
            {1: 5},
        ),
        # Deletion before cursor: cursor shifts backward
        (
            {1: (10, "#ff0000")},
            5, -3,
            {1: 7},
        ),
        # Deletion at cursor position: cursor stays at edit position (clamped)
        (
            {1: (5, "#ff0000")},
            5, -3,
            {1: 5},
        ),
        # Deletion that would move cursor before edit position: clamped to edit pos
        (
            {1: (7, "#ff0000")},
            5, -10,
            {1: 5},
        ),
        # Multiple cursors with mixed positions relative to edit
        (
            {1: (3, "#ff0000"), 2: (10, "#00ff00"), 3: (20, "#0000ff")},
            10, 5,
            {1: 3, 2: 15, 3: 25},
        ),
        # Empty cursors dict: no-op
        (
            {},
            5, 3,
            {},
        ),
        # Cursor at position 0, insertion at 0: shifts forward
        (
            {1: (0, "#ff0000")},
            0, 5,
            {1: 5},
        ),
        # Cursor at position 0, deletion at 0: stays at 0 (clamped)
        (
            {1: (0, "#ff0000")},
            0, -5,
            {1: 0},
        ),
    ),
)
def test_adjust_remote_cursors(cursors, edit_pos, delta, expected_positions):
    """Adjust stored remote cursor positions after a local edit.

    Cursors at or after the edit position shift by delta (clamped to not
    go before the edit position). Cursors before the edit are unchanged.
    """
    w = make_widget("x" * 30)  # Enough text to cover all positions
    w._remote_cursors = dict(cursors)

    w._adjust_remote_cursors(edit_pos, delta)

    for client_id, expected_pos in expected_positions.items():
        actual_pos, _color = w._remote_cursors[client_id]
        assert actual_pos == expected_pos, (
            f"client {client_id}: expected pos {expected_pos}, got {actual_pos}"
        )


def test_adjust_remote_cursors_preserves_colors():
    """Colors are preserved through cursor adjustment."""
    w = make_widget("hello world")
    w._remote_cursors = {1: (5, "#ff0000"), 2: (8, "#00ff00")}

    w._adjust_remote_cursors(3, 2)

    assert w._remote_cursors[1][1] == "#ff0000"
    assert w._remote_cursors[2][1] == "#00ff00"


# ---------------------------------------------------------------------------
# _notify_cursor_change
# ---------------------------------------------------------------------------


def test_notify_cursor_change_no_callback():
    """No error when no callback is set (the default)."""
    w = make_widget("hello")
    w._cursor_change_callback = None
    # Should not raise
    w._notify_cursor_change()


def test_notify_cursor_change_suppressed_during_remote_edit():
    """Cursor changes during remote edit application are not broadcast.

    This prevents the local cursor from "dragging" remote cursors: when a
    remote edit moves our selection, we shouldn't broadcast that as an
    intentional cursor movement.
    """
    w = make_widget("hello")
    calls = []
    w._cursor_change_callback = lambda pos: calls.append(pos)
    w._applying_remote_edit = True

    w._notify_cursor_change()

    assert len(calls) == 0


def test_notify_cursor_change_fires_on_new_position():
    """Callback fires when cursor position changes."""
    w = make_widget("hello")
    calls = []
    w._cursor_change_callback = lambda pos: calls.append(pos)
    w._applying_remote_edit = False
    w._last_notified_cursor_pos = None

    w._notify_cursor_change()

    assert len(calls) == 1
    # Position is byte offset of cursor (at start = 0)
    assert calls[0] == 0


def test_notify_cursor_change_deduplicates():
    """Callback does not fire when position hasn't changed.

    This debouncing prevents redundant awareness updates when the cursor
    stays in the same place across multiple post-command-hook calls.
    """
    w = make_widget("hello")
    calls = []
    w._cursor_change_callback = lambda pos: calls.append(pos)
    w._applying_remote_edit = False
    # Simulate: last notified position was 0, cursor is still at 0
    w._last_notified_cursor_pos = 0

    w._notify_cursor_change()

    assert len(calls) == 0


# ---------------------------------------------------------------------------
# get_index_from_binary_index / get_binary_index_from_index
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "byte_index", "expected_char_index"),
    (
        # ASCII: byte index == char index
        ("hello", 0, 0),
        ("hello", 3, 3),
        ("hello", 5, 5),
        # Empty text
        ("", 0, 0),
        # 4-byte emoji
        ("a\N{PALM TREE}b", 0, 0),
        ("a\N{PALM TREE}b", 1, 1),   # after 'a'
        ("a\N{PALM TREE}b", 5, 2),   # after emoji
        ("a\N{PALM TREE}b", 6, 3),   # after 'b'
        # 2-byte accented character
        ("café", 3, 3),   # before 'é'
        ("café", 5, 4),   # after 'é'
    ),
)
def test_get_index_from_binary_index(text, byte_index, expected_char_index):
    """Convert UTF-8 byte index to character index within the document."""
    w = make_widget(text)
    assert w.get_index_from_binary_index(byte_index) == expected_char_index


@pytest.mark.parametrize(
    ("text", "char_index", "expected_byte_index"),
    (
        # ASCII: byte index == char index
        ("hello", 0, 0),
        ("hello", 3, 3),
        ("hello", 5, 5),
        # Empty text
        ("", 0, 0),
        # 4-byte emoji
        ("a\N{PALM TREE}b", 1, 1),
        ("a\N{PALM TREE}b", 2, 5),
        ("a\N{PALM TREE}b", 3, 6),
        # 2-byte accented character
        ("café", 4, 5),
    ),
)
def test_get_binary_index_from_index(text, char_index, expected_byte_index):
    """Convert character index to UTF-8 byte index within the document."""
    w = make_widget(text)
    assert w.get_binary_index_from_index(char_index) == expected_byte_index


@pytest.mark.parametrize(
    ("text", "byte_index"),
    (
        ("hello", 0),
        ("hello", 5),
        ("a\N{PALM TREE}b", 0),
        ("a\N{PALM TREE}b", 1),
        ("a\N{PALM TREE}b", 5),
        ("a\N{PALM TREE}b", 6),
        ("café", 0),
        ("café", 3),
        ("café", 5),
    ),
)
def test_widget_byte_char_roundtrip(text, byte_index):
    """Round-trip byte->char->byte returns original at character boundaries."""
    w = make_widget(text)
    char_index = w.get_index_from_binary_index(byte_index)
    result = w.get_binary_index_from_index(char_index)
    assert result == byte_index
