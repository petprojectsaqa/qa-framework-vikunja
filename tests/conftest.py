"""Fixtures shared by the whole suite.

Scoping follows the isolation rule in docs/strategy.md, section 1:
anything shared and read-only lives for the session, while anything that
owns data is per test, because ownership is what keeps parallel tests
from seeing each other.
"""

from __future__ import annotations

import os
from urllib.parse import urlsplit

import pytest

from vikunja_qa.actors.actor import Actor
from vikunja_qa.actors.factory import ActorFactory
from vikunja_qa.config import Settings, get_settings
from vikunja_qa.contracts.baseline import Baseline
from vikunja_qa.contracts.spec import SpecIndex
from vikunja_qa.contracts.validator import ContractValidator, Mode
from vikunja_qa.db import Database
from vikunja_qa.scenes import SceneBuilder, build
from vikunja_qa.transport.client import ResponseHook
from vikunja_qa.transport.mailpit import MailpitClient
from vikunja_qa.transport.webhooks import WebhookSink


@pytest.fixture(scope="session")
def settings() -> Settings:
    return get_settings()


@pytest.fixture(scope="session")
def worker_id() -> str:
    """Which xdist worker this is, or `main` when running single-process.

    Threaded into generated names so a row in the database points back at
    both the test and the worker that made it.
    """
    return os.environ.get("PYTEST_XDIST_WORKER", "main")


@pytest.fixture(scope="session")
def mailpit(settings: Settings) -> MailpitClient:
    return MailpitClient(settings.mailpit_url, timeout=settings.mail_timeout)


@pytest.fixture(scope="session")
def db(settings: Settings) -> Database:
    """Read-only access to the product's database.

    For the claims the API cannot settle on its own: orphaned rows, a
    rejected bulk write that half applied, a secret stored in the clear.
    """
    return Database(settings.db_dsn)


@pytest.fixture(scope="session")
def webhooks(settings: Settings) -> WebhookSink:
    return WebhookSink(settings.webhook_url)


@pytest.fixture
def hook_name(request: pytest.FixtureRequest, worker_id: str) -> str:
    """A webhook path unique to this test, so parallel runs do not mix
    each other's deliveries."""
    return f"{request.node.name}-{worker_id}".replace("[", "-").replace("]", "")


# --- contracts -------------------------------------------------------------


@pytest.fixture(scope="session")
def specs(settings: Settings) -> list[SpecIndex]:
    """Both descriptions, taken from the running instance.

    Fetched rather than read from the product's repository so the suite
    checks the build that is actually up.
    """
    return [
        SpecIndex.from_url(
            f"{settings.api_v1}/docs.json",
            label="v1",
            base_path=urlsplit(settings.api_v1).path,
        ),
        SpecIndex.from_url(
            f"{settings.api_v2}/openapi.json",
            label="v2",
            base_path=urlsplit(settings.api_v2).path,
        ),
    ]


@pytest.fixture(scope="session")
def contracts(
    request: pytest.FixtureRequest, settings: Settings, specs: list[SpecIndex]
) -> ContractValidator:
    """Strict by default: a response that contradicts its own contract
    fails the test that produced it. The baseline is what makes that
    workable, absorbing the deviations already written up in
    docs/findings so only new ones break the run.

    Publishing the validator here rather than from an autouse fixture is
    deliberate: it keeps the unit tests from pulling the specifications
    over the network, so they really do run without a stand.
    """
    validator = ContractValidator(specs, mode=Mode(settings.contract_mode), baseline=Baseline())
    request.config._vqa_contracts = validator  # type: ignore[attr-defined]
    return validator


@pytest.fixture(scope="session")
def transport_hooks(contracts: ContractValidator) -> list[ResponseHook]:
    """Installed on every client the suite builds, which is what makes
    contract coverage a by-product of ordinary testing."""
    return [contracts]


# --- actors ----------------------------------------------------------------


@pytest.fixture
def actors(
    request: pytest.FixtureRequest,
    settings: Settings,
    mailpit: MailpitClient,
    worker_id: str,
    transport_hooks: list[ResponseHook],
) -> ActorFactory:
    """Per-test source of accounts.

    No teardown on purpose. Accounts are never reused, so leftovers are
    inert, and skipping cleanup keeps the suite parallel and its failures
    inspectable: after a red run the data that produced it is still there.
    """
    label = f"{request.node.name}{worker_id}"
    return ActorFactory(settings, mailpit, label=label, hooks=transport_hooks)


