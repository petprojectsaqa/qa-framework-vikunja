"""Fixtures for the browser layer.

Built on pytest-playwright's own machinery rather than beside it. Contexts
come from its `new_context` factory, so `--tracing`, `--video` and
`--screenshot` work as documented, and the base URL arrives through its
`base_url` fixture. Its `page` fixture is used as is, on top of a `context`
that is already signed in.

Everything a browser test needs is prepared over the API, so a page opens
signed in and looking at the data under examination.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

import pytest
from allure_commons.types import AttachmentType
from playwright.sync_api import BrowserContext, Page, expect

from vikunja_qa import reporting
from vikunja_qa.actors.actor import Actor
from vikunja_qa.config import Settings
from vikunja_qa.scenes import Scene, SceneBuilder
from vikunja_qa.ui.pages.project import ProjectPage
from vikunja_qa.ui.session import DEFAULT_LOCALE, VIEWPORT, PageOpener, sign_in

NewContext = Callable[..., BrowserContext]


# --- pytest-playwright configuration ---------------------------------------


@pytest.fixture(scope="session")
def base_url(settings: Settings) -> str:
    """Consumed by pytest-playwright, which sets it on every context."""
    return settings.base_url


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args: dict[str, Any]) -> dict[str, Any]:
    """The pinned viewport, on top of what pytest-playwright sets, including
    the video directory when `--video` asks for one.

    The locale is deliberately not here. The factory passes these arguments
    and its own keyword arguments to Playwright side by side, so a locale set
    in both places is a TypeError rather than an override. It is given where
    contexts are made instead, which is only in the two fixtures below.
    """
    return {**browser_context_args, "viewport": VIEWPORT}


#: How long `expect` keeps retrying before failing. Set once here rather than
#: repeated on every assertion; a first paint on a cold stand can be slow.
EXPECT_TIMEOUT_MS = 15_000


@pytest.fixture(scope="session", autouse=True)
def _expect_timeout() -> None:
    expect.set_options(timeout=EXPECT_TIMEOUT_MS)


# --- data -------------------------------------------------------------------


@pytest.fixture
def ui_scene(scene: SceneBuilder) -> Scene:
    """A project with a handful of tasks, built entirely over the API."""
    return (
        scene.project(title="browser scenario")
        .task("first", title="write the report")
        .task("second", title="review the draft")
        .task("third", title="send it on")
        .done()
    )


@pytest.fixture
def task_on_server(ui_scene: Scene) -> Callable[[str], dict[str, Any] | None]:
    """Look up, over the API, a task the page appeared to create.

    A browser test confirms its effect on the server as well as on screen:
    a change that only shows in the page has not really happened.
    """

    def find(title_fragment: str) -> dict[str, Any] | None:
        listed = ui_scene.owner.api.tasks.all()
        assert listed.ok, listed.describe()
        return next(
            (
                dict(task)
                for task in listed.json
                if task.get("project_id") == ui_scene.project_id
                and title_fragment in task.get("title", "")
            ),
            None,
        )

    return find


# --- browsers ---------------------------------------------------------------


@pytest.fixture
def context(
    new_context: NewContext, ui_scene: Scene, request: pytest.FixtureRequest
) -> Iterator[BrowserContext]:
    """Signed in as the scene's owner. pytest-playwright's `page` fixture
    opens its page in this context, so tests simply ask for `page`."""
    signed_in = sign_in(new_context(locale=DEFAULT_LOCALE), ui_scene.owner)
    yield signed_in
    _attach_on_failure(request, [signed_in])


@pytest.fixture
def open_as(new_context: NewContext, request: pytest.FixtureRequest) -> Iterator[PageOpener]:
    """A page signed in as any actor, in any locale.

    For tests that need someone other than the scene's owner, or a
    different language. Contexts still come from the factory, so traces
    and videos are recorded for these too.
    """
    opened: list[BrowserContext] = []

    def open_page(actor: Actor, *, locale: str = DEFAULT_LOCALE) -> Page:
        signed_in = sign_in(new_context(locale=locale), actor)
        opened.append(signed_in)
        return signed_in.new_page()

    yield open_page
    _attach_on_failure(request, opened)


@pytest.fixture
def project_page(page: Page) -> ProjectPage:
    return ProjectPage(page)


def _attach_on_failure(request: pytest.FixtureRequest, contexts: list[BrowserContext]) -> None:
    """Put the screen and the page source into the report when a test fails.

    pytest-playwright already saves artifacts to disk; this puts the two
    most useful ones where a reader of the report looks first. It runs in
    the fixture's teardown, before the factory closes the contexts, so the
    pages are still there to photograph.
    """
    report = getattr(request.node, "rep_call", None)
    if report is None or not report.failed:
        return
    for context in contexts:
        for number, open_page in enumerate(context.pages, start=1):
            reporting.attach(
                open_page.screenshot(full_page=True),
                name=f"screen {number} at failure",
                kind=AttachmentType.PNG,
            )
            reporting.attach(
                open_page.content(),
                name=f"page {number} source at failure",
                kind=AttachmentType.HTML,
            )
