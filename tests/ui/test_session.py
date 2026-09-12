"""Proves the browser arrives already signed in.

Not a product test. It exists so that a failure in any other browser test
can be trusted to be about the feature under examination rather than
about how the session got there.
"""

from __future__ import annotations

from playwright.sync_api import Page, expect

from vikunja_qa.scenes import Scene


def test_the_browser_lands_signed_in(page: Page, ui_scene: Scene) -> None:
    page.goto("/")

    expect(page).not_to_have_url("**/login", timeout=15_000)
    expect(page.get_by_text(ui_scene.project["title"]).first).to_be_visible(timeout=15_000)


def test_the_testing_flag_reaches_the_application(page: Page) -> None:
    """The flag that makes the product emit its test attributes.

    Its production build strips them unless a runner injects this, so if
    the injection ever stops working every attribute-based selector in
    the suite fails at once. Better to learn that here.
    """
    page.goto("/")

    assert page.evaluate("window.TESTING") is True, (
        "the testing flag did not survive into the page, so data-cy attributes will be absent"
    )


def test_a_task_made_over_the_api_is_visible_in_the_browser(page: Page, ui_scene: Scene) -> None:
    """The link the whole approach rests on: state built over the API is
    what the browser sees."""
    page.goto(f"/projects/{ui_scene.project_id}")

    expect(page.get_by_text("write the report")).to_be_visible(timeout=15_000)
