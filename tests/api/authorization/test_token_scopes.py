"""Do scoped API tokens stay in their lane?

A token carries a map of area to actions. For every area the product
publishes, this asks whether a token granted one action there can perform
it, is refused the other actions in that area, and cannot reach another
area at all.

The cases come from `/routes`, the same catalogue the product validates
tokens against, so this cannot drift from it: an area added tomorrow is
covered on the next run. The granted scope is always a read, because
proving a token reaches what it should must leave no data behind.

How cases are derived from a catalogue, including that the product's
table-emptying area is never generated, is pure logic and is tested in the
unit layer. What stays here needs the live product.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from vikunja_qa.actors.actor import Actor
from vikunja_qa.actors.factory import ActorFactory
from vikunja_qa.auth.strategies import ApiToken
from vikunja_qa.config import Settings
from vikunja_qa.contracts.scopes import ScopeCase
from vikunja_qa.testing import discovery
from vikunja_qa.transport.client import HttpClient

pytestmark = [
    pytest.mark.covers("SCP"),
    pytest.mark.generated,
    pytest.mark.usefixtures("contracts_collect_only"),
]

#: What the product answers a token reaching outside its scope.
OUT_OF_SCOPE = 401

#: Every way a call can be turned away. Used for the positive half of the
#: matrix, where "not refused" is the claim: ruling out only 401 there let a
#: 403 or a 405 on the very action a token was granted read as success.
#: Granted actions here are reads of identifiers that cannot exist, so the
#: honest answers are 200 and 404 and nothing else.
REFUSALS = frozenset({401, 403, 405})

CASES = discovery.scope_cases()


@pytest.fixture(scope="module")
def token_owner(module_actors: ActorFactory) -> Actor:
    """One account mints every token in this module."""
    return module_actors.user("tokens")


@pytest.fixture
def scoped_client(token_owner: Actor, settings: Settings) -> Callable[[ScopeCase], HttpClient]:
    """Mint a token granted exactly one action and return a client carrying it."""

    def mint(case: ScopeCase) -> HttpClient:
        minted = token_owner.api.tokens.create(
            f"scope {case.granted.label}", {case.area: [case.granted.name]}
        )
        assert minted.ok, f"could not mint a token for {case.granted.label}\n{minted.describe()}"
        # Catalogue paths are absolute from the host root, so the client is
        # bound to the host rather than to a version prefix.
        return token_owner.v1.with_base(settings.base_url).with_auth(
            ApiToken(str(minted["token"]), case.granted.label)
        )

    return mint


@pytest.mark.parametrize("case", CASES, ids=[case.id for case in CASES])
def test_a_scoped_token_reaches_what_it_was_granted(
    case: ScopeCase, scoped_client: Callable[[ScopeCase], HttpClient]
) -> None:
    response = scoped_client(case).request(case.granted.method, case.granted.concrete_path)

    assert response.status not in REFUSALS, (
        f"a token granted {case.granted.label} was refused that very action with "
        f"{response.status}\n{response.describe()}"
    )


@pytest.mark.parametrize("case", CASES, ids=[case.id for case in CASES])
def test_a_scoped_token_is_refused_its_siblings(
    case: ScopeCase, scoped_client: Callable[[ScopeCase], HttpClient]
) -> None:
    """Granting one action in an area must not grant the rest of it: the
    check that would catch a scope widened by accident."""
    client = scoped_client(case)

    reached = [
        action.label
        for action in case.denied
        if client.request(action.method, action.concrete_path).status != OUT_OF_SCOPE
    ]

    assert not reached, f"a token granted only {case.granted.label} also reached {reached}"


def test_a_scoped_token_cannot_reach_another_area(
    scoped_client: Callable[[ScopeCase], HttpClient],
) -> None:
    """The coarsest boundary, stated on its own so a failure is unmistakable."""
    labels = next((case for case in CASES if case.area == "labels"), None)
    if labels is None:
        pytest.skip("the catalogue has no labels area to scope a token to")
    client = scoped_client(labels)

    reached = [
        case.granted.label
        for case in CASES
        if case.area != labels.area
        and client.request(case.granted.method, case.granted.concrete_path).status != OUT_OF_SCOPE
    ]

    assert not reached, f"a token scoped to {labels.area} also reached {reached}"


def test_the_live_catalogue_yields_cases() -> None:
    """Guards against the product's catalogue changing shape and the
    generator quietly producing nothing."""
    assert len(CASES) >= 10, f"only {len(CASES)} areas of the catalogue produced a case"
