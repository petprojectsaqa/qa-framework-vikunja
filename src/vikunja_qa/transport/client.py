"""The single place the suite talks HTTP.

Responsibilities: build the request, stamp it with a credential, send it,
wrap the result, and record what happened in the report. It knows nothing
about projects or tasks, and it never decides whether a response is
correct. Both of those belong to layers above it.

Contract validation hangs off the hook at the end of `request`, which is
why contract coverage costs the suite nothing: every call made by every
test passes through here. See docs/strategy.md, section 6.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from typing import Any

import allure
import requests

from vikunja_qa.auth.strategies import Anonymous, AuthStrategy
from vikunja_qa.transport.response import ApiResponse

ResponseHook = Callable[[ApiResponse], None]


class HttpClient:
    """A client bound to one base URL and one credential.

    Bound rather than parameterised on purpose: a test reads better as
    `owner.v1.get(...)` than as `client.get(..., auth=owner)`, and an
    accidental credential mix-up becomes impossible.
    """

    def __init__(
        self,
        base_url: str,
        auth: AuthStrategy | None = None,
        *,
        timeout: float = 15.0,
        session: requests.Session | None = None,
        attach_traffic: bool = True,
        hooks: list[ResponseHook] | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._auth = auth or Anonymous()
        self._timeout = timeout
        self._session = session or requests.Session()
        self._attach = attach_traffic
        self._hooks = hooks if hooks is not None else []

    # --- derivation ---------------------------------------------------------

    def with_auth(self, auth: AuthStrategy) -> HttpClient:
        """Same target, different credential. Used by the access matrix to
        replay one request as every actor in turn."""
        return HttpClient(
            self._base_url,
            auth,
            timeout=self._timeout,
            session=self._session,
            attach_traffic=self._attach,
            hooks=self._hooks,
        )

    def with_base(self, base_url: str) -> HttpClient:
        """Same credential, different API version."""
        return HttpClient(
            base_url,
            self._auth,
            timeout=self._timeout,
            session=self._session,
            attach_traffic=self._attach,
            hooks=self._hooks,
        )

    def add_hook(self, hook: ResponseHook) -> None:
        self._hooks.append(hook)

    @property
    def auth(self) -> AuthStrategy:
        return self._auth

    @property
    def base_url(self) -> str:
        return self._base_url

    # --- verbs --------------------------------------------------------------

    def get(self, path: str, **kwargs: Any) -> ApiResponse:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> ApiResponse:
        return self.request("POST", path, **kwargs)

    def put(self, path: str, **kwargs: Any) -> ApiResponse:
        return self.request("PUT", path, **kwargs)

    def patch(self, path: str, **kwargs: Any) -> ApiResponse:
        return self.request("PATCH", path, **kwargs)

    def delete(self, path: str, **kwargs: Any) -> ApiResponse:
        return self.request("DELETE", path, **kwargs)

    # --- the one implementation --------------------------------------------

    def request(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        files: Any = None,
        data: Any = None,
    ) -> ApiResponse:
        url = path if path.startswith("http") else f"{self._base_url}/{path.lstrip('/')}"

        final_headers: dict[str, str] = {"Accept": "application/json"}
        if headers:
            final_headers.update(headers)
        # Auth goes on last so a test can still strip or override it
        # deliberately by passing its own Authorization header.
        if "Authorization" not in final_headers:
            self._auth.apply(final_headers)

        started = time.perf_counter()
        raw = self._session.request(
            method,
            url,
            json=json,
            params=params,
            headers=final_headers,
            files=files,
            data=data,
            timeout=self._timeout,
        )
        elapsed_ms = (time.perf_counter() - started) * 1000

        try:
            body: Any = raw.json()
        except ValueError:
            body = raw.text

        response = ApiResponse(
            method=method.upper(),
            url=url,
            status=raw.status_code,
            headers=dict(raw.headers),
            body=body,
            elapsed_ms=elapsed_ms,
            request_body=json if json is not None else data,
            auth_label=self._auth.label,
            text=raw.text,
        )

        self._record(response)
        for hook in self._hooks:
            hook(response)
        return response

    # --- reporting ----------------------------------------------------------

    def _record(self, response: ApiResponse) -> None:
        short_url = response.url.replace(self._base_url, "")
        title = f"{response.method} {short_url} -> {response.status}"
        with allure.step(title):
            if self._attach:
                allure.attach(
                    response.describe(),
                    name=title,
                    attachment_type=allure.attachment_type.TEXT,
                )
