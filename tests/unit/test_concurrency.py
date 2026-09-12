"""The helper that stages a race.

If it staged them badly, a concurrency test would pass by never
overlapping, which is the one failure mode that looks like success.
"""

from __future__ import annotations

import threading
import time

import pytest

from vikunja_qa.concurrency import NotSimultaneousError, at_the_same_time


def test_the_callers_really_do_overlap() -> None:
    """Each caller records the moment it started; the spread between the
    first and the last is what the barrier is for."""
    started: list[float] = []
    lock = threading.Lock()

    def note() -> float:
        moment = time.monotonic()
        with lock:
            started.append(moment)
        time.sleep(0.05)
        return moment

    at_the_same_time([note] * 8)

    assert len(started) == 8
    assert max(started) - min(started) < 0.05, (
        "the callers were staggered, so a race would not be observed"
    )


def test_results_come_back_in_the_order_the_calls_were_given() -> None:
    """However they finish. A test needs to know which caller got what."""

    def slow_then(value: int) -> int:
        time.sleep(0.05 if value == 0 else 0)
        return value

    assert at_the_same_time([lambda: slow_then(0), lambda: slow_then(1)]) == [0, 1]


def test_one_caller_is_not_a_race() -> None:
    with pytest.raises(NotSimultaneousError, match="at least two"):
        at_the_same_time([lambda: None])


def test_a_failure_in_one_caller_reaches_the_test() -> None:
    def explode() -> None:
        raise ValueError("the product said no")

    with pytest.raises(ValueError, match="the product said no"):
        at_the_same_time([explode, lambda: None])


def test_every_caller_finishes_before_a_failure_is_reported() -> None:
    """Otherwise the failure surfaces while other threads are still
    touching the product, and the next test inherits the mess."""
    finished: list[str] = []

    def explode() -> None:
        raise ValueError("first")

    def slow() -> None:
        time.sleep(0.1)
        finished.append("slow")

    with pytest.raises(ValueError, match="first"):
        at_the_same_time([explode, slow])

    assert finished == ["slow"]
