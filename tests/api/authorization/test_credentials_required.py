"""Every operation both descriptions declare either demands a credential or
is public on purpose.

Nobody writes these cases. The list comes from the product, so an endpoint
added tomorrow is covered the first time this runs, which is the only way a
claim like "everything needs a credential" stays true.

An operation that refuses an anonymous caller with 404 is asked again with
a session, because one response cannot tell two failures apart. 404 to both
means the route is not registered, which is what a feature switched off on
this stand looks like and not an authorization hole. 404 to the anonymous
call alone would be one.

Identifiers in the generated paths match nothing, so even an endpoint that
turns out not to check anything cannot touch real data, and the product's
table-emptying test API is excluded outright.

Contract checking only records here. Probing hundreds of operations with
identifiers that match nothing makes nearly every response an error, and
error schemas are where deviations cluster; a question about credentials
should not be answered by the shape of an error body.
"""

from __future__ import annotations

import pytest

from vikunja_qa.actors.actor import Actor
from vikunja_qa.actors.factory import ActorFactory
from vikunja_qa.config import Settings
from vikunja_qa.contracts.sweep import Call, unused_public_entries, unused_substitutions
from vikunja_qa.testing import discovery
from vikunja_qa.transport.client import ResponseHook
from vikunja_qa.transport.mailpit import MailpitClient

pytestmark = [pytest.mark.covers("AUT"), pytest.mark.generated]

CALLS = discovery.generated_calls()


@pytest.fixture(scope="session")
def sweeper(
    settings: Settings, mailpit: MailpitClient, transport_hooks: list[ResponseHook]
) -> Actor:
    """One account for the whole sweep. Shared deliberately: the sweep only
    probes identifiers that match nothing, so it owns no data and cannot
    collide with anything."""
    return ActorFactory(settings, mailpit, label="sweep", hooks=transport_hooks).user("sweeper")


@pytest.mark.usefixtures("contracts_collect_only")
@pytest.mark.parametrize("call", CALLS, ids=[call.id for call in CALLS])
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
        # The verb never reaches the path, so there is nothing to protect.
        # Whether the description should list it is a contract question.
        pytest.skip("the product does not accept this verb; see test_documented_operations")

    assert anonymous.status == 401, (
        f"{call.operation} answered an anonymous caller with {anonymous.status} "
        f"instead of refusing them\n{anonymous.describe()}"
    )


def test_no_stale_entries_in_the_public_allowlist() -> None:
    """An exemption that stopped matching anything is how an endpoint
    quietly drops out of the sweep."""
    stale = unused_public_entries(list(discovery.described_specs()))

    assert not stale, f"these allowlist entries match no operation any more: {stale}"


def test_no_stale_entries_in_the_parameter_substitutions() -> None:
    """The other table the sweep is built on, held to the same rule.

    These name the path parameters that are words rather than identifiers.
    A key that stops matching means the parameter was renamed, and from
    then on the sweep fills it with a number — which asks a different
    question of each version and looks like the versions disagreeing.
    """
    stale = unused_substitutions(list(discovery.described_specs()))

    assert not stale, f"these substitutions match no path parameter any more: {stale}"


def test_the_sweep_covers_both_descriptions() -> None:
    """Guards against the generator silently producing nothing."""
    for spec in discovery.described_specs():
        count = sum(1 for call in CALLS if call.spec == spec.label)
        assert count > 50, f"only {count} operations generated for {spec.label}"
