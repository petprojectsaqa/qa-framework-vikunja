"""Authenticated requests with the key-value store gone."""

from __future__ import annotations

import time

import pytest
import requests

from vikunja_qa import stand
from vikunja_qa.scenes import SceneBuilder

pytestmark = pytest.mark.covers("RES")

#: Deliberately generous. The question is not whether the request is slow
#: without its cache but whether it answers at all.
ANSWER_BUDGET_S = 25


@pytest.mark.finding("VKJ-011")
@pytest.mark.xfail(
    reason=(
        "VKJ-011: with Redis as the key-value store, an outage makes authenticated requests "
        "hang rather than fail, so the connection pool drains and one dependency's outage "
        "becomes the product's"
    ),
    # Not strict, unlike every other xfail in the suite, and this is the
    # exception rather than the default: what it measures is how long an
    # answer takes. A machine that happens to answer inside the budget once
    # would make an unexpected pass, and a red run for that reason says
    # nothing about the product. `xfail_strict` in pyproject.toml is what
    # makes the rest of them strict.
    strict=False,
)
def test_losing_redis_degrades_requests_instead_of_hanging_them(scene: SceneBuilder) -> None:
    world = scene.done()
    impatient = world.owner.v1.with_timeout(ANSWER_BUDGET_S)

    with stand.stopped("redis"):
        started = time.monotonic()
        try:
            answered = impatient.get("/user")
        except requests.RequestException as exc:
            waited = time.monotonic() - started
            pytest.fail(
                f"no answer in {waited:.0f}s without the key-value store "
                f"({type(exc).__name__}); a cache outage must not block a request outright"
            )

    assert answered.status < 500, f"the product failed without its cache\n{answered.describe()}"
