"""The transport's own promises, checked without a network.

`requests` lets a test swap the adapter that would open a connection, so
the real client runs its real code against canned answers.
"""

from __future__ import annotations

from typing import Any

import pytest
import requests
from requests.adapters import BaseAdapter

from vikunja_qa.auth.strategies import BasicAuth
from vikunja_qa.transport.client import HttpClient
from vikunja_qa.transport.response import ApiResponse


class CannedAdapter(BaseAdapter):
    """Answers every request with one prepared response and remembers what
    it was asked, including the timeout the client passed down."""

    def __init__(self, status: int = 200, headers: dict[str, str] | None = None) -> None:
        super().__init__()
        self._status = status
        self._headers = headers or {}
        self.requests: list[requests.PreparedRequest] = []
        self.timeouts: list[Any] = []

    def send(  # type: ignore[override]
        self, request: requests.PreparedRequest, **kwargs: Any
    ) -> requests.Response:
        self.requests.append(request)
        self.timeouts.append(kwargs.get("timeout"))
        response = requests.Response()
        response.status_code = self._status
        response.headers.update(self._headers)
        response._content = b'{"ok": true}'
        response.request = request
        response.url = request.url or ""
        return response

    def close(self) -> None:
        pass


def _client(adapter: CannedAdapter, **kwargs: Any) -> HttpClient:
    session = requests.Session()
    session.mount("http://", adapter)
    return HttpClient("http://stand.invalid/api/v1", session=session, **kwargs)


def test_header_names_are_looked_up_without_regard_to_case() -> None:
    """Go canonicalises header names, so a challenge arrives as
    `Www-Authenticate`; the lookup a test naturally writes must still find it."""
    adapter = CannedAdapter(401, {"Www-Authenticate": 'basic realm="Restricted"'})

    answered = _client(adapter).get("/user")

    assert answered.headers.get("WWW-Authenticate") == 'basic realm="Restricted"'
    assert answered.headers.get("www-authenticate") == 'basic realm="Restricted"'


def test_a_derived_client_keeps_everything_but_what_it_changes() -> None:
    adapter = CannedAdapter()
    seen: list[ApiResponse] = []
    base = _client(adapter, timeout=15.0, hooks=[seen.append])

    impatient = base.with_timeout(2.5)
    impatient.get("/user")
    base.get("/user")

    assert adapter.timeouts == [2.5, 15.0], "the deadline must belong to the derived client only"
    assert len(seen) == 2, "hooks, and so contract checks, must follow a derived client"


def test_a_credential_is_applied_unless_the_test_sends_its_own() -> None:
    adapter = CannedAdapter()
    client = _client(adapter).with_auth(BasicAuth("someone", "secret"))

    client.get("/user")
    client.get("/user", headers={"Authorization": "Bearer deliberately-wrong"})

    stamped, overridden = (request.headers["Authorization"] for request in adapter.requests)
    assert stamped.startswith("Basic ")
    assert overridden == "Bearer deliberately-wrong"


@pytest.mark.parametrize("status", [200, 204, 299])
def test_success_is_the_2xx_range(status: int) -> None:
    assert _client(CannedAdapter(status)).get("/user").ok


@pytest.mark.parametrize("status", [199, 300, 404, 500])
def test_anything_outside_2xx_is_not_success(status: int) -> None:
    assert not _client(CannedAdapter(status)).get("/user").ok


class TestSecretsNeverReachTheReport:
    """What `describe` renders is published.

    It feeds the message on a failed assertion and the attachments in an
    Allure report this project puts on the open web. A scan of that report
    found three thousand session tokens and the fixed test password, in
    plain text, on every registration and every login. The stands behind
    them were long gone, so nothing was at risk — but a testing tool that
    prints credentials into a public page is teaching the wrong habit, and
    a reader debugging a failure has never needed the literal string.
    """

    SECRET = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.aaaaaaaaaaaaaaaaaaaa.bbbbbbbbbbbb"

    def _response(self, body: object, sent: object = None) -> ApiResponse:
        return ApiResponse(
            method="POST",
            url="http://host/api/v1/login",
            status=200,
            headers={},
            body=body,
            elapsed_ms=1.0,
            request_body=sent,
        )

    def test_a_token_in_the_answer_is_redacted(self) -> None:
        described = self._response({"id": 7, "token": self.SECRET}).describe()

        assert self.SECRET not in described
        assert "redacted" in described
        assert "id" in described, "redaction must not swallow the rest of the body"

    def test_a_password_in_the_request_is_redacted(self) -> None:
        described = self._response(
            {"id": 7}, sent={"username": "someone", "password": "VikunjaQA123!"}
        ).describe()

        assert "VikunjaQA123!" not in described
        assert "someone" in described, "only the credential goes, not the context around it"

    def test_a_token_nested_in_a_collection_is_redacted(self) -> None:
        described = self._response({"tokens": [{"id": 1, "token": self.SECRET}]}).describe()

        assert self.SECRET not in described

    def test_the_body_itself_is_untouched(self) -> None:
        """Redaction is a property of the rendering, not of the answer. A
        test that mints a token still has to be able to use it."""
        response = self._response({"token": self.SECRET})

        assert response["token"] == self.SECRET
