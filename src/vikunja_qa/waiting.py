"""Waiting for something to become true.

The suite contains no fixed pauses. A pause is both slower and less
reliable than it looks: on a quick machine it wastes the difference, on a
loaded one it still flakes. Polling a condition with an explicit deadline
removes both problems at once.

Every use must say how long it is prepared to wait and why, which is what
the `because` argument is for. It ends up in the failure message, so a
timeout explains itself instead of just saying that time ran out.
"""

from __future__ import annotations

import time
from collections.abc import Callable

import allure

#: Poll fast at first, then back off. Most effects on this stand land in
#: well under a second, so the first few polls usually settle it.
FIRST_INTERVAL = 0.05
MAX_INTERVAL = 0.5
BACKOFF = 1.5


class WaitTimeoutError(AssertionError):
    """Deliberately not named TimeoutError: that name is taken by a
    builtin which this does not inherit from, and shadowing it would make
    every `except TimeoutError` in the suite ambiguous."""

    pass


def wait_until[T](
    condition: Callable[[], T | None],
    *,
    timeout: float,
    because: str,
    interval: float = FIRST_INTERVAL,
) -> T:
    """Poll until `condition` returns something truthy, then return it.

    Raises with an explanation, not just a duration, when the deadline
    passes.
    """
    deadline = time.monotonic() + timeout
    attempts = 0
    last_error: Exception | None = None

    with allure.step(f"wait up to {timeout:.0f}s until {because}"):
        while time.monotonic() < deadline:
            attempts += 1
            try:
                result = condition()
            except Exception as exc:  # noqa: BLE001 - a probe may fail while the effect is in flight
                last_error = exc
                result = None
            if result:
                return result
            time.sleep(interval)
            interval = min(interval * BACKOFF, MAX_INTERVAL)

    waited = f"{timeout:.0f}s, {attempts} attempts"
    if last_error is not None:
        raise WaitTimeoutError(f"waited {waited} for {because}; last probe raised {last_error!r}")
    raise WaitTimeoutError(f"waited {waited} for {because}, and it never became true")


def eventually_equals[T](
    probe: Callable[[], T],
    expected: T,
    *,
    timeout: float,
    because: str,
) -> None:
    """Wait for a value to settle, and say what it was when it did not.

    Separate from `wait_until` because an equality that never holds
    should report the value it kept seeing, not just that it kept
    failing.
    """
    deadline = time.monotonic() + timeout
    interval = FIRST_INTERVAL
    seen: T | None = None

    with allure.step(f"wait up to {timeout:.0f}s until {because}"):
        while time.monotonic() < deadline:
            seen = probe()
            if seen == expected:
                return
            time.sleep(interval)
            interval = min(interval * BACKOFF, MAX_INTERVAL)

    raise WaitTimeoutError(
        f"waited {timeout:.0f}s for {because}; expected {expected!r}, last saw {seen!r}"
    )
