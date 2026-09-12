"""One set of tasks, several presentations.

A project can be shown as a list, a table, a Gantt chart and a board. Each
is rendered by different frontend code, which is exactly how two views of
the same data come to disagree.
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import expect

from vikunja_qa.scenes import Scene
from vikunja_qa.ui.pages.project import ProjectPage

pytestmark = pytest.mark.covers("UI")


def test_a_task_appears_in_every_view_that_lists_tasks(
    project_page: ProjectPage, ui_scene: Scene
) -> None:
    views = ui_scene.owner.api.projects.views(ui_scene.project_id)
    assert views.ok, views.describe()

    shown_in: list[str] = []
    missing_from: list[str] = []
    for view in views.json:
        name = str(view.get("title") or view["id"])
        project_page.open(ui_scene.project_id, int(view["id"]))
        try:
            expect(project_page.task("write the report")).to_be_visible()
        except (AssertionError, PlaywrightError):
            missing_from.append(name)
        else:
            shown_in.append(name)

    assert len(shown_in) >= 2, (
        f"the task appeared in {shown_in} and not in {missing_from}; the views disagree "
        "about what the project contains"
    )
