"""Proves the browser arrives signed in, looking at data built over the API.

A framework area: these prove the harness rather than a product feature.
Every other browser test rests on them, so if one fails, the rest are
reporting on how the session got there rather than on what they examine.
"""

from __future__ import annotations

import re

import pytest
from playwright.sync_api import Page, expect

from vikunja_qa.scenes import Scene
from vikunja_qa.ui.pages.project import ProjectPage

#: A regular expression on purpose. Given a plain string, Playwright joins
#: it to the base URL and compares the whole URL exactly, so a glob such as
#: "**/login" would never match and the assertion could never fail.
LOGIN_PAGE = re.compile(r"/login(\?|$)")


@pytest.mark.smoke
def test_the_browser_lands_signed_in(page: Page, ui_scene: Scene) -> None:
    page.goto("/")

    expect(page).not_to_have_url(LOGIN_PAGE)
    expect(page.get_by_text(ui_scene.project["title"]).first).to_be_visible()


def test_the_testing_flag_reaches_the_application(page: Page) -> None:
    """The flag that makes the product emit its test attributes.

    The production build strips them unless a runner injects it. If the
    injection ever stopped working, every attribute-based selector would
    fail at once; better to learn that here, with a message that says so.
    """
    page.goto("/")

    assert page.evaluate("window.TESTING") is True, (
        "the testing flag did not reach the page, so data-cy attributes will be absent"
    )


@pytest.mark.smoke
def test_a_task_made_over_the_api_is_visible_in_the_browser(
    project_page: ProjectPage, ui_scene: Scene
) -> None:
    """The link the whole approach rests on: state built over the API is
    what the browser shows."""
    project_page.open(ui_scene.project_id)

    expect(project_page.task("write the report")).to_be_visible()
