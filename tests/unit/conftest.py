"""The framework's own tests.

They must pass with the stand switched off, or they are not unit tests.
That used to be a promise; here it is enforced. Every test in this layer
runs with outgoing connections refused, so one that quietly starts
depending on a live service fails at once and says why, instead of
passing on a developer's machine and failing in the job that has no stand.
"""

from __future__ import annotations

import socket
from typing import NoReturn

import pytest


class NetworkAccessError(RuntimeError):
    pass


def _refuse(*args: object, **kwargs: object) -> NoReturn:  # noqa: ARG001 - mirrors socket API
    raise NetworkAccessError(
        "a unit test tried to open a network connection; unit tests run without the stand"
    )


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Undone by monkeypatch itself when the test ends."""
    monkeypatch.setattr(socket.socket, "connect", _refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", _refuse)
    monkeypatch.setattr(socket, "create_connection", _refuse)
