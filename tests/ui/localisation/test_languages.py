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
    # Both of these retry, which is the point. The language bundles are
    # fetched after the page mounts, so the field is visible for a moment
    # still carrying the English fallback. A single `get_attribute` read
    # lands in that moment often enough to look like the product failing to
    # translate, and the message even said so.
    expect(project.add_task_field).not_to_have_attribute("placeholder", "")
    expect(project.add_task_field).not_to_have_attribute("placeholder", ENGLISH_PLACEHOLDER)


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
    element = project_page.task_text(long_title)
    expect(element).to_be_visible()

    geometry = element.evaluate(
        "el => { const style = getComputedStyle(el); return {"
        "   scroll: el.scrollWidth, client: el.clientWidth,"
        "   overflow: style.overflow, textOverflow: style.textOverflow,"
        "   whiteSpace: style.whiteSpace }; }"
    )

    # Said first, because everything below is meaningless without it: an
    # inline box reports zero for both widths, so a measurement taken on one
    # answers "it fits" for any text at all, and this check used to.
    assert geometry["client"] > 0, (
        f"measured an element with no layout box, so nothing was measured: {geometry}"
    )
    fits = geometry["scroll"] <= geometry["client"] + 1
    # An ellipsis trims nothing on its own: the box also has to hide its
    # overflow and keep the text on one line for it to have any effect.
    trimmed = (
        geometry["textOverflow"] == "ellipsis"
        and geometry["overflow"] != "visible"
        and geometry["whiteSpace"] in ("nowrap", "pre")
    )
    assert fits or trimmed, f"a long title overflows its container untrimmed: {geometry}"
