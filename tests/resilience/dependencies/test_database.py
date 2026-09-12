"""The health check with the database gone."""

from __future__ import annotations

import pytest

from vikunja_qa import stand
from vikunja_qa.config import Settings
from vikunja_qa.waiting import wait_until

pytestmark = pytest.mark.covers("RES")


def test_the_health_check_admits_the_outage_without_revealing_internals(
    settings: Settings,
) -> None:
    """Orchestrators act on this check, so it has to tell the truth, and the
    failure it reports must not describe the product's internals to whoever
    asks."""

    def admitted() -> str | None:
        response = stand.health_of(settings.base_url)
        if response is None:
            return "no answer"
        if response.status_code == 200:
            return None
        return f"{response.status_code}: {response.text}"

    with stand.stopped("db"):
        answer = wait_until(
            admitted, timeout=60, because="the health check stops claiming the product is well"
        )

    assert "goroutine" not in answer, (
        f"the health check handed an internal stack trace to whoever asked:\n{answer}"
    )
