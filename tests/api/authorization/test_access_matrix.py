"""The access matrix for tasks and projects.

One table, one test. Each row names who is calling and what the product
answers, and is replayed against a world identical apart from the caller.
That is why link shares and team members are dressed up as actors: a row
does not care how its caller got in.

Rows reach the `caller` fixture through indirect parametrisation, so a row
is data and the fixture turns it into an actor; no test carries an argument
it only passes along.

Three expectations are worth stating out loud. A reader gets 403 on a
write, not 404: they may know the task exists, they simply may not change
it. An outsider also gets 403, and the matrix records that because it is
what the product does; whether it should is a separate question, taken up
in `test_existence_disclosure.py`. And the world is built once per module,
since six accounts per row would cost more than the checks, so rows that
mutate create their own task inside the shared project.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from vikunja_qa.actors.actor import Actor
from vikunja_qa.actors.factory import ActorFactory
from vikunja_qa.domain.permissions import Permission
from vikunja_qa.scenes import Scene, SceneBuilder

if TYPE_CHECKING:
    from _pytest.mark.structures import ParameterSet

pytestmark = pytest.mark.covers("ACL")


def row(role: str, expected: int, *, smoke: bool = False) -> ParameterSet:
    return pytest.param(role, expected, id=role, marks=[pytest.mark.smoke] if smoke else [])


READ_TASK = [
    row("owner", 200, smoke=True),
    row("admin", 200),
    row("writer", 200),
    row("reader", 200),
    row("teammate", 200),
    row("share_read", 200),
    row("outsider", 403, smoke=True),
    row("anon", 401),
]

WRITE_TASK = [
    row("owner", 200),
    row("admin", 200),
    row("writer", 200),
    row("reader", 403),
    row("teammate", 200),
    row("share_read", 403),
    row("outsider", 403),
    row("anon", 401),
]

# Deleting the project is split in two. Refusals can be replayed against
# the shared project because a refused call changes nothing; the two roles
# that succeed need a world of their own, since a project made just for
# the row would carry none of the shared project's grants.
DELETE_PROJECT_REFUSED = [
    row("writer", 403),
    row("reader", 403),
    row("teammate", 403),
    row("share_read", 403),
    row("outsider", 403),
    row("anon", 401),
]


@pytest.fixture(scope="module")
def world(module_scene: SceneBuilder) -> Scene:
    """One project, reached through every route the product offers."""
    return (
        module_scene.project()
        .member("admin", Permission.ADMIN)
        .member("writer", Permission.WRITE)
        .member("reader", Permission.READ)
        .team("devs", members=("teammate",), permission=Permission.WRITE)
        .share("share_read", Permission.READ)
        .outsider()
        .task("readable")
        .done()
    )


@pytest.fixture
def caller(request: pytest.FixtureRequest, world: Scene, actors: ActorFactory) -> Actor:
    """The actor a row names."""
    role: str = request.param
    return actors.anonymous() if role == "anon" else world.actor(role)


@pytest.fixture
def spare_task(world: Scene) -> int:
    """A task a mutating row may destroy without spoiling the shared world."""
    created = world.owner.api.tasks.create(world.project_id, "spare for a mutating row")
    assert created.ok, created.describe()
    return int(created["id"])


@pytest.mark.parametrize(("caller", "expected"), READ_TASK, indirect=["caller"])
def test_reading_a_task(world: Scene, caller: Actor, expected: int) -> None:
    response = caller.api.tasks.get(world.tasks["readable"]["id"])

    assert response.status == expected, response.describe()


@pytest.mark.parametrize(("caller", "expected"), WRITE_TASK, indirect=["caller"])
def test_updating_a_task(spare_task: int, caller: Actor, expected: int) -> None:
    response = caller.api.tasks.update(spare_task, title="changed by the matrix")

    assert response.status == expected, response.describe()


@pytest.mark.parametrize(("caller", "expected"), WRITE_TASK, indirect=["caller"])
def test_deleting_a_task(spare_task: int, caller: Actor, expected: int) -> None:
    response = caller.api.tasks.delete(spare_task)

    assert response.status == expected, response.describe()


@pytest.mark.parametrize(("caller", "expected"), DELETE_PROJECT_REFUSED, indirect=["caller"])
def test_deleting_a_project_is_refused(world: Scene, caller: Actor, expected: int) -> None:
    """Everyone short of an administrator is refused, a writer included.

    Write on a project means write inside it, not power over it.
    """
    response = caller.api.projects.delete(world.project_id)

    assert response.status == expected, response.describe()


@pytest.mark.parametrize("role", ["owner", "admin"])
def test_deleting_a_project_is_allowed(scene: SceneBuilder, role: str) -> None:
    """The two roles that may delete, each against a world of its own,
    because the call destroys it."""
    own = scene.project().member("admin", Permission.ADMIN).done()
    actor = own.owner if role == "owner" else own.actor("admin")

    response = actor.api.projects.delete(own.project_id)

    assert response.status == 200, response.describe()
    gone = own.owner.api.projects.get(own.project_id)
    assert gone.status == 404, f"the project survived a successful delete\n{gone.describe()}"


def test_a_reader_is_refused_rather_than_told_it_is_missing(world: Scene) -> None:
    """The distinction the matrix rests on: someone who may read but not
    write is refused, not told the task is absent, because they already
    know it is there."""
    response = world.actor("reader").api.tasks.update(world.tasks["readable"]["id"], title="nope")

    assert response.status == 403, response.describe()
