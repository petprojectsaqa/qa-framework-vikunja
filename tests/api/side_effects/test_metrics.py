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
from vikunja_qa.db import Database
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
def test_the_user_counter_tracks_the_accounts_that_exist(
    actors: ActorFactory, settings: Settings, db: Database
) -> None:
    """Four moving parts in one check: the product counts accounts, counts
    them right, exposes the count, and Prometheus collects it.

    Held against the table rather than against itself. "The gauge went up
    after I registered someone" cannot be attributed under `-n 8`, where
    seven other workers are registering accounts continuously: the gauge
    rises within the budget whatever this test did, so the old version of
    this check passed for a reason that had nothing to do with its name.

    Two independent sources of truth instead. The gauge has to reach the
    number of accounts that existed before this test added one — which it
    cannot do without counting ours or someone else's, so a registration
    path that forgets to count shows up as the gauge falling behind. And it
    must never exceed the number of rows there are, which is what would
    happen if it counted something twice or counted deletions wrongly.
    """
    # Waits on presence rather than on the value itself: a gauge that reads
    # zero is falsy, and waiting on it directly would never return.
    wait_until(
        lambda: _scraped(settings, USERS) is not None,
        timeout=SCRAPE_BUDGET,
        because="Prometheus has scraped the user counter at least once",
    )
    rows_before = db.count("select count(*) from users")

    actors.user("counted")

    def caught_up() -> bool:
        scraped = _scraped(settings, USERS)
        return scraped is not None and scraped > rows_before

    wait_until(
        caught_up,
        timeout=SCRAPE_BUDGET,
        because=f"the gauge counts more than the {rows_before} accounts that existed before",
    )

    scraped = _scraped(settings, USERS)
    assert scraped is not None, "the gauge stopped being scraped mid-test"
    rows_now = db.count("select count(*) from users")
    assert scraped <= rows_now, (
        f"the gauge reports {scraped} accounts while the table holds {rows_now}, "
        "so it is counting something that is not there"
    )
