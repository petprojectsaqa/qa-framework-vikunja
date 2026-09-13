"""Dragging a card across the board.

The one thing in this product that has no API shape at all. There is an
endpoint for moving a task into a bucket, and the api layer covers it; the
drag is the frontend deciding that a press, a path and a release mean that
call, with that task, into that column. A board whose drop handler sends
the wrong bucket, or sends nothing and only rearranges the screen, answers
every API question correctly.

The board also carries a rule of its own: the last column finishes what is
put in it. That is two subsystems agreeing, and it is worth asking of the
gesture rather than of the endpoint.
"""

from __future__ import annotations

from typing import Any

import pytest
from playwright.sync_api import expect

from vikunja_qa.scenes import Scene, SceneBuilder
from vikunja_qa.ui.pages.project import ProjectPage
from vikunja_qa.ui.session import PageOpener
from vikunja_qa.waiting import wait_until

pytestmark = pytest.mark.covers("UI")

DONE_COLUMN = "Done"
#: The drop sends its request and returns. Polled, not paused.
SERVER_BUDGET_S = 15


@pytest.fixture
def world(scene: SceneBuilder) -> Scene:
    return scene.project(title="a board").task("dragged", title="drag me").done()


def _board(world: Scene) -> dict[str, Any]:
    views = world.owner.api.projects.views(world.project_id)
    assert views.ok, views.describe()
    board = next((view for view in views.json if view.get("view_kind") == "kanban"), None)
    assert board is not None, (
        f"the project has no board: {[view.get('view_kind') for view in views.json]}"
    )
    return dict(board)


@pytest.mark.smoke
def test_dragging_a_card_into_done_finishes_the_task(world: Scene, open_as: PageOpener) -> None:
    """The gesture, end to end: the card lands in the column, and the task
    it stands for is finished on the server.

    Both halves are needed. The card arriving proves only that the screen
    rearranged itself; the server proves the drop was a request. Neither on
    its own says the board did what it looked like it did.
    """
    page = ProjectPage(open_as(world.owner)).open(world.project_id, int(_board(world)["id"]))
    expect(page.card("drag me")).to_be_visible()
    assert not world.owner.api.tasks.get(world.task_id)["done"], "the task started out finished"

    page.drag_card_into("drag me", DONE_COLUMN)

    expect(page.bucket(DONE_COLUMN).locator(".kanban-card")).to_have_count(1)

    def finished() -> bool | None:
        task = world.owner.api.tasks.get(world.task_id)
        assert task.ok, task.describe()
        return bool(task["done"]) or None

    wait_until(
        finished,
        timeout=SERVER_BUDGET_S,
        because="the server has the dragged task marked done",
    )


def test_a_card_dragged_into_an_ordinary_column_is_moved_and_not_finished(
    world: Scene, open_as: PageOpener
) -> None:
    """The control for the test above.

    Without it, a board that finished every task it was handed — whichever
    column it was dropped into — would pass. "Doing" is an ordinary column,
    so a task that lands there has moved and nothing more.
    """
    page = ProjectPage(open_as(world.owner)).open(world.project_id, int(_board(world)["id"]))
    expect(page.card("drag me")).to_be_visible()

    page.drag_card_into("drag me", "Doing")

    expect(page.bucket("Doing").locator(".kanban-card")).to_have_count(1)
    expect(page.bucket(DONE_COLUMN).locator(".kanban-card")).to_have_count(0)

    task = world.owner.api.tasks.get(world.task_id)
    assert task.ok, task.describe()
    assert task["done"] is False, (
        "a card dropped into an ordinary column was marked done; only the last column does that"
    )
