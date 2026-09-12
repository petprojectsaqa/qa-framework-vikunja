"""The rules a task obeys as it is worked on.

These are the product's promises about its own domain, the ones a user
would describe without mentioning HTTP: finishing a task records when,
reopening it forgets, a repeating task comes back rather than closing, and
a task carries a number of its own inside its project.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from vikunja_qa.scenes import SceneBuilder

pytestmark = pytest.mark.covers("FUN")

#: The product's zero time, which is what an unset timestamp looks like on
#: the wire. Go has no null date, so "never" arrives as year one.
NEVER = "0001-01-01T00:00:00Z"

DAY_IN_SECONDS = 86_400


def _iso(moment: datetime) -> str:
    return moment.isoformat().replace("+00:00", "Z")


def test_finishing_a_task_records_when_and_reopening_it_forgets(scene: SceneBuilder) -> None:
    world = scene.project().task(title="finish it").done()
    task_id = world.task_id

    created = world.owner.api.tasks.get(task_id)
    assert created.ok, created.describe()
    assert created["done"] is False
    assert created["done_at"] == NEVER, "a task nobody finished carries a completion time"

    finished = world.owner.api.tasks.update(task_id, title="finish it", done=True)
    assert finished.ok, finished.describe()
    assert finished["done"] is True
    assert finished["done_at"] != NEVER, "a finished task records no completion time"

    reopened = world.owner.api.tasks.update(task_id, title="finish it", done=False)
    assert reopened.ok, reopened.describe()
    assert reopened["done"] is False
    assert reopened["done_at"] == NEVER, (
        f"a reopened task kept the moment it was finished: {reopened['done_at']}"
    )


def test_a_repeating_task_moves_its_due_date_instead_of_closing(scene: SceneBuilder) -> None:
    """The point of a repeating task: finishing this occurrence schedules
    the next one, and the task stays open."""
    world = scene.project().done()
    due = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
    created = world.owner.api.tasks.create(
        world.project_id, "water the plants", repeat_after=DAY_IN_SECONDS, due_date=_iso(due)
    )
    assert created.ok, created.describe()

    finished = world.owner.api.tasks.update(
        int(created["id"]),
        title="water the plants",
        repeat_after=DAY_IN_SECONDS,
        due_date=_iso(due),
        done=True,
    )
    assert finished.ok, finished.describe()

    assert finished["done"] is False, "a repeating task closed instead of coming back"
    assert finished["due_date"] == _iso(datetime(2026, 10, 2, 9, 0, tzinfo=UTC)), (
        f"the next occurrence is not a day later: {finished['due_date']}"
    )


def test_a_task_carries_its_own_number_within_its_project(scene: SceneBuilder) -> None:
    """The number people quote to each other. It counts up inside a
    project and starts again in the next one, so it is not the id."""
    world = scene.project().done()
    second_project = world.owner.api.projects.create("somewhere else")
    assert second_project.ok, second_project.describe()

    numbers = []
    for title in ("first", "second", "third"):
        made = world.owner.api.tasks.create(world.project_id, title)
        assert made.ok, made.describe()
        numbers.append((made["index"], made["identifier"]))

    elsewhere = world.owner.api.tasks.create(int(second_project["id"]), "first over here")
    assert elsewhere.ok, elsewhere.describe()

    assert numbers == [(1, "#1"), (2, "#2"), (3, "#3")], f"numbering did not count up: {numbers}"
    assert elsewhere["index"] == 1, (
        f"a new project started numbering at {elsewhere['index']} rather than 1"
    )


def test_moving_a_task_into_the_done_bucket_finishes_it(scene: SceneBuilder) -> None:
    """The board and the task are two views of one state. Dragging a card
    into Done is the same act as ticking the box."""
    world = scene.project().task(title="drag me").done()
    views = world.owner.api.projects.views(world.project_id)
    assert views.ok, views.describe()
    kanban = next((view for view in views.json if view.get("view_kind") == "kanban"), None)
    assert kanban is not None, (
        f"the project has no board: {[v.get('view_kind') for v in views.json]}"
    )

    buckets = world.owner.api.projects.buckets(world.project_id, int(kanban["id"]))
    assert buckets.ok, buckets.describe()
    done_bucket = next((bucket for bucket in buckets.json if bucket["title"] == "Done"), None)
    assert done_bucket is not None, f"no Done bucket: {[b['title'] for b in buckets.json]}"

    moved = world.owner.api.projects.move_task_to_bucket(
        world.project_id, int(kanban["id"]), int(done_bucket["id"]), world.task_id
    )
    assert moved.ok, moved.describe()

    task = world.owner.api.tasks.get(world.task_id)
    assert task.ok, task.describe()
    assert task["done"] is True, "a task in the Done bucket is not marked done"


def test_an_archived_project_refuses_writes_and_still_reads(scene: SceneBuilder) -> None:
    """Archiving is not deleting. The history stays readable, and nothing
    new is added to it."""
    world = scene.project(title="to archive").task(title="before archiving").done()
    archived = world.owner.api.projects.update(
        world.project_id, title="to archive", is_archived=True
    )
    assert archived.ok, archived.describe()

    created = world.owner.api.tasks.create(world.project_id, "after archiving")
    updated = world.owner.api.tasks.update(world.task_id, title="renamed")
    read = world.owner.api.tasks.get(world.task_id)

    assert not created.ok, f"an archived project accepted a new task\n{created.describe()}"
    assert not updated.ok, f"an archived project accepted an edit\n{updated.describe()}"
    assert created.error_code == updated.error_code, (
        "the two refusals carry different domain codes: "
        f"{created.error_code} and {updated.error_code}"
    )
    assert read.ok, f"an archived project stopped being readable\n{read.describe()}"
    assert read["title"] == "before archiving"
