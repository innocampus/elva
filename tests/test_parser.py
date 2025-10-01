import pytest
from pycrdt import Array, Doc, Map, Text

from elva.parser import (
    ArrayEventParser,
    MapEventParser,
    TextEventParser,
)


@pytest.mark.parametrize(
    ("initial_text", "edits", "expected_text"),
    (
        # insert at beginning
        (
            "",
            [lambda text: text.insert(0, "test")],
            "test",
        ),
        # insert at end
        (
            "",
            [lambda text: text.insert(100, "test")],
            "test",
        ),
        # insert before content
        (
            "foo",
            [lambda text: text.insert(0, "bar")],
            "barfoo",
        ),
        # insert into content
        (
            "foo",
            [lambda text: text.insert(1, "bar")],
            "fbaroo",
        ),
        # insert after content
        (
            "foo",
            [lambda text: text.insert(3, "bar")],
            "foobar",
        ),
        # insert and delete slice
        (
            "foo",
            [
                lambda text: text.insert(2, "bar"),
                lambda text: text.__delitem__(slice(1, 4)),
                lambda text: text.insert(0, "baz"),
            ],
            "bazfro",
        ),
        # insert and delete slice
        (
            "foo",
            [
                lambda text: text.insert(3, "bar"),
                lambda text: text.__delitem__(slice(2, 4)),
                lambda text: text.insert(1, "quux"),
            ],
            "fquuxoar",
        ),
        # insert and delete slice
        (
            "foo",
            [
                lambda text: text.insert(1, "quux"),
                lambda text: text.insert(7, "bar"),
                lambda text: text.__delitem__(slice(6, 8)),
            ],
            "fquuxoar",
        ),
        # insert single grapheme cluster with a single codepoint
        (
            "",
            [lambda text: text.insert(0, "\N{SLIGHTLY SMILING FACE}")],
            "\N{SLIGHTLY SMILING FACE}",
        ),
        # insert single grapheme cluster with a single codepoint before content
        (
            "\N{PALM TREE}",
            [lambda text: text.insert(0, "\N{SMILING FACE WITH SUNGLASSES}")],
            "\N{SMILING FACE WITH SUNGLASSES}\N{PALM TREE}",
        ),
        # insert single grapheme cluster with a single codepoint into another cluster
        (
            "\N{PALM TREE}",
            [lambda text: text.insert(2, "\N{SMILING FACE WITH SUNGLASSES}")],
            "\N{PALM TREE}\N{SMILING FACE WITH SUNGLASSES}",
        ),
        # insert single grapheme cluster with a single codepoint after content
        (
            "\N{PALM TREE}",
            [lambda text: text.insert(100, "\N{SMILING FACE WITH SUNGLASSES}")],
            "\N{PALM TREE}\N{SMILING FACE WITH SUNGLASSES}",
        ),
    ),
)
def test_text_event_parser(initial_text, edits, expected_text):
    #
    # SETUP
    #

    # parameters yielded from the parser class
    params = list()

    class TestParser(TextEventParser):
        def _on_edit(self, insert="", retain=0, delete=0):
            params.append((insert, retain, delete))

    parser = TestParser()

    # data type
    doc = Doc()
    doc["shared"] = text = Text(initial_text)
    text.observe(lambda event: parser.parse(event))

    #
    # TEST PARSER
    #

    # perform and pack the edits in atomic transaction
    with doc.transaction():
        for edit in edits:
            edit(text)

    # we defined the edits properly, so that we get the expected text
    assert str(text) == expected_text

    #
    # TEST PARAMETERS
    #

    # define a new data type
    new_doc = Doc()
    new_doc["shared"] = new_text = Text(initial_text)

    # define intended usage of parameters
    def replace(text, insert, retain, delete):
        if delete:
            end = retain + delete
            del text[retain:end]

        if insert:
            text.insert(retain, insert)

    # redo the edits with the parameters
    for edit in params:
        replace(new_text, *edit)

    # we end up with the same expected text as above
    assert str(new_text) == expected_text


