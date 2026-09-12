"""Fixtures for the browser tests.

Everything a browser test needs is prepared over the API, so a page opens
already signed in and already looking at the data under examination.
"""

from __future__ import annotations

from collections.abc import Iterator

import allure
import pytest
from playwright.sync_api import Browser, BrowserContext, Page

from vikunja_qa.config import Settings
from vikunja_qa.scenes import Scene, SceneBuilder
from vikunja_qa.ui.session import context_for


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
def signed_in(browser: Browser, ui_scene: Scene, settings: Settings) -> Iterator[BrowserContext]:
    context = context_for(browser, ui_scene.owner, settings.base_url)
    yield context
    context.close()


@pytest.fixture
def page(signed_in: BrowserContext, request: pytest.FixtureRequest) -> Iterator[Page]:
    """A page, with the screenshot and the page source attached on failure.

    Attached only on failure: a green run has no use for them, and a red
    one is hard to diagnose without them.
    """
    page = signed_in.new_page()
    yield page

    report = getattr(request.node, "rep_call", None)
    if report is not None and report.failed:
        allure.attach(
            page.screenshot(full_page=True),
            name="screen at failure",
            attachment_type=allure.attachment_type.PNG,
        )
        allure.attach(
            page.content(),
            name="page source at failure",
            attachment_type=allure.attachment_type.HTML,
        )
    page.close()


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo):  # noqa: ANN201, ARG001
    """Expose each phase's result to fixtures, so teardown can tell a
    failure from a pass."""
    outcome = yield
    setattr(item, f"rep_{outcome.get_result().when}", outcome.get_result())
