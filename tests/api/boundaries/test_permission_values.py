"""What the product does with a permission level it cannot read.

The level is a small integer: read is zero, write one, admin two, and the
product keeps a fourth state, minus one, for "not determined". A field
that small is exactly where a parser turns a malformed value into a real
grant, so each shape is sent deliberately.

A refusal is only half the check. The other half is that nobody gained
access on the way, which is asked of the account itself rather than of
the answer.
"""

from __future__ import annotations

from typing import Any

import pytest

from vikunja_qa.actors.actor import Actor
from vikunja_qa.domain.permissions import Permission
from vikunja_qa.scenes import Scene, SceneBuilder

pytestmark = [
    pytest.mark.covers("NEG"),
    # Every request here carries a permission that is not a permission.
    # Sending one is the subject, so holding what is sent to the
    # description would be reporting the test rather than the product.
    # What comes back is still checked, and that is the half worth
    # keeping: a refusal still owes its caller the shape it promised.
    pytest.mark.usefixtures("contracts_ignore_requests"),
]

#: Every shape that is not a permission level, with the name it goes by in
#: a failure message.
MALFORMED: list[Any] = [
    pytest.param(None, id="null"),
    pytest.param("", id="empty-string"),
    pytest.param("1", id="the-number-as-a-string"),
    pytest.param(-1, id="the-not-determined-sentinel"),
    pytest.param(99, id="out-of-range"),
    pytest.param(1.5, id="fractional"),
    pytest.param(True, id="boolean"),
    pytest.param([1], id="a-list"),
    pytest.param({"permission": 1}, id="an-object"),
]


@pytest.fixture
def world(scene: SceneBuilder) -> Scene:
    """A project, and an account that has no access to it yet."""
    return scene.project().outsider().done()


def _can_see(actor: Actor, project_id: int) -> bool:
    return actor.api.projects.get(project_id).ok


@pytest.mark.parametrize("value", MALFORMED)
def test_a_permission_that_is_not_a_level_is_refused(world: Scene, value: Any) -> None:
    stranger = world.actor("outsider")
    assert not _can_see(stranger, world.project_id), "the fixture handed out access already"

    answered = world.owner.v1.put(
        f"/projects/{world.project_id}/users",
        json={"username": stranger.username, "permission": value},
    )

    assert not answered.ok, f"a grant was made from {value!r}\n{answered.describe()}"
    assert answered.status < 500, f"a malformed level broke the product\n{answered.describe()}"
    assert not _can_see(stranger, world.project_id), (
        f"the call was refused and the account got access anyway, from {value!r}"
    )


def test_an_omitted_permission_grants_the_least_privilege(world: Scene) -> None:
    """Defaulting is fine; defaulting upwards would not be. With no level
    named at all, the grant has to land on read."""
    stranger = world.actor("outsider")

    granted = world.owner.v1.put(
        f"/projects/{world.project_id}/users", json={"username": stranger.username}
    )
    assert granted.ok, granted.describe()

    assert granted["permission"] == int(Permission.READ), (
        f"an unnamed permission became {granted['permission']}"
    )
    assert _can_see(stranger, world.project_id), "read access was reported but not given"
    refused = stranger.api.tasks.create(world.project_id, "writing with read access")
    assert not refused.ok, f"the default grant allowed writing\n{refused.describe()}"


def test_a_refused_level_leaves_an_existing_grant_alone(world: Scene) -> None:
    """The dangerous version of the same mistake: not inventing access but
    quietly widening it on an account that already has some."""
    stranger = world.actor("outsider")
    granted = world.owner.api.projects.add_user(
        world.project_id, stranger.username, Permission.READ
    )
    assert granted.ok, granted.describe()

    answered = world.owner.v1.post(
        f"/projects/{world.project_id}/users/{stranger.username}", json={"permission": 99}
    )

    assert not answered.ok, f"a level of 99 was accepted\n{answered.describe()}"
    still_refused = stranger.api.tasks.create(world.project_id, "writing after a refused change")
    assert not still_refused.ok, (
        f"a refused change widened an existing grant\n{still_refused.describe()}"
    )
