"""Two checks applied to every operation both descriptions declare.

Nobody writes these cases. The list comes from the product, so an
endpoint added tomorrow is covered the first time this runs, which is the
only way a check like "everything needs a credential" stays true.

Each operation is called twice, anonymously and with a session, because
one response cannot tell the two interesting failures apart. A 404 to
both means the route is not registered at all, which is what a feature
switched off on this stand looks like and is not an authorization hole.
A 404 to the anonymous call alone would be one.

Identifiers in the generated paths are chosen to match nothing, so even
an endpoint that turns out not to check anything cannot touch real data.
The product's table-truncating test API is excluded outright.

Contract checking runs in record-only mode here. Walking hundreds of
operations with identifiers that match nothing means nearly every
response is an error, and error schemas are where deviations cluster; a
question about credentials should not be answered by the shape of an
error body. The deviations are still counted and still reported.
"""

from __future__ import annotations

from functools import lru_cache
from urllib.parse import urlsplit

import pytest

from vikunja_qa.actors.actor import Actor
from vikunja_qa.actors.factory import ActorFactory
from vikunja_qa.config import get_settings
from vikunja_qa.contracts.spec import SpecIndex
from vikunja_qa.contracts.sweep import Call, calls_for, unused_public_entries
from vikunja_qa.transport.mailpit import MailpitClient

#: Documented operations the product answers 405 to, meaning the described
#: operation does not exist. Each is a reported finding; anything new here
#: fails, the same arrangement the contract baseline uses.
KNOWN_ABSENT: dict[str, str] = {
    "PUT /labels/{id}": "VKJ-007",
    "POST /migration/vikunja-file/migrate": "VKJ-007",
}


@lru_cache(maxsize=1)
def _specs() -> tuple[SpecIndex, ...]:
    """Loaded once, at collection, straight from the running instance."""
    settings = get_settings()
    try:
        return (
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
        )
    except Exception as exc:  # noqa: BLE001 - collection needs a readable reason
        # allow_module_level is required here: without it pytest raises its
        # own error about skipping at import time, which buries the reason
        # this actually failed.
        pytest.skip(
            f"cannot read the descriptions: {type(exc).__name__}: {exc}",
            allow_module_level=True,
        )


@lru_cache(maxsize=1)
def _calls() -> tuple[Call, ...]:
    return tuple(call for spec in _specs() for call in calls_for(spec))


CALLS = _calls()
IDS = [call.id for call in CALLS]


@pytest.fixture(scope="session")
def sweeper(settings, mailpit: MailpitClient, transport_hooks) -> Actor:  # noqa: ANN001
    """One account for the whole sweep.

    Shared deliberately: the sweep only probes identifiers that match
    nothing, so it owns no data and cannot collide with anything.
    """
    return ActorFactory(settings, mailpit, label="sweep", hooks=transport_hooks).user("sweeper")


@pytest.mark.usefixtures("contracts_collect_only")
@pytest.mark.parametrize("call", CALLS, ids=IDS)
def test_operation_demands_a_credential(call: Call, sweeper: Actor, actors: ActorFactory) -> None:
    anonymous = actors.anonymous().raw(call.spec).request(call.method, call.path)

    if call.public:
        assert anonymous.status != 401, (
            f"{call.operation} is meant to be reachable without a credential "
            f"({call.reason}) but demanded one\n{anonymous.describe()}"
        )
        return

    if anonymous.status == 404:
        authenticated = sweeper.raw(call.spec).request(call.method, call.path)
        if authenticated.status == 404:
            pytest.skip("route not registered; the feature is off on this stand")

    if anonymous.status == 405:
        # The verb never reaches the path, so there is nothing here to
        # protect. Whether the description should have listed it is the
        # other test's question.
        pytest.skip("the product does not accept this verb; see test_documented_operation_exists")

    assert anonymous.status == 401, (
        f"{call.operation} answered an anonymous caller with {anonymous.status} "
        f"instead of refusing them\n{anonymous.describe()}"
    )


@pytest.mark.usefixtures("contracts_collect_only")
@pytest.mark.parametrize("call", CALLS, ids=IDS)
def test_documented_operation_exists(call: Call, actors: ActorFactory) -> None:
    """A described operation the product answers 405 to does not exist.

    Asked anonymously on purpose. Routing decides whether a verb reaches
    a path before authentication is consulted, so 405 means the same
    thing either way, and asking without a credential keeps the check
    from creating anything: a collection-level create like `PUT /labels`
    succeeds when it is authenticated, and a sweep should not leave data
    behind.
    """
    response = actors.anonymous().raw(call.spec).request(call.method, call.path)

    if response.status != 405:
        assert call.operation not in KNOWN_ABSENT or call.spec == "v2", (
            f"{call.operation} no longer answers 405, so "
            f"{KNOWN_ABSENT.get(call.operation)} may be fixed; drop it from KNOWN_ABSENT"
        )
        return

    known = KNOWN_ABSENT.get(call.operation)
    assert known, (
        f"{call.operation} is described but the product rejects that verb, "
        f"so a client built from the description cannot call it\n{response.describe()}"
    )


def test_no_stale_entries_in_the_public_allowlist() -> None:
    """An exemption that stopped matching is how an endpoint quietly
    drops out of the sweep."""
    stale = unused_public_entries(list(_specs()))
    assert not stale, f"these entries match no operation any more: {stale}"


def test_the_sweep_covers_both_descriptions() -> None:
    """Guards against the generator silently producing nothing."""
    by_spec = {spec.label: len([c for c in CALLS if c.spec == spec.label]) for spec in _specs()}
    for label, count in by_spec.items():
        assert count > 50, f"only {count} operations generated for {label}"
