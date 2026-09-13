"""One set of tasks, several presentations.

A project can be shown as a list, a table, a Gantt chart and a board. Each
is rendered by different frontend code, which is exactly how two views of
the same data come to disagree.
"""

from __future__ import annotations

import pytest
from playwright.sync_api import expect

from vikunja_qa.scenes import Scene
from vikunja_qa.ui.pages.project import ProjectPage

pytestmark = pytest.mark.covers("UI")

#: Views that list tasks, by the kind the product gives them rather than by
#: their title, which is translated. Gantt is left out and that is the whole
#: reason this set is named: it plots by date and shows nothing for a task
#: with none, so its silence is correct and counting it would make the check
#: tolerate a real disagreement to accommodate it.
LISTS_TASKS = frozenset({"list", "table", "kanban"})


def test_a_task_appears_in_every_view_that_lists_tasks(
    project_page: ProjectPage, ui_scene: Scene
) -> None:
    views = ui_scene.owner.api.projects.views(ui_scene.project_id)
    assert views.ok, views.describe()
    listing = {
        str(view.get("view_kind")): int(view["id"])
        for view in views.json
        if str(view.get("view_kind")) in LISTS_TASKS
    }
    assert set(listing) == LISTS_TASKS, (
        f"the project offers {sorted(listing)} of the views that list tasks, "
        f"so this check would not have looked at {sorted(LISTS_TASKS - set(listing))}"
    )

    missing_from: list[str] = []
    for kind, view_id in sorted(listing.items()):
        project_page.open(ui_scene.project_id, view_id)
        try:
            # AssertionError only. A dead browser or a failed navigation
            # arrives as a PlaywrightError, and scoring that as "the view
            # does not show the task" reports a broken run as a product
            # defect — or, worse, lets a browser that died halfway pass.
            expect(project_page.task("write the report")).to_be_visible()
        except AssertionError:
            missing_from.append(kind)

    assert not missing_from, (
        f"the task is missing from {missing_from} while the other views show it, "
        "so the views disagree about what the project contains"
    )
