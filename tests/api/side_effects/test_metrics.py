"""Counters the product exports, read from the stand's Prometheus scrape.

Every metric here is instance-wide, and every other test running at the
same time moves it too. So nothing is asserted as an absolute value: a
check measures the change around its own action.

Which metric matters. They are all gauges of how many things exist, so
most of them fall as well as rise: the task gauge drops whenever any other
test deletes a task, and there is no window in a parallel run where it can
be expected to have gone up. The user gauge is the exception, because this
suite never deletes an account, by design. See docs/strategy.md, section 1.
"""

from __future__ import annotations

import pytest
import requests

from vikunja_qa.actors.factory import ActorFactory
from vikunja_qa.config import Settings
from vikunja_qa.waiting import wait_until

pytestmark = pytest.mark.covers("ASY")

#: Prometheus scrapes the stand every five seconds; allow several scrapes.
SCRAPE_BUDGET = 30

USERS = "vikunja_user_count"


def _scraped(settings: Settings, metric: str) -> float | None:
    """The latest scraped value of a metric, or None before its first scrape."""
    response = requests.get(
        f"{settings.prometheus_url}/api/v1/query", params={"query": metric}, timeout=10
    )
    response.raise_for_status()
    result = response.json().get("data", {}).get("result", [])
    return float(result[0]["value"][1]) if result else None


@pytest.mark.smoke
def test_registering_an_account_raises_the_user_counter(
    actors: ActorFactory, settings: Settings
) -> None:
    """Three moving parts in one check: the product counts, it exposes the
    count, and Prometheus collects it."""
    # Waits on presence rather than on the value itself: a gauge that reads
    # zero is falsy, and waiting on it directly would never return.
    wait_until(
        lambda: _scraped(settings, USERS) is not None,
        timeout=SCRAPE_BUDGET,
        because="Prometheus has scraped the user counter at least once",
    )
    before = _scraped(settings, USERS)
    assert before is not None

    actors.user("counted")

    def risen() -> bool:
        now = _scraped(settings, USERS)
        return now is not None and now > before

    wait_until(risen, timeout=SCRAPE_BUDGET, because=f"the user counter rises above {before:g}")
