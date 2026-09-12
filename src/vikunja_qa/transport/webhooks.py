"""Reader for the stand's webhook sink.

An outgoing webhook is the one effect the product cannot report on
itself: asking the API whether it fired only tells you what it intended.
The sink records what actually arrived, headers and body.

Each test points its webhooks at its own path, so recordings stay
separated while the suite runs in parallel.
"""

from __future__ import annotations

from typing import Any

import requests

from vikunja_qa.waiting import wait_until


class WebhookSink:
    def __init__(self, base_url: str, timeout: float = 10.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._session = requests.Session()

    def target_for(self, name: str) -> str:
        """The URL a webhook should be pointed at.

        Given to the product, so it must be the address the product can
        reach on the compose network, not the one the suite uses.
        """
        return f"http://webhook-receiver:8080/hook/{name}"

    def received(self, name: str) -> list[dict[str, Any]]:
        response = self._session.get(
            f"{self._base_url}/_recorded", params={"name": name}, timeout=self._timeout
        )
        response.raise_for_status()
        payload = response.json()
        return payload if isinstance(payload, list) else []

    def wait_for(self, name: str, *, timeout: float = 15.0, count: int = 1) -> list[dict[str, Any]]:
        """Wait until at least `count` calls have arrived on this path."""

        def enough() -> list[dict[str, Any]] | None:
            arrived = self.received(name)
            return arrived if len(arrived) >= count else None

        return wait_until(
            enough,
            timeout=timeout,
            because=f"{count} webhook call(s) reach {name}",
        )

    def clear(self, name: str | None = None) -> None:
        self._session.delete(
            f"{self._base_url}/_recorded",
            params={"name": name} if name else None,
            timeout=self._timeout,
        )
