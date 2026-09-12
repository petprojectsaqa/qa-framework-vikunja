"""Two callers writing at the same instant.

Everything else in this suite asks what the product does when one caller
acts. These ask what it does when two act at the same moment, which is the
ordinary case for a product several people share and the one a sequential
suite never reaches.

Contract checking is set to record rather than fail here. These tests
provoke error paths deliberately, and a deviation raised from the
transport hook would fail the test before it reached the thing it exists
to state.
"""

from __future__ import annotations

from typing import Any

import pytest

from vikunja_qa.actors.actor import Actor
from vikunja_qa.concurrency import at_the_same_time
from vikunja_qa.scenes import Scene, SceneBuilder
from vikunja_qa.transport.response import ApiResponse

pytestmark = [pytest.mark.covers("CNC"), pytest.mark.usefixtures("contracts_collect_only")]

#: Wide enough to collide reliably, small enough to stay quick. The defect
#: below shows at two, so this is not a load test in disguise.
CALLERS = 6


def _callers(actor: Actor, howmany: int) -> list[Actor]:
    """The same identity, one connection pool per caller."""
    return [actor.on_its_own_connection(role=f"{actor.role}-{n}") for n in range(howmany)]


def _statuses(answers: list[ApiResponse]) -> list[int]:
    return sorted(answer.status for answer in answers)


@pytest.fixture
def world(scene: SceneBuilder) -> Scene:
    return scene.project().done()


@pytest.mark.finding("VKJ-015")
@pytest.mark.xfail(
    reason=(
        "VKJ-015: tasks created in one project at the same moment collide on the per-project "
        "index, and every caller but one gets a 500 with its task not created"
    ),
    strict=False,
)
def test_tasks_created_at_the_same_moment_are_all_created(world: Scene) -> None:
    """Two people adding a task to a shared project at the same second is
    the ordinary case, not an edge one."""
    callers = _callers(world.owner, CALLERS)

    answers = at_the_same_time(
        [
            (lambda caller=caller, n=n: caller.api.tasks.create(world.project_id, f"racer {n}"))
            for n, caller in enumerate(callers)
        ]
    )

    refused = [answer for answer in answers if not answer.ok]
    assert not refused, (
        f"{len(refused)} of {CALLERS} simultaneous creations failed\n{refused[0].describe()}"
    )


def test_simultaneous_creation_never_gives_two_tasks_the_same_number(world: Scene) -> None:
    """Whatever the product does with the callers it refuses, the tasks it
    does accept must stay distinguishable: the per-project number is what
    people quote to each other.
    """
    callers = _callers(world.owner, CALLERS)

    at_the_same_time(
        [
            (lambda caller=caller, n=n: caller.api.tasks.create(world.project_id, f"numbered {n}"))
            for n, caller in enumerate(callers)
        ]
    )

    listed = world.owner.api.tasks.all()
    assert listed.ok, listed.describe()
    stored: list[dict[str, Any]] = [
        task for task in listed.json if task["project_id"] == world.project_id
    ]
    numbers = [task["index"] for task in stored]
    assert len(numbers) == len(set(numbers)), f"two tasks share a number: {sorted(numbers)}"


def test_the_same_task_updated_at_the_same_moment_keeps_one_of_the_writes(world: Scene) -> None:
    """Last write wins is a fine answer. Losing every write, or storing a
    mixture of two, is not."""
    task = world.owner.api.tasks.create(world.project_id, "contested")
    assert task.ok, task.describe()
    task_id = int(task["id"])
    callers = _callers(world.owner, CALLERS)
    titles = [f"written by {n}" for n in range(CALLERS)]

    answers = at_the_same_time(
        [
            (lambda caller=caller, title=title: caller.api.tasks.update(task_id, title=title))
            for caller, title in zip(callers, titles, strict=True)
        ]
    )

    assert all(answer.status < 500 for answer in answers), (
        f"a simultaneous update answered with a server error: {_statuses(answers)}"
    )
    stored = world.owner.api.tasks.get(task_id)
    assert stored.ok, stored.describe()
    assert stored["title"] in titles, (
        f"the stored title is not one of the writes: {stored['title']!r}"
    )


def test_deleting_the_same_task_twice_at_the_same_moment_is_not_an_error(world: Scene) -> None:
    """Both callers asked for the same end state, and both got it. What
    matters is that neither is told the product broke."""
    task = world.owner.api.tasks.create(world.project_id, "doomed")
    assert task.ok, task.describe()
    task_id = int(task["id"])
    first, second = _callers(world.owner, 2)

    answers = at_the_same_time(
        [lambda: first.api.tasks.delete(task_id), lambda: second.api.tasks.delete(task_id)]
    )

    assert all(answer.status < 500 for answer in answers), (
        f"deleting twice at once answered with a server error: {_statuses(answers)}"
    )
    assert world.owner.api.tasks.get(task_id).status == 404, "the task outlived both deletions"


def test_the_same_label_added_twice_at_the_same_moment_lands_once(world: Scene) -> None:
    """The interesting half is the database, not the status codes: two
    callers must not produce two rows for one label on one task."""
    task = world.owner.api.tasks.create(world.project_id, "labelled")
    assert task.ok, task.describe()
    label = world.owner.api.labels.create("racy")
    assert label.ok, label.describe()
    task_id, label_id = int(task["id"]), int(label["id"])
    first, second = _callers(world.owner, 2)

    answers = at_the_same_time(
        [
            lambda: first.api.tasks.add_label(task_id, label_id),
            lambda: second.api.tasks.add_label(task_id, label_id),
        ]
    )

    assert all(answer.status < 500 for answer in answers), (
        f"adding one label twice at once answered with a server error: {_statuses(answers)}"
    )
    labels = world.owner.api.tasks.labels(task_id)
    assert labels.ok, labels.describe()
    assert len(labels.json) == 1, f"one label was stored {len(labels.json)} times"
