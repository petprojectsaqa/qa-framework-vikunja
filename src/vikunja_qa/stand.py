"""Taking parts of the stand away on purpose.

Used only by the resilience group, which asks what the product does when
something it depends on stops answering. That question cannot be asked
from inside the product, and it is the reason the stand is built out of
separate containers rather than one.

The container always comes back, failure or not, because a test that
leaves the stand broken takes every test after it down with it.
"""

from __future__ import annotations

import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import allure

from vikunja_qa.waiting import wait_until

COMPOSE_FILE = Path(__file__).resolve().parent.parent.parent / "docker" / "docker-compose.yml"

#: Never stop these. The product itself is the thing under test, and the
#: database holds everything every other test has built.
PROTECTED = frozenset({"vikunja"})


class StandControlError(RuntimeError):
    pass


def _compose(*args: str) -> str:
    result = subprocess.run(  # noqa: S603 - fixed binary, arguments built here
        ["docker", "compose", "-f", str(COMPOSE_FILE), *args],  # noqa: S607
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        raise StandControlError(f"docker compose {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def is_available() -> bool:
    try:
        _compose("ps", "--format", "{{.Service}}")
    except (StandControlError, FileNotFoundError, subprocess.SubprocessError):
        return False
    return True


def running_services() -> set[str]:
    return {
        line.strip()
        for line in _compose("ps", "--format", "{{.Service}}").splitlines()
        if line.strip()
    }


def _state_of(service: str) -> str:
    """`healthy`, `running`, `starting` or whatever compose reports."""
    listing = _compose("ps", "-a", "--format", "{{.Service}}|{{.State}}|{{.Health}}")
    for line in listing.splitlines():
        parts = line.split("|")
        if parts and parts[0].strip() == service:
            health = parts[2].strip() if len(parts) > 2 else ""
            return health or (parts[1].strip() if len(parts) > 1 else "")
    return "absent"


def wait_until_ready(service: str, timeout: float = 120) -> None:
    """Block until a restarted service is actually answering.

    Restarting a container is not the same as it being usable again, and
    handing a half-started dependency to the next test produces a failure
    that has nothing to do with what that test checks. The mail trap is
    the clearest case: it comes back empty and a registration sent a
    moment too early is simply gone.
    """

    def ready() -> bool | None:
        state = _state_of(service)
        return True if state in ("healthy", "running") else None

    wait_until(ready, timeout=timeout, because=f"{service} is answering again")


@contextmanager
def stopped(service: str) -> Iterator[None]:
    """Stop one container for the duration, then bring it back.

    Restoration runs in a finally block and is not conditional on the
    test passing: leaving the stand in pieces would turn one failure into
    a cascade.
    """
    if service in PROTECTED:
        raise StandControlError(
            f"{service} is not something the suite may stop; it would take everything else with it"
        )

    with allure.step(f"stop {service}"):
        _compose("stop", service)
    try:
        yield
    finally:
        with allure.step(f"start {service} again and wait for it"):
            _compose("start", service)
            wait_until_ready(service)
