"""
Module defining parsers for change events from Y data types.
"""

from typing import Any

import anyio
from pycrdt import ArrayEvent, MapEvent, TextEvent

from elva.component import Component, create_component_state

ParserState = create_component_state("ParserState")
"""The states of the [`EventParser`][elva.parser.EventParser] component."""


class EventParser(Component):
    """
    Parser base class.

    This class is supposed to be inherited from and extended.
    """

    event_type: TextEvent | ArrayEvent | MapEvent
    """Event type this parser is supposed to handle."""

    async def run(self):
        """
        Hook running after the `RUNNING` state has been set.

        It initializes the buffer and waits for incoming events to parse.
        """
        self._send_stream, self._receive_stream = anyio.create_memory_object_stream(
            max_buffer_size=65543
        )
        async with self._send_stream, self._receive_stream:
            self.log.info("awaiting events")
            async for event in self._receive_stream:
                await self._parse_event(event)

    def _check(self, event: TextEvent | ArrayEvent | MapEvent):
        """
        Check for the correct `event` type.

        Arguments:
            event: object holding event information of changes to a Y data type.

        Raises:
            TypeError: if `event` is not an instance of [`event_type`][elva.parser.EventParser.event_type].
        """
        if not isinstance(event, self.event_type):
            raise TypeError(
                f"The event '{event}' is of type {type(event)}, but needs to be {self.event_type}"
            )

    async def parse(self, event: TextEvent | ArrayEvent | MapEvent):
        """
        Queue `event` for parsing asynchronously.

        Arguments:
            event: object holding event information of changes to a Y data type.
        """
        self._check(event)
        await self._send_stream.send(event)
        self.log.debug("sending event")

    def parse_nowait(self, event: TextEvent | ArrayEvent | MapEvent):
        """
        Queue `event` for parsing synchronously.

        Arguments:
            event: object holding event information of changes to a Y data type.
        """
        self._check(event)
        self._send_stream.send_nowait(event)

    async def _parse_event(self, event: TextEvent | ArrayEvent | MapEvent):
        """
        Hook called when an `event` has been queued for parsing and which performs further actions.

        This method is defined as a no-op and supposed to be implemented in the inheriting subclass.

        Arguments:
            event: object holding event information of changes to a Y data type.
        """
        ...


class TextEventParser(EventParser):
    """
    [`TextEvent`][pycrdt.TextEvent] parser base class.
    """

    event_type = TextEvent
    """Event type this parser is supposed to handle."""

    async def _parse_event(self, event: TextEvent):
        """
        Hook called when an `event` has been queued for parsing and which performs further actions.

        Arguments:
            event: object holding event information of changes to a Y text data type.
        """
        deltas = event.delta

        range_offset = 0
        for delta in deltas:
            for action, var in delta.items():
                if action == "retain":
                    range_offset = var
                    await self._on_retain(range_offset)
                elif action == "insert":
                    insert_value = var
                    await self._on_insert(range_offset, insert_value)
                elif action == "delete":
                    range_length = var
                    await self._on_delete(range_offset, range_length)

    async def _on_retain(self, range_offset: int):
        """
        Hook called on action `retain`.

        This method is defined as a no-op and supposed to be implemented in the inheriting subclass.

        Arguments:
            range_offset: byte offset in the Y text data type.
        """
        ...

    async def _on_insert(self, range_offset: int, insert_value: Any):
        """
        Hook called on action `insert`.

        This method is defined as a no-op and supposed to be implemented in the inheriting subclass.

        Arguments:
            range_offset: byte offset in the Y text data type.
            insert_value: value that was inserted at `range_offset`
        """
        ...

    async def _on_delete(self, range_offset: int, range_length: int):
        """
        Hook called on action `delete`.

        This method is defined as a no-op and supposed to be implemented in the inheriting subclass.

        Arguments:
            range_offset: byte offset in the Y text data type.
            range_length: number of bytes deleted starting at `range_offset`
        """
        ...


class ArrayEventParser(EventParser):
    """
    [`ArrayEvent`][pycrdt.ArrayEvent] parser base class.
    """

    event_type = ArrayEvent
    """Event type this parser is supposed to handle."""

    async def _parse_event(self, event: ArrayEvent):
        """
        Hook called when an `event` has been queued for parsing and which performs further actions.

        Arguments:
            event: object holding event information of changes to a Y array data type.
        """
        deltas = event.delta

        range_offset = 0
        for delta in deltas:
            for action, var in delta.items():
                if action == "retain":
                    range_offset = var
                    await self._on_retain(range_offset)
                elif action == "insert":
                    insert_value = var
                    await self._on_insert(range_offset, insert_value)
                elif action == "delete":
                    range_length = var
                    await self._on_delete(range_offset, range_length)

    async def _on_retain(self, range_offset: int):
        """
        Hook called on action `retain`.

        This method is defined as a no-op and supposed to be implemented in the inheriting subclass.

        Arguments:
            range_offset: byte offset in the Y array data type.
        """
        ...

    async def _on_insert(self, range_offset: int, insert_value: Any):
        """
        Hook called on action `insert`.

        This method is defined as a no-op and supposed to be implemented in the inheriting subclass.

        Arguments:
            range_offset: byte offset in the Y array data type.
            insert_value: value that was inserted at `range_offset`
        """
        ...

    async def _on_delete(self, range_offset: int, range_length: int):
        """
        Hook called on action `delete`.

        This method is defined as a no-op and supposed to be implemented in the inheriting subclass.

        Arguments:
            range_offset: byte offset in the Y array data type.
            range_length: number of items deleted starting at `range_offset`
        """
        ...


class MapEventParser(EventParser):
    """
    [`MapEvent`][pycrdt.MapEvent] parser base class.
    """

    event_type = MapEvent
    """Event type this parser is supposed to handle."""

    async def _parse_event(self, event: MapEvent):
        """
        Hook called when an `event` has been queued for parsing and which performs further actions.

        Arguments:
            event: object holding event information of changes to a Y map data type.
        """
        keys = event.keys

        for key, delta in keys.items():
            print(delta)
            action = delta["action"]
            if action == "add":
                new_value = delta["newValue"]
                await self._on_add(key, new_value)
            elif action == "delete":
                old_value = delta["oldValue"]
                await self._on_delete(key, old_value)

    async def _on_add(self, key: str, new_value: Any):
        """
        Hook called on action `add`.

        This method is defined as a no-op and supposed to be implemented in the inheriting subclass.

        Arguments:
            key: key added to the Y map data type.
            new_value: value associated with `key` in the Y map data type.
        """
        ...

    async def _on_delete(self, key: str, old_value: Any):
        """
        Hook called on action `delete`.

        This method is defined as a no-op and supposed to be implemented in the inheriting subclass.

        Arguments:
            key: key deleted from the Y map data type.
            old_value: value which was associated with `key` in the Y map data type.
        """
        ...
