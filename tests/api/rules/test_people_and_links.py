"""Rules about attaching things to a task: people, labels, other tasks.

Each of these is a rule the product enforces rather than a permission
check. They matter because getting them wrong is invisible until someone
relies on them: an assignee who cannot open the task, a relation that
exists in one direction only.
"""

from __future__ import annotations

import pytest

from vikunja_qa.domain.permissions import Permission
from vikunja_qa.scenes import SceneBuilder

pytestmark = pytest.mark.covers("FUN")


def test_a_task_can_only_be_assigned_to_someone_who_can_see_it(scene: SceneBuilder) -> None:
    """Otherwise the product hands someone work they cannot open."""
    world = scene.project().task().outsider().done()
    stranger = world.actor("outsider")
    assert stranger.user_id is not None

    refused = world.owner.api.tasks.assign(world.task_id, stranger.user_id)
    assert not refused.ok, f"a stranger was assigned to the task\n{refused.describe()}"

    granted = world.owner.api.projects.add_user(
        world.project_id, stranger.username, Permission.WRITE
    )
    assert granted.ok, granted.describe()
    accepted = world.owner.api.tasks.assign(world.task_id, stranger.user_id)

    assert accepted.ok, (
        f"a member with write access was refused as an assignee\n{accepted.describe()}"
    )


def test_relating_a_task_shows_up_on_the_other_task_too(scene: SceneBuilder) -> None:
    """A relation is between two tasks, so it has to be visible from both.
    Subtask on one side means parent task on the other."""
    world = scene.project().done()
    parent = world.owner.api.tasks.create(world.project_id, "parent task")
    assert parent.ok, parent.describe()
    child = world.owner.api.tasks.create(world.project_id, "child task")
    assert child.ok, child.describe()

    related = world.owner.api.tasks.relate(int(parent["id"]), int(child["id"]), "subtask")
    assert related.ok, related.describe()

    other_side = world.owner.api.tasks.get(int(child["id"]))
    assert other_side.ok, other_side.describe()
    relations = other_side["related_tasks"] or {}
    assert "parenttask" in relations, (
        f"the child task knows nothing of its parent: {sorted(relations)}"
    )
    assert [task["id"] for task in relations["parenttask"]] == [int(parent["id"])]


def test_the_same_label_cannot_be_put_on_a_task_twice(scene: SceneBuilder) -> None:
    world = scene.project().task().label("urgent").done()
    label_id = int(world.labels["urgent"]["id"])

    first = world.owner.api.tasks.add_label(world.task_id, label_id)
    second = world.owner.api.tasks.add_label(world.task_id, label_id)

    assert first.ok, first.describe()
    assert not second.ok, f"one label went onto one task twice\n{second.describe()}"
    assert second.error_code is not None, (
        "the refusal carries no domain code, so a client cannot tell it from any other 400"
    )
    labels = world.owner.api.tasks.labels(world.task_id)
    assert labels.ok, labels.describe()
    assert len(labels.json) == 1, f"the task ended up with {len(labels.json)} labels"
