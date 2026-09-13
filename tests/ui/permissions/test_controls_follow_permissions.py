"""The screen offers only what the server will allow.

The server enforces permissions whatever the interface shows, so a control
offered to someone who cannot use it is not a security hole. It is still a
defect: the person acts, and is refused.
"""

from __future__ import annotations

import pytest
from playwright.sync_api import expect

from vikunja_qa.domain.permissions import Permission
from vikunja_qa.scenes import SceneBuilder
from vikunja_qa.ui.pages.project import ProjectPage
from vikunja_qa.ui.session import PageOpener

pytestmark = pytest.mark.covers("UI")


def test_a_reader_is_not_offered_the_add_task_control(
    scene: SceneBuilder, open_as: PageOpener
) -> None:
    """Asked as a comparison, because an absence on its own proves nothing.

    `to_have_count(0)` is satisfied on its very first poll, so a page that
    has not rendered yet answers it exactly as well as a page that correctly
    withholds the control. Two things rule that out here. The view is waited
    for by something that only exists once it has painted — the task list,
    with this project's task in it. And the owner's view of the same project
    is checked in the same run: the control is there for one caller and not
    for the other, so neither result can be an artefact of timing.
    """
    world = (
        scene.project(title="shared read only")
        .member("reader", Permission.READ)
        .task(title="write the report")
        .done()
    )

    def open_project(role: str) -> ProjectPage:
        page = ProjectPage(open_as(world.actor(role))).open(world.project_id)
        expect(page.task_list).to_be_visible()
        expect(page.task("write the report")).to_be_visible()
        return page

    expect(open_project("owner").add_task_field).to_have_count(1)
    expect(open_project("reader").add_task_field).to_have_count(0)
