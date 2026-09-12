"""The interface in more than one language.

Only the English wording is pinned. For other languages the check is that
the wording changed at all, because asserting a particular translation
would test the translators rather than the product.
"""

from __future__ import annotations

import pytest
from playwright.sync_api import expect

from vikunja_qa.scenes import Scene
from vikunja_qa.ui.pages.project import ProjectPage
from vikunja_qa.ui.session import PageOpener

pytestmark = pytest.mark.covers("I18")

ENGLISH_PLACEHOLDER = "Add a task…"


@pytest.mark.parametrize("locale", ["de-DE", "ru-RU"])
def test_the_interface_follows_the_browser_language(
    ui_scene: Scene, open_as: PageOpener, locale: str
) -> None:
    project = ProjectPage(open_as(ui_scene.owner, locale=locale)).open(ui_scene.project_id)

    expect(project.add_task_field).to_be_visible()
    placeholder = project.add_task_field.get_attribute("placeholder")

    assert placeholder, f"no placeholder rendered for {locale}"
    assert placeholder != ENGLISH_PLACEHOLDER, f"{locale} fell back to English: {placeholder!r}"


def test_english_is_the_pinned_default(project_page: ProjectPage, ui_scene: Scene) -> None:
    """The suite pins its locale so text selectors never depend on the
    machine running it. This proves the pin holds."""
    project_page.open(ui_scene.project_id)

    expect(project_page.add_task_field).to_have_attribute("placeholder", ENGLISH_PLACEHOLDER)


def test_a_long_title_is_not_cut_off_by_its_container(
    project_page: ProjectPage, ui_scene: Scene
) -> None:
    """Translation lengthens text, and a layout that only fits English
    breaks quietly. Measured rather than eyeballed."""
    long_title = "Überprüfung der Zusammenarbeitsvereinbarung mit dem Verwaltungsrat"
    created = ui_scene.owner.api.tasks.create(ui_scene.project_id, long_title)
    assert created.ok, created.describe()

    project_page.open(ui_scene.project_id)
    element = project_page.task(long_title)
    expect(element).to_be_visible()

    geometry = element.evaluate(
        "el => ({ scroll: el.scrollWidth, client: el.clientWidth,"
        " overflow: getComputedStyle(el).textOverflow })"
    )
    fits = geometry["scroll"] <= geometry["client"] + 1
    trimmed = geometry["overflow"] == "ellipsis"
    assert fits or trimmed, f"a long title overflows its container untrimmed: {geometry}"
