"""A public link, opened by a browser that has never signed in.

The one flow in this product that exists only in the frontend. The API side
is a single call that trades a hash for a token, and the api layer covers
it; what the browser adds is everything around it — the route, the token
kept out of the address bar's path, the project rendered for someone with
no account, and the controls that must not appear for them.

Every other browser test here starts from a session placed in storage in
advance. These start from nothing at all, which is the whole point: a link
share is the one door a stranger walks through.
"""

from __future__ import annotations

import re

import pytest
from playwright.sync_api import expect

from vikunja_qa.domain.permissions import Permission
from vikunja_qa.scenes import SceneBuilder
from vikunja_qa.ui.pages.project import ProjectPage
from vikunja_qa.ui.session import AnonymousOpener

pytestmark = [pytest.mark.covers("UI"), pytest.mark.covers("ACL")]

SHARE_PASSWORD = "a-shared-secret-123"

#: A regular expression, for the reason `test_session.py` gives: a plain
#: string is joined to the base URL and compared whole.
SIGN_IN = re.compile(r"/login(\?|$)")


@pytest.mark.smoke
@pytest.mark.parametrize(
    ("permission", "add_task_controls"),
    [
        pytest.param(Permission.READ, 0, id="read-only"),
        pytest.param(Permission.WRITE, 1, id="writable"),
    ],
)
def test_a_public_link_offers_exactly_what_it_was_shared_for(
    scene: SceneBuilder,
    open_anonymously: AnonymousOpener,
    permission: Permission,
    add_task_controls: int,
) -> None:
    """What a stranger with the link gets, asked of both levels together.

    Both rows on purpose. `to_have_count(0)` is satisfied on its first poll,
    so a read-only share proves nothing on its own: a page that has not
    rendered answers it just as well. The writable row is what rules that
    out — the same page, the same wait, the same assertion, and the control
    is there. Between them the absence means something.
    """
    world = (
        scene.project(title="shared with the world")
        .task("visible", title="write the report")
        .share("guest", permission)
        .done()
    )
    share_hash = str(world.shares["guest"]["hash"])

    page = ProjectPage(open_anonymously(f"/share/{share_hash}/auth"))

    expect(page.task_list).to_be_visible()
    expect(page.task("write the report")).to_be_visible()
    expect(page.add_task_field).to_have_count(add_task_controls)


def test_a_link_share_reaches_only_the_project_it_was_made_for(
    scene: SceneBuilder, open_anonymously: AnonymousOpener
) -> None:
    """The boundary GHSA-2pv8-4c52-mf8j crossed, asked of the browser.

    The api layer asks it of the token directly. Here the question is
    whether the frontend, holding that token, can be pointed at another
    project and made to render it — which is a URL a curious visitor can
    simply type.

    The claim is the redirect, not the absence of the secret. "The other
    project's task is not on screen" is true of an error page, of a blank
    page and of a page that never loaded; being sent to sign in is a
    specific thing the product does, and it is what says the token was
    recognised as not covering this project.
    """
    world = (
        scene.project("shared", title="shared with the world")
        .task("visible", title="write the report")
        .share("guest", Permission.READ)
        .done()
    )
    private = world.owner.api.projects.create("kept to myself")
    assert private.ok, private.describe()
    hidden = world.owner.api.tasks.create(int(private["id"]), "the secret plan")
    assert hidden.ok, hidden.describe()
    share_hash = str(world.shares["guest"]["hash"])

    page = ProjectPage(open_anonymously(f"/share/{share_hash}/auth"))
    expect(page.task("write the report")).to_be_visible()

    page.open(int(private["id"]))

    expect(page.page).to_have_url(SIGN_IN)
    assert "the secret plan" not in page.page.locator("body").inner_text(), (
        "a link share made for one project rendered another project's task"
    )


def test_a_password_protected_link_shows_nothing_until_the_password_is_given(
    scene: SceneBuilder, open_anonymously: AnonymousOpener
) -> None:
    """A share behind a password is the frontend's only authentication form,
    and the only place in this product where a browser asks a stranger for a
    secret. What it must not do is render the project first and ask after.
    """
    world = (
        scene.project(title="behind a password")
        .task("visible", title="write the report")
        .share("locked", Permission.READ, password=SHARE_PASSWORD)
        .done()
    )
    share_hash = str(world.shares["locked"]["hash"])

    page = open_anonymously(f"/share/{share_hash}/auth")
    password = page.locator("input[type=password]")

    expect(password).to_be_visible()
    assert "write the report" not in page.locator("body").inner_text(), (
        "the project was rendered before the password was asked for"
    )

    password.fill(SHARE_PASSWORD)
    password.press("Enter")

    expect(ProjectPage(page).task("write the report")).to_be_visible()
