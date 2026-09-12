"""Doing several things at the same instant, deliberately.

A race only happens when the calls overlap. Handing work to a thread pool
does not arrange that: the first thread can be finished before the last
one starts, and that gap is exactly what lets a product with a race in it
look correct. So every call gets a thread, all of them wait on a barrier,
and the barrier releases them together.

The results come back in the order the calls were given, however they
finished, so a test can say which caller got what.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Sequence


class NotSimultaneousError(RuntimeError):
    """Raised when the callers could not be lined up or did not all finish.

    Distinct from a test failure: it means the race was never staged, so
    whatever the test was going to observe was not observed.
    """


def at_the_same_time[T](calls: Sequence[Callable[[], T]], *, timeout: float = 60) -> list[T]:
    """Run every call on its own thread, released together.

    Raises whatever the first failing call raised, once every thread has
    finished, so a failure is never reported while other threads are still
    touching the product.
    """
    if len(calls) < 2:
        raise NotSimultaneousError(f"{len(calls)} call is not a race; give at least two")

    results: list[T | None] = [None] * len(calls)
    failures: list[tuple[int, BaseException]] = []
    ready = threading.Barrier(len(calls), timeout=timeout)

    def run(index: int, call: Callable[[], T]) -> None:
        try:
            ready.wait()
            results[index] = call()
        except BaseException as exc:  # noqa: BLE001 - carried to the caller's thread
            failures.append((index, exc))

    threads = [
        threading.Thread(target=run, args=(index, call), name=f"at-the-same-time-{index}")
        for index, call in enumerate(calls)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout)

    still_running = [thread.name for thread in threads if thread.is_alive()]
    if still_running:
        raise NotSimultaneousError(
            f"{len(still_running)} callers had not finished in {timeout:.0f}s"
        )
    if failures:
        index, exc = failures[0]
        raise exc from NotSimultaneousError(f"caller {index} of {len(calls)} failed")
    return list(results)  # type: ignore[arg-type]
