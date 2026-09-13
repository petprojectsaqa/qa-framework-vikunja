"""Deleting a project, and the step in front of it.

The API has one call that deletes a project and the access matrix says who
may make it. What it cannot say is whether a person is asked first, because
the asking is entirely the frontend's: the route that offers to delete is a
URL, and a URL is something a person can be sent, can bookmark, or can land
on by pressing the wrong thing twice.

So the claim here is about what happens before anyone agrees to anything —
that arriving destroys nothing — and it is checked on the server, because a
project that is gone from the screen and present in the database is a
different defect from the one this is looking for.
"""

from __future__ import annotations

import pytest
from playwright.sync_api import expect

from vikunja_qa.scenes import Scene, SceneBuilder
from vikunja_qa.ui.pages.project import ProjectPage
from vikunja_qa.ui.session import PageOpener

pytestmark = pytest.mark.covers("UI")


@pytest.fixture
def world(scene: SceneBuilder) -> Scene:
    return scene.project(title="delete me carefully").task(title="not yet").done()


def test_opening_the_delete_page_deletes_nothing_until_it_is_confirmed(
    world: Scene, open_as: PageOpener
) -> None:
    """Arriving is not agreeing.

    The confirmation exists in the product; this says it is load-bearing.
    A dialog that deletes on arrival and asks afterwards looks identical in
    a screenshot and identical in the API log, and is only visible from
    here.
    """
    page = ProjectPage(open_as(world.owner)).open_settings(world.project_id, "delete")

    expect(page.confirmation).to_be_visible()

    still_there = world.owner.api.projects.get(world.project_id)
    assert still_there.ok, (
        "the project was deleted by opening the page that offers to delete it\n"
        f"{still_there.describe()}"
    )


def test_confirming_deletes_the_project(world: Scene, open_as: PageOpener) -> None:
    """The other half. Without it the test above would pass just as well
    against a button that does nothing at all."""
    page = ProjectPage(open_as(world.owner)).open_settings(world.project_id, "delete")
    expect(page.confirmation).to_be_visible()

    page.confirm.click()

    expect(page.confirmation).to_have_count(0)
    gone = world.owner.api.projects.get(world.project_id)
    assert gone.status == 404, f"the project survived a confirmed delete\n{gone.describe()}"
