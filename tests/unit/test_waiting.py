"""Tests for the waiting helper.

It replaces every fixed pause in the suite, so a mistake here would show
up as unexplained flakiness everywhere else. No stand required.
"""

from __future__ import annotations

import time

import pytest

from vikunja_qa.waiting import WaitTimeoutError, eventually_equals, wait_until


def test_returns_as_soon_as_the_condition_holds() -> None:
    calls = []

    def condition() -> str | None:
        calls.append(1)
        return "ready" if len(calls) >= 3 else None

    assert wait_until(condition, timeout=5, because="the probe settles") == "ready"
    assert len(calls) == 3


def test_returns_immediately_when_already_true() -> None:
    started = time.monotonic()

    wait_until(lambda: True, timeout=5, because="it is already true")

    assert time.monotonic() - started < 0.2, "a condition already true must not sleep"


def test_timeout_names_what_it_was_waiting_for() -> None:
    """A timeout that only reports a duration tells the reader nothing."""
    with pytest.raises(WaitTimeoutError) as raised:
        wait_until(lambda: None, timeout=0.3, because="the webhook arrives")

    assert "the webhook arrives" in str(raised.value)


def test_a_probe_that_raises_does_not_end_the_wait() -> None:
    """An effect in flight can make the probe itself fail briefly."""
    calls = []

    def flaky() -> bool | None:
        calls.append(1)
        if len(calls) < 3:
            raise ConnectionError("not up yet")
        return True

    assert wait_until(flaky, timeout=5, because="the service answers") is True


def test_a_probe_that_always_raises_reports_the_last_error() -> None:
    with pytest.raises(WaitTimeoutError) as raised:
        wait_until(
            lambda: (_ for _ in ()).throw(ConnectionError("refused")),
            timeout=0.3,
            because="the service answers",
        )

    assert "refused" in str(raised.value)


def test_backoff_keeps_the_number_of_attempts_sane() -> None:
    """Polling must not spin: a tight loop would hammer the product."""
    calls = []
    with pytest.raises(WaitTimeoutError):
        wait_until(lambda: calls.append(1), timeout=1.0, because="never")

    assert len(calls) < 30, f"{len(calls)} attempts in a second is a spin, not a poll"


class TestEventuallyEquals:
    def test_passes_once_the_value_settles(self) -> None:
        seen = []

        def probe() -> int:
            seen.append(1)
            return len(seen)

        eventually_equals(probe, 3, timeout=5, because="the counter reaches three")

    def test_failure_reports_the_value_it_kept_seeing(self) -> None:
        """The whole reason this exists rather than wait_until: knowing
        what the value actually was is most of the diagnosis."""
        with pytest.raises(WaitTimeoutError) as raised:
            eventually_equals(lambda: 7, 9, timeout=0.3, because="the counter moves")

        message = str(raised.value)
        assert "expected 9" in message
        assert "last saw 7" in message
