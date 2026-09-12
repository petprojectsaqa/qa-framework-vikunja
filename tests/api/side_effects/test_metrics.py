"""Counters the product exports, read from the stand's Prometheus scrape.

Every counter here is instance-wide, and every other test running in
parallel moves it too. So nothing is ever asserted as an absolute value:
a check measures the difference around its own action.
"""

from __future__ import annotations

import pytest
import requests

from vikunja_qa.config import Settings
from vikunja_qa.scenes import SceneBuilder
from vikunja_qa.waiting import wait_until

pytestmark = pytest.mark.covers("ASY")

#: Prometheus scrapes the stand every five seconds; allow several scrapes.
SCRAPE_BUDGET = 30


def _scraped(settings: Settings, metric: str) -> float | None:
    """The latest scraped value of a metric, or None before its first scrape."""
    response = requests.get(
        f"{settings.prometheus_url}/api/v1/query", params={"query": metric}, timeout=10
    )
    response.raise_for_status()
    result = response.json().get("data", {}).get("result", [])
    return float(result[0]["value"][1]) if result else None


def test_creating_a_task_raises_the_task_counter(scene: SceneBuilder, settings: Settings) -> None:
    world = scene.project().done()

    # Waits on presence rather than on the value itself: a counter that
    # reads zero is falsy, and waiting on it directly would never return.
    wait_until(
        lambda: _scraped(settings, "vikunja_task_count") is not None,
        timeout=SCRAPE_BUDGET,
        because="Prometheus has scraped the task counter at least once",
    )
    before = _scraped(settings, "vikunja_task_count")
    assert before is not None

    created = world.owner.api.tasks.create(world.project_id, "a task worth counting")
    assert created.ok, created.describe()

    def risen() -> bool:
        now = _scraped(settings, "vikunja_task_count")
        return now is not None and now > before

    wait_until(risen, timeout=SCRAPE_BUDGET, because=f"the task counter rises above {before:g}")
