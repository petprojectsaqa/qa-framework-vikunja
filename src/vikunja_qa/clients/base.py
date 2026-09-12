"""Base for the per-area clients.

A client knows the shape of one area of the API: its paths, its verbs and
its field names. It does not know whether any given response is correct,
and it never asserts. Tests decide; clients only speak the protocol.

Keeping that line means a client can be used both to set up a scenario
and to make the call under test, with no separate "safe" and "raw"
variants of every method.
"""

from __future__ import annotations

from typing import Any

from vikunja_qa.transport.client import HttpClient
from vikunja_qa.transport.response import ApiResponse


class DomainClient:
    def __init__(self, http: HttpClient) -> None:
        self._http = http

    @property
    def http(self) -> HttpClient:
        return self._http

    # Thin pass-throughs so subclasses read as API calls rather than as
    # transport plumbing.
    def _get(self, path: str, **kwargs: Any) -> ApiResponse:
        return self._http.get(path, **kwargs)

    def _post(self, path: str, **kwargs: Any) -> ApiResponse:
        return self._http.post(path, **kwargs)

    def _put(self, path: str, **kwargs: Any) -> ApiResponse:
        return self._http.put(path, **kwargs)

    def _delete(self, path: str, **kwargs: Any) -> ApiResponse:
        return self._http.delete(path, **kwargs)
