"""
Module defining parsers for change events from Y data types.
"""

from typing import Any

from pycrdt import ArrayEvent, MapEvent, TextEvent


class IndexBasedEventParser:
    """
    Base class for index-based [`TextEventParser][elva.parser.TextEventParser]
    and [`ArrayEventParser`][elva.parser.ArrayEventParser].
    """

    def _get_insertion_length(self, value: str | list) -> int:
        """
        Calculate the cursor advancement for the inserted value.

        This method is supposed to be implemented in an inheriting subclass.

        Raises:
            NotImplementedError: if not redefined.

        Arguments:
            value: the inserted value.

        Returns:
            the steps to move the cursor forward.
        """
        raise NotImplementedError("No insertion length logic specified")

    def parse(self, event: TextEvent | ArrayEvent):
        """
        Hook called when an `event` has been queued for parsing and which performs further actions.

        Arguments:
            event: object holding event information of changes to a Y text data type.
        """
        cursor = 0
        kwargs = dict()

        # `event.delta` is a list of edits
        for edit in event.delta:
            if "retain" in edit:
                # we are about to move the cursor to a new edit;
                # perform the current edit first
                if kwargs:
                    self._on_edit(**kwargs)

                # move the cursor
                cursor += edit["retain"]

                # renew kwargs for the new edit
                kwargs = dict(retain=cursor)
            elif "insert" in edit:
                # the cursor only moves on insertion respecting a present deletion,
                # but not on deletion only
                cursor += self._get_insertion_length(edit["insert"]) - kwargs.get(
                    "delete", 0
                )

                # update kwargs for the current edit
                kwargs.update(edit)
            else:
                # "delete" in edit
                kwargs.update(edit)

        # perform the last edit in `event.delta`
        if kwargs:
            self._on_edit(**kwargs)

    def _on_edit(**kwargs):
        """
        Hook called on every edit of a parsed event.

        It is defined as a no-op and supposed to be implemented in an inheriting subclass.

        Arguments:
            kwargs: a mapping of the edit parameters.
        """
        ...


class TextEventParser(IndexBasedEventParser):
    """
    [`TextEvent`][pycrdt.TextEvent] parser base class.
    """

    def _get_insertion_length(self, text: str) -> int:
        """
        Calculate the cursor advancement for the inserted text.

        Arguments:
            value: the inserted text.

        Returns:
            the steps to move the cursor forward.
        """
        return len(text.encode("utf-8"))

    def _on_edit(retain: int = 0, delete: int = 0, insert: str = ""):
        """
        Hook called on every edit of a parsed event.

        It is defined as a no-op and supposed to be implemented in an inheriting subclass.

        Arguments:
            retain: the UTF-8 byte index at which the insert and deletion range start.
            delete: the length of the deletion range in UTF-8 bytes
            insert: the inserted text.
        """
        ...


class ArrayEventParser(IndexBasedEventParser):
    """
    [`ArrayEvent`][pycrdt.ArrayEvent] parser base class.
    """

    def _get_insertion_length(self, items: list) -> int:
        """
        Calculate the cursor advancement for the inserted items.

        Arguments:
            value: the inserted items.

        Returns:
            the steps to move the cursor forward.
        """
        return len(items)

    def _on_edit(retain: int = 0, delete: int = 0, insert: list = []):
        """
        Hook called on every edit of a parsed event.

        It is defined as a no-op and supposed to be implemented in an inheriting subclass.

        Arguments:
            retain: the index at which the insert and deletion range start.
            delete: the length of the deletion range in indices
            insert: a list of the inserted elements.
        """
        ...


class MapEventParser:
    """
    [`MapEvent`][pycrdt.MapEvent] parser base class.
    """

    def parse(self, event: MapEvent):
        """
        Hook called when an `event` has been queued for parsing and which performs further actions.

        Arguments:
            event: object holding event information of changes to a Y map data type.
        """
        # dictionary of keys mapping to actions and values
        keys = event.keys

        insert = dict()
        update = dict()
        delete = dict()

        # collect inserted, updated and deleted keys alongside their values
        for key, delta in keys.items():
            action = delta["action"]

            if action == "add":
                insert[key] = delta["newValue"]
            elif action == "update":
                update[key] = (delta["oldValue"], delta["newValue"])
            elif action == "delete":
                delete[key] = delta["oldValue"]

        # perform the edit
        self._on_edit(delete=delete, update=update, insert=insert)

    def _on_edit(
        self, delete: dict[str, Any], update: dict[str, Any], insert: dict[str, Any]
    ):
        """
        Hook called on every edit of a parsed event.

        It is defined as a no-op and supposed to be implemented in an inheriting subclass.

        Arguments:
            delete: a mapping with deleted keys alongside their respective old value.
            update: a mapping with updated keys alongside tuples containing their respective old and new value.
            insert: a mapping with added keys alongside their respective new value.
        """
        ...
