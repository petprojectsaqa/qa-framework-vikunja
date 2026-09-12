"""Fixtures for the resilience layer: the product with a dependency taken away.

Every test here stops a container the whole stand shares, which sets three
rules, all enforced rather than hoped for.

The layer runs only when asked. The suite's plugin leaves it out unless
`--resilience` is given, because a main pipeline that is sometimes red
for infrastructure reasons is worth less than a smaller one that is
always honest.

It runs in one process. The plugin refuses `--resilience` together with
`-n`: an outage cannot be confined to the test that caused it.

Every test hands the stand back healthy, pass or fail. Recovery sits in
fixture teardown rather than at the end of each test, because a test that
fails mid-outage would otherwise skip its own recovery, and one failure
would turn into a cascade that hides its own cause.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from vikunja_qa import stand
from vikunja_qa.config import Settings
from vikunja_qa.contracts.validator import ContractValidator


@pytest.fixture(scope="session", autouse=True)
def _stand_under_control() -> None:
    """Fail loudly when the containers cannot be controlled from here.

    Not a skip: this layer only runs when someone asked for it, and a run
    that was asked for and quietly did nothing would read as a pass.
    """
    if not stand.is_available():
        pytest.fail(
            "docker compose cannot reach the stand from this shell, so no dependency "
            "can be stopped; run the layer where `docker compose ps` works",
            pytrace=False,
        )


@pytest.fixture(autouse=True)
def _contracts_out_of_scope(contracts: ContractValidator) -> Iterator[None]:
    """Contract checks stay out of this layer.

    What a response looks like during an outage is exactly the question
    each test here asks, explicitly. Left on, the validator would answer a
    different question first, and a test would fail on an undeclared status
    before it reached the assertion it exists for.
    """
    with contracts.suspended():
        yield


@pytest.fixture(autouse=True)
def _stand_restored(settings: Settings) -> Iterator[None]:
    """Wait, after every test, until the product reports itself healthy."""
    yield
    stand.wait_until_healthy(settings.base_url)
