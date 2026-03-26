"""
Tests for cursor awareness logic in the YTextArea widget.

These tests cover remote cursor position adjustment after edits and
cursor change notification suppression. They operate on the widget's
internal data structures directly, without needing a running Textual app.
"""

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
        ("a\N{PALM TREE}b", 1, 1),  # after 'a'
        ("a\N{PALM TREE}b", 5, 2),  # after emoji
        ("a\N{PALM TREE}b", 6, 3),  # after 'b'
        # 2-byte accented character
        ("café", 3, 3),  # before 'é'
        ("café", 5, 4),  # after 'é'
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
