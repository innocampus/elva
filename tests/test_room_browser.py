import json
from http.client import HTTPResponse
from io import BytesIO
from unittest.mock import patch

import pytest

from elva.apps.editor.cli import fetch_rooms_info


def _make_response(data: dict) -> HTTPResponse:
    """Create a mock HTTP response with JSON body."""
    body = json.dumps(data).encode("utf-8")
    resp = HTTPResponse(None)
    resp.fp = BytesIO(body)
    resp.status = 200
    resp.reason = "OK"
    resp.headers = resp.msg = None
    return resp


class FakeResponse:
    """Context manager wrapping a bytes payload to mimic urlopen."""

    def __init__(self, data: dict):
        self._body = json.dumps(data).encode("utf-8")

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


@pytest.mark.parametrize(
    "server_data, expected",
    [
        # typical response with multiple rooms
        (
            {
                "rooms": [
                    {"identifier": "room-a", "clients": 2, "persistent": True},
                    {"identifier": "room-b", "clients": 0, "persistent": False},
                ],
                "count": 2,
            },
            [
                {"identifier": "room-a", "clients": 2, "persistent": True},
                {"identifier": "room-b", "clients": 0, "persistent": False},
            ],
        ),
        # empty rooms list
        (
            {"rooms": [], "count": 0},
            [],
        ),
        # room entry missing identifier is filtered out
        (
            {
                "rooms": [
                    {"identifier": "good", "clients": 1, "persistent": True},
                    {"clients": 3, "persistent": False},
                ],
                "count": 2,
            },
            [{"identifier": "good", "clients": 1, "persistent": True}],
        ),
        # room with empty identifier is filtered out
        (
            {
                "rooms": [
                    {"identifier": "", "clients": 0, "persistent": False},
                ],
                "count": 1,
            },
            [],
        ),
    ],
)
def test_fetch_rooms_info(server_data, expected):
    """fetch_rooms_info parses the server JSON response correctly."""
    with patch(
        "elva.apps.editor.cli.urllib.request.urlopen",
        return_value=FakeResponse(server_data),
    ):
        result = fetch_rooms_info("localhost", 7654)
    assert result == expected


def test_fetch_rooms_info_connection_error():
    """fetch_rooms_info returns empty list on connection failure."""
    import urllib.error

    with patch(
        "elva.apps.editor.cli.urllib.request.urlopen",
        side_effect=urllib.error.URLError("refused"),
    ):
        result = fetch_rooms_info("localhost", 9999)
    assert result == []


def test_fetch_rooms_info_bad_json():
    """fetch_rooms_info returns empty list on malformed JSON."""

    class BadResponse:
        def read(self):
            return b"not json"

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    with patch(
        "elva.apps.editor.cli.urllib.request.urlopen",
        return_value=BadResponse(),
    ):
        result = fetch_rooms_info("localhost", 7654)
    assert result == []