@pytest.fixture
def anon(actors: ActorFactory) -> Actor:
    """A caller with no credential."""
    return actors.anonymous()


@pytest.fixture
def owner(actors: ActorFactory) -> Actor:
    """A fresh account that will own whatever the test creates."""
    return actors.user("owner")


@pytest.fixture
def contracts_collect_only(contracts: ContractValidator):  # noqa: ANN201
    """Record contract deviations for this test instead of failing on them.

    Used by suites that walk error paths on purpose. The deviations still
    reach the end-of-run report.
    """
    with contracts.collecting():
        yield contracts


@pytest.fixture
def contracts_suspended(contracts: ContractValidator):  # noqa: ANN201
    """Check no contracts for this test.

    For tests that deliberately make a call no description covers, in
    order to prove it is refused. Such a call is not a finding, so it
    should not reach the report.
    """
    with contracts.suspended():
        yield contracts


@pytest.fixture(scope="module")
def module_actors(
    request: pytest.FixtureRequest,
    settings: Settings,
    mailpit: MailpitClient,
    worker_id: str,
    transport_hooks: list[ResponseHook],
) -> ActorFactory:
    """Accounts shared by every test in one module.

    The access matrix needs a world with six accounts in it, and building
    that per parametrised row costs more than the checks themselves. One
    module owning one world is still isolated from every other module and
    every other worker, because the accounts are unique to it; rows that
    mutate create their own task inside the shared project.
    """
    label = f"{request.node.name}{worker_id}"
    return ActorFactory(settings, mailpit, label=label, hooks=transport_hooks)


@pytest.fixture(scope="module")
def module_scene(module_actors: ActorFactory) -> SceneBuilder:
    return build(module_actors)


@pytest.fixture
def scene(actors: ActorFactory) -> SceneBuilder:
    """Declarative setup. Creates the owning account immediately, since
    every scene has one, and nothing else until the test asks."""
    return build(actors)


@pytest.fixture
def outsider(actors: ActorFactory) -> Actor:
    """A fresh account with no relationship to the test's data.

    The actor that proves an authorization check actually checks
    something.
    """
    return actors.user("outsider")


# --- browser ---------------------------------------------------------------


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args: dict) -> dict:  # noqa: ANN001
    """Record a trace and a video only when something goes wrong.

    Keeping them always would slow every run for the sake of the rare
    failure; keeping none would make the rare failure a guessing game.
    """
    return {**browser_context_args, "viewport": {"width": 1400, "height": 900}}


# --- reporting -------------------------------------------------------------


def pytest_terminal_summary(terminalreporter: pytest.TerminalReporter) -> None:
    """Print what the contract pass learned.

    Under xdist each worker keeps its own tally, so these figures are per
    worker; the CI job merges them from the Allure results.
    """
    validator: ContractValidator | None = getattr(terminalreporter.config, "_vqa_contracts", None)
    if validator is None:
        return

    coverage = validator.coverage()
    terminalreporter.write_sep("-", "contract coverage")
    for label, numbers in coverage.items():
        terminalreporter.write_line(
            f"  {label}: {numbers['exercised']}/{numbers['described']} "
            f"operations exercised ({numbers['percent']}%)"
        )

    accepted = validator.accepted
    if accepted:
        by_finding: dict[str, int] = {}
        for _, deviation in accepted:
            by_finding[deviation.finding] = by_finding.get(deviation.finding, 0) + 1
        known = ", ".join(f"{name} x{count}" for name, count in sorted(by_finding.items()))
        terminalreporter.write_line(f"  known deviations seen: {known}")

    violations = validator.violations
    if not violations:
        terminalreporter.write_line("  no new contract violations")
        return

    terminalreporter.write_sep("-", f"NEW contract violations ({len(violations)})")
    seen: set[tuple[str, str, int, str]] = set()
    for violation in violations:
        key = (violation.spec, violation.operation, violation.status, violation.kind)
        if key in seen:
            continue
        seen.add(key)
        terminalreporter.write_line(f"  {violation}")
