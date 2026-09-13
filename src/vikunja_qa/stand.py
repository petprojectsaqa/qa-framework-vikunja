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
import requests

from vikunja_qa.waiting import wait_until

COMPOSE_FILE = Path(__file__).resolve().parent.parent.parent / "docker" / "docker-compose.yml"

#: Never stop these. The product is the thing under test, so taking it away
#: leaves nothing to ask a question of. Its dependencies are all fair game,
#: the database included: its data lives in a volume that outlives a stop,
#: which is what makes "take the database away" a test rather than a reset.
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
    the clearest case: it comes back empty, and a registration sent a
    moment too early is simply gone.

    Which is why `running` is not accepted as an answer. Compose reports
    that the instant the container process exists, long before anything is
    listening, so every service the suite stops carries a healthcheck in
    docker-compose.yml and this waits for that. A service without one waits
    for nothing, and this used to be exactly that: mailpit had no
    healthcheck, so the helper written to stop the mail race returned true
    on its first poll.
    """

    def ready() -> bool | None:
        return True if _state_of(service) == "healthy" else None

    wait_until(ready, timeout=timeout, because=f"{service} reports itself healthy again")


def health_of(base_url: str, timeout: float = 5) -> requests.Response | None:
    """The product's own health check, or None when nothing answers at all."""
    try:
        return requests.get(f"{base_url.rstrip('/')}/health", timeout=timeout)
    except requests.RequestException:
        return None


def wait_until_healthy(base_url: str, timeout: float = 120) -> None:
    """Block until the product reports itself healthy.

    A dependency's container running again is not the product having
    noticed. It reconnects on its own schedule, and the next test should
    not be the one that finds out it has not yet.
    """

    def healthy() -> bool | None:
        response = health_of(base_url)
        return True if response is not None and response.status_code == 200 else None

    wait_until(healthy, timeout=timeout, because="the product reports itself healthy again")


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
