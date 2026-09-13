"""Finishing a task by ticking the box in the list.

The box is the shortest path in the whole product and the one people use
most. It is also frontend work end to end: the row decides what to send,
which task it is for, and what to do with the answer. The API has an
endpoint for marking a task done and the api layer covers it; what cannot
be asked there is whether the box in front of a person is wired to it.

The server is asked afterwards, because a row that crosses itself out
locally and sends nothing looks exactly the same on screen.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from playwright.sync_api import expect

from vikunja_qa.scenes import Scene
from vikunja_qa.ui.pages.project import ProjectPage
from vikunja_qa.waiting import wait_until

pytestmark = pytest.mark.covers("UI")

TaskLookup = Callable[[str], dict[str, Any] | None]

#: The click sends its request and returns; the round trip lands in about a
#: third of a second on this stand. Polled rather than paused, and given
#: room for a slow one.
SERVER_BUDGET_S = 15


@pytest.mark.smoke
def test_ticking_the_box_finishes_that_task_and_no_other(
    project_page: ProjectPage, ui_scene: Scene, task_on_server: TaskLookup
) -> None:
    """Two claims in one, and the second is the one worth having.

    That the task is finished says the box is wired to something. That the
    two beside it are untouched says it is wired to the right row — the
    defect this is really watching for is a list that sends the position of
    a row rather than the identity of a task, which passes every check made
    of one task on its own.
    """
    project_page.open(ui_scene.project_id)
    expect(project_page.task_row("write the report")).to_be_visible()

    project_page.done_box("write the report").click()

    def finished_on_the_server() -> bool | None:
        task = task_on_server("write the report")
        assert task is not None, "the task vanished from the project"
        return task["done"] or None

    wait_until(
        finished_on_the_server,
        timeout=SERVER_BUDGET_S,
        because="the server has the ticked task marked done",
    )

    for untouched in ("review the draft", "send it on"):
        other = task_on_server(untouched)
        assert other is not None, f"{untouched!r} vanished from the project"
        assert other["done"] is False, f"ticking one box also finished {untouched!r}"
