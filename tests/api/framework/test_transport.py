"""Proves the transport and identity layers work against the real product.

A framework area: these prove the harness rather than a product feature,
so they are exempt from declaring a coverage-matrix check. They exist so a
failure anywhere else can be trusted to be about the product and not about
the plumbing underneath it.

Three of them are smoke. If an anonymous caller is not refused, if a fresh
account cannot sign in, or if two accounts can see each other's data,
nothing the rest of the suite reports means anything, so CI asks these
first.
"""

from __future__ import annotations

import pytest

from vikunja_qa.actors.actor import Actor
from vikunja_qa.actors.factory import ActorFactory
from vikunja_qa.auth.strategies import RawHeader
from vikunja_qa.config import Settings


@pytest.mark.smoke
def test_anonymous_caller_is_refused(anon: Actor) -> None:
    """The unauthenticated baseline every access-matrix row rests on."""
    response = anon.v1.get("/user")

    assert response.status == 401, response.describe()
    assert response.error_code is not None, (
        "an error response must carry a domain code; clients key their "
        f"translations off it\n{response.describe()}"
    )


@pytest.mark.smoke
def test_registered_actor_can_read_itself(owner: Actor) -> None:
    """Register, confirm by mail, log in, then use the session."""
    response = owner.v1.get("/user")

    assert response.status == 200, response.describe()
    assert response["username"] == owner.username, response.describe()


@pytest.mark.smoke
def test_two_actors_are_isolated(actors: ActorFactory) -> None:
    """The property the whole isolation strategy rests on: separate
    accounts cannot see each other's projects."""
    alice, bob = actors.users("alice", "bob")

    created = alice.v1.put("/projects", json={"title": "alice's project"})
    assert created.ok, created.describe()
    project_id = created["id"]

    visible_to_bob = bob.v1.get("/projects")
    assert visible_to_bob.ok, visible_to_bob.describe()
    assert all(p["id"] != project_id for p in visible_to_bob.json), (
        "bob can see a project they have no relationship to; ownership-based "
        f"isolation does not hold\n{visible_to_bob.describe()}"
    )


def test_both_api_versions_answer_the_same_actor(owner: Actor) -> None:
    """One credential, two doors. Cross-version work depends on this."""
    v1 = owner.v1.get("/user")
    v2 = owner.v2.get("/user")

    assert v1.status == 200, v1.describe()
    assert v2.status == 200, v2.describe()
    assert v1["username"] == v2["username"] == owner.username


def test_malformed_credential_is_refused(owner: Actor) -> None:
    """A token-shaped string that is not a token must not authenticate.

    The product looks tokens up by their last eight characters, and its
    source carries a guard against short values panicking, so this is a
    boundary worth holding.
    """
    broken = owner.using(RawHeader("Bearer tk_not-a-real-token", "malformed-token"))
    response = broken.v1.get("/user")

    assert response.status == 401, response.describe()


@pytest.mark.parametrize("version", ["v1", "v2"])
def test_version_indexed_access(owner: Actor, version: str) -> None:
    """Tests parameterised over both versions address them by name."""
    response = owner.raw(version).get("/user")
    assert response.status == 200, response.describe()


def test_settings_point_at_the_stand(settings: Settings) -> None:
    assert settings.api_v1.endswith("/api/v1")
    assert settings.api_v2.endswith("/api/v2")
