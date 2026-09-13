"""The fixtures every product test layer draws on.

Registered as a pytest plugin from the root conftest, so they are part of
the framework rather than buried in a conftest file: importable, typed and
documented in one place.

Scoping follows the isolation rule in docs/strategy.md: what is shared and
read-only lives for the session, and what owns data lives for a single
test, because ownership is what keeps parallel tests from seeing each
other. None of these touches the stand until a test asks for it, which is
why the unit layer can load this plugin and still run with the stand off.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Protocol

import pytest

from vikunja_qa.actors.actor import Actor
from vikunja_qa.actors.factory import ActorFactory
from vikunja_qa.clients.calendar import CalendarClient
from vikunja_qa.config import Settings, get_settings
from vikunja_qa.contracts.baseline import Baseline
from vikunja_qa.contracts.spec import SpecIndex
from vikunja_qa.contracts.validator import ContractValidator, Mode
from vikunja_qa.db import Database
from vikunja_qa.scenes import SceneBuilder, build
from vikunja_qa.testing import discovery, state
from vikunja_qa.transport.client import ResponseHook
from vikunja_qa.transport.mailpit import MailpitClient
from vikunja_qa.transport.webhooks import WebhookSink

# --- environment ------------------------------------------------------------


@pytest.fixture(scope="session")
def settings() -> Settings:
    return get_settings()


@pytest.fixture(scope="session")
def worker_id() -> str:
    """Which xdist worker this is, or `main` in a single process.

    Threaded into generated names so a row in the database points back at
    both the test and the worker that created it.
    """
    return os.environ.get("PYTEST_XDIST_WORKER", "main")


# --- services around the product -------------------------------------------


@pytest.fixture(scope="session")
def mailpit(settings: Settings) -> MailpitClient:
    return MailpitClient(settings.mailpit_url, timeout=settings.mail_timeout)


@pytest.fixture(scope="session")
def db(settings: Settings) -> Database:
    """Read-only access to the product's database, for the claims the API
    cannot settle: orphaned rows, a refused write that half applied, a
    secret stored in the clear."""
    return Database(settings.db_dsn)


@pytest.fixture(scope="session")
def webhooks(settings: Settings) -> WebhookSink:
    return WebhookSink(settings.webhook_url)


@pytest.fixture
def hook_name(request: pytest.FixtureRequest, worker_id: str) -> str:
    """A webhook path unique to this test, so parallel runs never read each
    other's deliveries."""
    return f"{request.node.name}-{worker_id}".replace("[", "-").replace("]", "")


# --- contracts --------------------------------------------------------------


@pytest.fixture(scope="session")
def specs() -> tuple[SpecIndex, ...]:
    """Both API descriptions, from the running instance rather than the
    product's repository, so the build that is up is the build checked."""
    return discovery.descriptions()


@pytest.fixture(scope="session")
def contracts(
    pytestconfig: pytest.Config, settings: Settings, specs: tuple[SpecIndex, ...]
) -> ContractValidator:
    """Strict by default: a response contradicting its own contract fails
    the test that produced it. The baseline absorbs deviations already
    written up in docs/findings, so only new ones break a run."""
    validator = ContractValidator(
        list(specs), mode=Mode(settings.contract_mode), baseline=Baseline()
    )
    pytestconfig.stash[state.VALIDATOR] = validator
    return validator


@pytest.fixture(scope="session")
def transport_hooks(contracts: ContractValidator) -> list[ResponseHook]:
    """Installed on every client the suite builds, which is what makes
    contract coverage a by-product of ordinary testing."""
    return [contracts]


@pytest.fixture
def contracts_collect_only(contracts: ContractValidator) -> Iterator[ContractValidator]:
    """Record contract deviations for this test instead of failing on them.

    For tests that walk error paths they did not choose, such as the
    generated sweep. The deviations still reach the end-of-run report.
    """
    with contracts.collecting():
        yield contracts


@pytest.fixture
def contracts_suspended(contracts: ContractValidator) -> Iterator[ContractValidator]:
    """Check no contracts for this test.

    For tests that deliberately call something no description covers, to
    prove it is refused. That call is not a finding and stays out of the
    report.
    """
    with contracts.suspended():
        yield contracts


# --- actors and scenes ------------------------------------------------------


@pytest.fixture
def actors(
    request: pytest.FixtureRequest,
    settings: Settings,
    mailpit: MailpitClient,
    worker_id: str,
    transport_hooks: list[ResponseHook],
) -> ActorFactory:
    """A per-test source of fresh accounts.

    No teardown, on purpose. Accounts are never reused, so leftovers are
    inert, and after a red run the data that produced it is still there
    to inspect.
    """
    return ActorFactory(
        settings, mailpit, label=f"{request.node.name}{worker_id}", hooks=transport_hooks
    )


@pytest.fixture(scope="module")
def module_actors(
    request: pytest.FixtureRequest,
    settings: Settings,
    mailpit: MailpitClient,
    worker_id: str,
    transport_hooks: list[ResponseHook],
) -> ActorFactory:
    """Accounts shared by every test in one module.

    A matrix world with six accounts in it costs more to build than the
    checks cost to run, so a module may build it once. It stays isolated
    from every other module and worker because the accounts are unique to
    it; tests that mutate create their own objects inside it.
    """
    return ActorFactory(
        settings, mailpit, label=f"{request.node.name}{worker_id}", hooks=transport_hooks
    )


@pytest.fixture
def scene(actors: ActorFactory) -> SceneBuilder:
    """Declarative setup. Creates the owning account at once, since every
    scene has one, and nothing else until the test asks."""
    return build(actors)


@pytest.fixture(scope="module")
def module_scene(module_actors: ActorFactory) -> SceneBuilder:
    return build(module_actors)


@pytest.fixture
def anon(actors: ActorFactory) -> Actor:
    """A caller with no credential at all."""
    return actors.anonymous()


@pytest.fixture
def owner(actors: ActorFactory) -> Actor:
    """A fresh account that will own whatever the test creates."""
    return actors.user("owner")


class CalendarOpener(Protocol):
    """Opens the calendar door as an actor. The secret defaults to the
    account password; a CalDAV token or an API token goes in its place.

    Declared here rather than beside the client because it names an actor,
    and actors sit above clients.
    """

    def __call__(self, actor: Actor, secret: str | None = None) -> CalendarClient: ...


@pytest.fixture(scope="session")
def calendar_for(settings: Settings) -> CalendarOpener:
    """The CalDAV door, opened as an actor.

    Kept outside the contract hooks on purpose: the API descriptions say
    nothing about CalDAV, so there is no contract to hold its answers to.
    """

    def open_door(actor: Actor, secret: str | None = None) -> CalendarClient:
        return CalendarClient.for_account(settings, actor.username, secret or actor.password)

    return open_door


@pytest.fixture(scope="session")
def calendar_anonymous(settings: Settings) -> CalendarClient:
    """The CalDAV door with no credential offered at all."""
    return CalendarClient.anonymous(settings)


@pytest.fixture
def outsider(actors: ActorFactory) -> Actor:
    """A fresh account with no relationship to the test's data: the actor
    that proves an authorization check checks anything."""
    return actors.user("outsider")
