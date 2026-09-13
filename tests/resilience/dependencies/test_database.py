"""The health check with the database gone."""

from __future__ import annotations

from typing import NamedTuple

import pytest

from vikunja_qa import stand
from vikunja_qa.config import Settings
from vikunja_qa.waiting import wait_until

pytestmark = pytest.mark.covers("RES")


class Answer(NamedTuple):
    """What the health check said once it stopped saying 200.

    `status` is None when nothing answered at all. Always truthy as a
    whole, so `wait_until` treats "answered badly" and "did not answer" the
    same way, which is what the claim needs; the assertion afterwards can
    still tell them apart.
    """

    status: int | None
    body: str


def test_the_health_check_stops_claiming_the_product_is_well(settings: Settings) -> None:
    """Orchestrators act on this check, so the one thing it must not do with
    its database gone is keep answering 200 OK.

    That is the whole claim, and it is deliberately the load-bearing one.
    The version before this asserted only that the answer carried no stack
    trace, and treated "nothing answered" as the outage being admitted — so
    the assertion it stood on was that the string "no answer" contains no
    stack trace, which no product could fail.

    What actually happens on this stand, recorded because it surprised us:
    the product does not answer 503. It accepts the connection and closes it
    again without a response after about three seconds. An orchestrator does
    read that as unhealthy, so the behaviour is defensible; a 503 with a
    short reason would be more useful to whoever is reading logs at the
    time, but a dropped connection is not a defect and is not written up as
    one. Both outcomes satisfy the claim above, and the assertion below
    still holds the answer to the leak rule if there ever is one.
    """

    def not_claiming_to_be_well() -> Answer | None:
        response = stand.health_of(settings.base_url)
        if response is None:
            return Answer(None, "")
        if response.status_code == 200:
            return None
        return Answer(response.status_code, response.text)

    with stand.stopped("db"):
        answer = wait_until(
            not_claiming_to_be_well,
            timeout=60,
            because="the health check stops claiming the product is well",
        )

    assert "goroutine" not in answer.body, (
        "the health check handed an internal stack trace to whoever asked: "
        f"{answer.status} {answer.body}"
    )
