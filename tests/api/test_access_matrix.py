"""The access matrix for tasks and projects.

One table, one test. Each row names who is calling and what the product
answers, and the row is replayed against a world that is identical apart
from the caller. That is the reason link shares and team members are
dressed up as actors: a row does not care how its caller got in.

Three expectations deserve stating out loud.

A reader gets 403 on a write, not 404. They are allowed to know the task
exists; they are simply not allowed to change it.

An outsider also gets 403, not 404, and the matrix records that because
it is what the product does. Whether it *should* is a separate question,
taken up in `test_outsider_disclosure.py`.

The world is built once for the whole module. Six accounts per
parametrised row cost more than the checks themselves, so rows that
mutate create their own task inside the shared project instead.
"""

from __future__ import annotations

import pytest

from vikunja_qa.actors.factory import ActorFactory
from vikunja_qa.domain.permissions import Permission
from vikunja_qa.scenes import Scene, SceneBuilder

READ_TASK = [
    ("owner", 200),
    ("admin", 200),
    ("writer", 200),
    ("reader", 200),
    ("teammate", 200),
    ("share_read", 200),
    ("outsider", 403),
    ("anon", 401),
]

WRITE_TASK = [
    ("owner", 200),
    ("admin", 200),
    ("writer", 200),
    ("reader", 403),
    ("teammate", 200),
    ("share_read", 403),
    ("outsider", 403),
    ("anon", 401),
]

# Deleting the project is split in two. The refusals can be replayed
# against the shared project because a refused call changes nothing;
# the two roles that succeed need a world of their own, since a project
# created just for the row would not carry any of its grants.
DELETE_PROJECT_REFUSED = [
    ("writer", 403),
    ("reader", 403),
    ("teammate", 403),
    ("share_read", 403),
    ("outsider", 403),
    ("anon", 401),
]

ROLES = [role for role, _ in READ_TASK]


@pytest.fixture(scope="module")
def world(module_scene: SceneBuilder) -> Scene:
    """One project reached through every route the product offers."""
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
def caller(world: Scene, actors: ActorFactory, request: pytest.FixtureRequest):  # noqa: ANN201
    """The actor named by the current parametrised row."""
    role = request.getfixturevalue("role")
    return actors.anonymous() if role == "anon" else world.actor(role)


@pytest.fixture
def spare_task(world: Scene) -> int:
    """A task this row may destroy without spoiling the shared world."""
    created = world.owner.api.tasks.create(world.project_id, "spare for a mutating row")
    assert created.ok, created.describe()
    return int(created["id"])


@pytest.mark.parametrize(("role", "expected"), READ_TASK, ids=ROLES)
def test_reading_a_task(world: Scene, caller, role: str, expected: int) -> None:  # noqa: ANN001, ARG001
    response = caller.api.tasks.get(world.tasks["readable"]["id"])
    assert response.status == expected, response.describe()


@pytest.mark.parametrize(("role", "expected"), WRITE_TASK, ids=ROLES)
def test_updating_a_task(spare_task: int, caller, role: str, expected: int) -> None:  # noqa: ANN001, ARG001
    response = caller.api.tasks.update(spare_task, title="changed by the matrix")
    assert response.status == expected, response.describe()


@pytest.mark.parametrize(("role", "expected"), WRITE_TASK, ids=ROLES)
def test_deleting_a_task(spare_task: int, caller, role: str, expected: int) -> None:  # noqa: ANN001, ARG001
    response = caller.api.tasks.delete(spare_task)
    assert response.status == expected, response.describe()


@pytest.mark.parametrize(
    ("role", "expected"),
    DELETE_PROJECT_REFUSED,
    ids=[r for r, _ in DELETE_PROJECT_REFUSED],
)
def test_deleting_a_project_is_refused(world: Scene, caller, role: str, expected: int) -> None:  # noqa: ANN001, ARG001
    """Everyone short of an administrator is refused, including a writer.

    Write on a project means write inside it, not power over it. That
    distinction is the one worth pinning down.
    """
    response = caller.api.projects.delete(world.project_id)
    assert response.status == expected, response.describe()


@pytest.mark.parametrize("role", ["owner", "admin"])
def test_deleting_a_project_is_allowed(scene: SceneBuilder, role: str) -> None:
    """The two roles that may delete, each against a world of its own
    because the call destroys it."""
    own = scene.project().member("admin", Permission.ADMIN).done()
    actor = own.owner if role == "owner" else own.actor("admin")

    response = actor.api.projects.delete(own.project_id)

    assert response.status == 200, response.describe()
    assert own.owner.api.projects.get(own.project_id).status == 404, (
        "the project should be gone after a successful delete"
    )


def test_a_reader_is_refused_rather_than_told_it_is_missing(world: Scene) -> None:
    """The distinction the matrix rests on.

    Someone who may read but not write must be refused, not told the
    task is absent: they already know it is there.
    """
    response = world.actor("reader").api.tasks.update(world.tasks["readable"]["id"], title="nope")

    assert response.status == 403, response.describe()