@pytest.mark.parametrize(
    ("initial_items", "edits", "expected_items"),
    (
        # insert
        (
            [],
            [lambda array: array.insert(0, "foo")],
            ["foo"],
        ),
        # insert before another item
        (
            ["foo"],
            [lambda array: array.insert(0, "bar")],
            ["bar", "foo"],
        ),
        # insert after another item
        (
            ["foo"],
            [lambda array: array.insert(1, "bar")],
            ["foo", "bar"],
        ),
        # delete
        (
            ["foo"],
            [lambda array: array.__delitem__(0)],
            [],
        ),
        # insert and delete
        (
            [],
            [
                lambda array: array.insert(0, "bar"),
                lambda array: array.insert(1, "baz"),
                lambda array: array.__delitem__(0),
            ],
            ["baz"],
        ),
        # delete slice and insert
        (
            ["foo", "bar", "baz"],
            [
                lambda array: array.__delitem__(slice(0, 2)),
                lambda array: array.insert(1, "quux"),
                lambda array: array.__delitem__(0),
            ],
            ["quux"],
        ),
    ),
)
def test_array_event_parser(initial_items, edits, expected_items):
    #
    # SETUP
    #

    # parameters yielded from the parser class
    params = list()

    class TestParser(ArrayEventParser):
        def _on_edit(self, insert=[], retain=0, delete=0):
            params.append((insert, retain, delete))

    parser = TestParser()

    # data type
    doc = Doc()
    doc["shared"] = array = Array(initial_items)
    array.observe(lambda event: parser.parse(event))

    #
    # TEST PARSER
    #

    # perform and pack the edits in atomic transaction
    with doc.transaction():
        for edit in edits:
            edit(array)

    # we defined the edits properly, so that we get the expected items
    assert array.to_py() == expected_items

    #
    # TEST PARAMETERS
    #

    # define a new data type
    new_doc = Doc()
    new_doc["shared"] = new_array = Array(initial_items)

    # define intended usage of parameters
    def replace(array, insert, retain, delete):
        if delete:
            end = retain + delete
            del array[retain:end]

        for i, item in enumerate(insert):
            array.insert(retain + i, item)

    # redo the edits with the parameters
    for edit in params:
        replace(new_array, *edit)

    # we end up with the same expected items as above
    assert new_array.to_py() == expected_items


@pytest.mark.parametrize(
    ("initial_items", "edits", "expected_items"),
    (
        # insert
        (
            {},
            [lambda map: map.__setitem__("foo", "bar")],
            {"foo": "bar"},
        ),
        # delete
        (
            {"foo": "bar"},
            [lambda map: map.__delitem__("foo")],
            {},
        ),
        # update
        (
            {"foo": "bar"},
            [lambda map: map.__setitem__("foo", "baz")],
            {"foo": "baz"},
        ),
        # insert, delete, update
        (
            {},
            [
                lambda map: map.__setitem__("foo", "bar"),
                lambda map: map.__setitem__("baz", "quux"),
                lambda map: map.__delitem__("baz"),
                lambda map: map.__setitem__("foo", "blub"),
            ],
            {"foo": "blub"},
        ),
    ),
)
def test_map_event_parser(initial_items, edits, expected_items):
    #
    # SETUP
    #

    # parameters yielded from the parser class
    params = list()

    class TestParser(MapEventParser):
        def _on_edit(self, delete={}, update={}, insert={}):
            params.append((delete, update, insert))

    parser = TestParser()

    # data type
    doc = Doc()
    doc["shared"] = map = Map(initial_items)
    map.observe(lambda event: parser.parse(event))

    #
    # TEST PARSER
    #

    # perform and pack the edits in atomic transaction
    with doc.transaction():
        for edit in edits:
            edit(map)

    # we defined the edits properly, so that we get the expected items
    assert map.to_py() == expected_items

    #
    # TEST PARAMETERS
    #

    # define a new data type
    new_doc = Doc()
    new_doc["shared"] = new_map = Map(initial_items)

    # define intended usage of parameters
    def replace(map, delete, update, insert):
        # delete all keys
        for key in delete:
            del map[key]

        # extract only the new values of updated keys
        update = dict((key, new) for key, (_, new) in update.items())
        map.update(update)

        # throw in new key-value-pairs
        map.update(insert)

    # redo the edits with the parameters
    for edit in params:
        replace(new_map, *edit)

    # we end up with the same expected items as above
    assert new_map.to_py() == expected_items
