"""Do scoped API tokens actually stay in their lane?

A token carries a map of area to actions. This asks, for every area the
product publishes, whether a token granted one action there can do that
action, is refused the other actions in the same area, and cannot reach a
different area at all.

The case list is derived from `/routes`, which is the same catalogue the
product validates tokens against, so the matrix cannot drift from it. An
area added tomorrow is covered the next time this runs.

The granted scope is always a read. Proving a token reaches what it
should must not leave data behind, and granting `create` would.
"""

from __future__ import annotations

from functools import lru_cache

import pytest

from vikunja_qa.actors.actor import Actor
from vikunja_qa.actors.factory import ActorFactory
from vikunja_qa.auth.strategies import ApiToken
from vikunja_qa.config import get_settings
from vikunja_qa.contracts.scopes import Action, ScopeCase, cases_for
from vikunja_qa.transport.client import HttpClient
from vikunja_qa.transport.mailpit import MailpitClient

#: What the product answers a token reaching outside its scope.
OUT_OF_SCOPE = 401


@lru_cache(maxsize=1)
def _catalogue() -> tuple[ScopeCase, ...]:
    """Read the catalogue at collection.

    Costs one throwaway account per worker. Worth it: deriving the cases
    here rather than at run time means each area gets its own result in
    the report instead of one pass-or-fail for the lot.
    """
    settings = get_settings()
    try:
        factory = ActorFactory(settings, MailpitClient(settings.mailpit_url), label="catalogue")
        response = factory.user("catalogue").api.tokens.routes()
        return tuple(cases_for(response.body))
    except Exception as exc:  # noqa: BLE001 - collection needs a readable reason
        pytest.skip(f"cannot read the permission catalogue; is the stand up? ({exc})")


CASES = _catalogue()
IDS = [case.id for case in CASES]


@pytest.fixture(scope="module")
def token_owner(module_actors: ActorFactory) -> Actor:
    """One account that mints every token in this module."""
    return module_actors.user("tokens")


def _scoped_client(owner: Actor, case: ScopeCase) -> HttpClient:
    """A client carrying a token granted exactly one action."""
    minted = owner.api.tokens.create(
        f"scope {case.granted.label}", {case.area: [case.granted.name]}
    )
    assert minted.ok, f"could not mint a token for {case.granted.label}\n{minted.describe()}"
    # Paths from the catalogue are absolute from the host root, so the
    # client is bound to the host rather than to a version prefix.
    return owner.v1.with_base(get_settings().base_url).with_auth(
        ApiToken(str(minted["token"]), case.granted.label)
    )


@pytest.mark.usefixtures("contracts_collect_only")
@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_a_scoped_token_reaches_what_it_was_granted(case: ScopeCase, token_owner: Actor) -> None:
    client = _scoped_client(token_owner, case)

    response = client.request(case.granted.method, case.granted.concrete_path)

    assert response.status != OUT_OF_SCOPE, (
        f"a token granted {case.granted.label} was refused that very action\n{response.describe()}"
    )


@pytest.mark.usefixtures("contracts_collect_only")
@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_a_scoped_token_is_refused_its_siblings(case: ScopeCase, token_owner: Actor) -> None:
    """Granting one action in an area must not grant the rest of it.

    This is the check that would catch a scope widened by accident, and
    the reason the case list comes from the product rather than from a
    list someone maintains.
    """
    client = _scoped_client(token_owner, case)

    reached = [
        action.label
        for action in case.denied
        if client.request(action.method, action.concrete_path).status != OUT_OF_SCOPE
    ]

    assert not reached, f"a token granted only {case.granted.label} also reached {reached}"


@pytest.mark.usefixtures("contracts_collect_only")
def test_a_scoped_token_cannot_reach_another_area(token_owner: Actor) -> None:
    """The coarsest boundary, stated on its own so a failure is obvious."""
    labels = next((c for c in CASES if c.area == "labels"), None)
    if labels is None:
        pytest.skip("no labels area in the catalogue")

    client = _scoped_client(token_owner, labels)
    elsewhere = [c for c in CASES if c.area != labels.area]
    assert elsewhere, "the catalogue offers nothing to compare against"

    reached = [
        case.granted.label
        for case in elsewhere
        if client.request(case.granted.method, case.granted.concrete_path).status != OUT_OF_SCOPE
    ]

    assert not reached, f"a token scoped to {labels.area} also reached {reached}"


def test_the_catalogue_yielded_cases() -> None:
    """Guards against the generator silently producing nothing."""
    assert len(CASES) >= 10, f"only {len(CASES)} areas generated a case"


def test_the_test_area_is_never_generated() -> None:
    """The product's table-truncating area must never be called."""
    areas = {case.area for case in CASES}
    assert "test" not in areas
    for case in CASES:
        for action in (case.granted, *case.denied):
            assert "/test/" not in action.path, action


def test_catalogue_paths_carry_no_placeholders() -> None:
    """Every `:param` has to be filled, or the call goes somewhere
    unintended."""
    for case in CASES:
        for action in (case.granted, *case.denied):
            assert ":" not in action.concrete_path, action


def _unused(_: Action) -> None:  # pragma: no cover - keeps the import honest
    return None
