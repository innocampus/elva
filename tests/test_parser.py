from typing import Union

import anyio
import pytest
from pycrdt import Array, ArrayEvent, Doc, Map, MapEvent, Text, TextEvent

from elva.parser import (
    ArrayEventParser,
    MapEventParser,
    TextEventParser,
)

DELAY = 0.01  # seconds


class Holder:
    """An object to assign arbitrary attributes to."""

    pass


def init(data_type) -> tuple[Doc, Union[Text, Array, Map], Holder]:
    """
    Initializes a shared data type of kind 'kind' and integrates it into a YDocument.
    It returns the YDocument, the shared data type and an holder object holding the last event.
    """
    doc = Doc()
    doc["shared"] = data_type

    holder = Holder()

    def callback(event):
        holder.event = event

    data_type.observe(callback)

    return doc, data_type, holder


@pytest.mark.anyio
async def test_text_event_parser():
    doc, text, holder = init(Text())
    holder.actions = list()

    class TestParser(TextEventParser):
        async def _on_retain(self, retain):
            holder.actions.append(("retain", retain))

        async def _on_insert(self, retain, value):
            holder.actions.append(("insert", retain, value))

        async def _on_delete(self, retain, length):
            holder.actions.append(("delete", retain, length))

    text_event_parser = TestParser()
    sub = text_event_parser.subscribe()
    states = text_event_parser.states

    async with text_event_parser:
        # is it running?
        while states.RUNNING not in text_event_parser.state:
            await sub.receive()

        # insert
        text += "test"
        assert str(text) == "test"
        event = holder.event
        assert isinstance(event, TextEvent)

        await text_event_parser.parse(event)
        # wait for parsing to finish
        await anyio.sleep(DELAY)
        assert holder.actions == [
            ("insert", 0, "test"),
        ]

        holder.actions.clear()

        # retain and insert, order matters
        text += "test"
        assert str(text) == "testtest"
        event = holder.event
        assert isinstance(event, TextEvent)

        await text_event_parser.parse(event)
        # wait for parsing to finish
        await anyio.sleep(DELAY)
        assert holder.actions == [
            ("retain", 4),
            ("insert", 4, "test"),
        ]

        holder.actions.clear()

        # retain and delete, order matters
        del text[2:]
        assert str(text) == "te"
        event = holder.event
        assert isinstance(event, TextEvent)

        await text_event_parser.parse(event)
        # wait for parsing to finish
        await anyio.sleep(DELAY)
        assert holder.actions == [
            ("retain", 2),
            ("delete", 2, 6),
        ]


@pytest.mark.anyio
async def test_array_event_parser():
    doc, array, holder = init(Array())
    holder.actions = list()

    class TestParser(ArrayEventParser):
        async def _on_retain(self, retain):
            holder.actions.append(("retain", retain))

        async def _on_insert(self, retain, values):
            holder.actions.append(("insert", retain, values))

        async def _on_delete(self, retain, length):
            holder.actions.append(("delete", retain, length))

    array_event_parser = TestParser()
    sub = array_event_parser.subscribe()
    states = array_event_parser.states

    async with array_event_parser:
        # is it running?
        while states.RUNNING not in array_event_parser.state:
            await sub.receive()

        # extend
        array.extend([1, 2, 3])
        assert array.to_py() == [1.0, 2.0, 3.0]
        event = holder.event
        assert isinstance(event, ArrayEvent)

        await array_event_parser.parse(event)
        # wait for parsing to finish
        await anyio.sleep(DELAY)
        assert holder.actions == [
            ("insert", 0, [1.0, 2.0, 3.0]),
        ]

        holder.actions.clear()

        # retain and insert, order matters
        array.insert(2, 10)
        assert array.to_py() == [1.0, 2.0, 10.0, 3.0]
        event = holder.event
        assert isinstance(event, ArrayEvent)

        await array_event_parser.parse(event)
        # wait for parsing to finish
        await anyio.sleep(DELAY)
        assert holder.actions == [
            ("retain", 2),
            ("insert", 2, [10.0]),
        ]

        holder.actions.clear()

        # retain and delete, order matters
        array.pop(1)
        assert array.to_py() == [1.0, 10.0, 3.0]
        event = holder.event
        assert isinstance(event, ArrayEvent)

        await array_event_parser.parse(event)
        # wait for parsing to finish
        await anyio.sleep(DELAY)
        assert holder.actions == [
            ("retain", 1),
            ("delete", 1, 1),
        ]


@pytest.mark.anyio
async def test_map_event_parser():
    doc, map, holder = init(Map())
    holder.actions = set()

    class TestParser(MapEventParser):
        async def _on_add(self, key, new_value):
            holder.actions.add(("add", key, new_value))

        async def _on_delete(self, key, old_value):
            holder.actions.add(("delete", key, old_value))

    map_event_parser = TestParser()
    sub = map_event_parser.subscribe()
    states = map_event_parser.states

    async with map_event_parser:
        # is it running?
        while states.RUNNING not in map_event_parser.state:
            await sub.receive()

        # add
        # order does not matter
        map.update({"foo": "bar", "baz": "faz"})
        assert map.to_py() == {"foo": "bar", "baz": "faz"}
        event = holder.event
        assert isinstance(event, MapEvent)

        await map_event_parser.parse(event)
        # wait for parsing to finish
        await anyio.sleep(DELAY)
        assert holder.actions == set(
            [
                ("add", "foo", "bar"),
                ("add", "baz", "faz"),
            ]
        )

        holder.actions.clear()

        # delete
        # order does not matter
        map.pop("foo")
        assert map.to_py() == {"baz": "faz"}
        event = holder.event
        assert isinstance(event, MapEvent)

        await map_event_parser.parse(event)
        # wait for parsing to finish
        await anyio.sleep(DELAY)
        assert holder.actions == set(
            [
                ("delete", "foo", "bar"),
            ]
        )
