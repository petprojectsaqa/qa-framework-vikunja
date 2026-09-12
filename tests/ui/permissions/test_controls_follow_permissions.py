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
    world = scene.project(title="shared read only").member("reader", Permission.READ).done()
    project = ProjectPage(open_as(world.actor("reader"))).open(world.project_id)

    expect(project.heading("shared read only")).to_be_visible()
    expect(project.add_task_field).to_have_count(0)
