"""Typing structure into a plain sentence.

Quick add lets someone write "pay the invoice *urgent !3" and get a task
with a label and a priority. The parsing lives in the frontend, so the API
cannot be asked whether it works. What the API can do is confirm the result,
and that confirmation is what gives the check its worth.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from playwright.sync_api import expect

from vikunja_qa.scenes import Scene
from vikunja_qa.ui.pages.project import ProjectPage

pytestmark = pytest.mark.covers("UI")

TaskLookup = Callable[[str], dict[str, Any] | None]


@pytest.mark.smoke
def test_a_label_and_a_priority_are_parsed_out_of_the_title(
    project_page: ProjectPage, ui_scene: Scene, task_on_server: TaskLookup
) -> None:
    project_page.open(ui_scene.project_id)

    project_page.add_task("pay the invoice *urgent !3")
    expect(project_page.task("pay the invoice")).to_be_visible()

    created = task_on_server("pay the invoice")
    assert created is not None, "the task never reached the server"
    assert created["priority"] == 3, f"the typed priority was not parsed: {created['priority']}"
    labels = [label["title"] for label in created.get("labels") or []]
    assert "urgent" in labels, f"the typed label was not parsed: {labels}"


def test_the_markers_are_stripped_from_the_title(
    project_page: ProjectPage, ui_scene: Scene, task_on_server: TaskLookup
) -> None:
    """The parsed parts must leave the title, or every task ends up named
    after its own syntax."""
    project_page.open(ui_scene.project_id)

    project_page.add_task("renew the licence *annual !2")
    expect(project_page.task("renew the licence")).to_be_visible()

    created = task_on_server("renew the licence")
    assert created is not None, "the task never reached the server"
    assert "*annual" not in created["title"], f"a label marker survived: {created['title']!r}"
    assert "!2" not in created["title"], f"a priority marker survived: {created['title']!r}"
