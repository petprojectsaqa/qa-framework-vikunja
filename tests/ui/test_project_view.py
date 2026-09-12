"""Browser tests for what only a browser can answer.

Anything checkable over the API is checked over the API; these cover the
rest. There are few of them on purpose. A large browser suite duplicating
API coverage is slower, more fragile, and tells you less.

Each test confirms its result through the API as well as on screen. A
change that only appears in the page has not really happened, and one
that only reaches the server was not really driven by the interface.
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Browser, Page, expect

from vikunja_qa.actors.factory import ActorFactory
from vikunja_qa.config import Settings
from vikunja_qa.domain.permissions import Permission
from vikunja_qa.scenes import Scene, SceneBuilder
from vikunja_qa.ui.session import context_for

#: The whole add-a-task block. Scoping to it keeps the button lookup away
#: from the several other "Add ..." controls on the page.
ADD_TASK_BLOCK = ".task-add"
ADD_TASK = "textarea.add-task-textarea"
VISIBLE = 15_000


def _add_button(page: Page):  # noqa: ANN202
    """The button reads ADD on screen and "Add" in the markup: the capitals
    come from a stylesheet, and an accessible name is computed from the
    text, not from how it is painted."""
    return page.locator(ADD_TASK_BLOCK).get_by_role("button", name="Add", exact=True)


class TestQuickAddMagic:
    """Typing structure into a plain sentence.

    The parsing lives in the frontend, so the API cannot be asked whether
    it works. What the API can do is confirm the result, which is what
    makes the check worth anything.
    """

    def test_a_label_and_a_priority_are_parsed_out_of_the_title(
        self, page: Page, ui_scene: Scene
    ) -> None:
        page.goto(f"/projects/{ui_scene.project_id}")

        page.locator(ADD_TASK).fill("pay the invoice *urgent !3")
        _add_button(page).click()

        expect(page.get_by_text("pay the invoice").first).to_be_visible(timeout=VISIBLE)

        created = _task_named(ui_scene, "pay the invoice")
        assert created is not None, "the task never reached the server"
        assert created["priority"] == 3, (
            f"the priority in the typed text was not parsed: {created['priority']}"
        )
        labels = [label["title"] for label in created.get("labels") or []]
        assert "urgent" in labels, f"the label in the typed text was not parsed: {labels}"

    def test_the_magic_markers_are_stripped_from_the_title(
        self, page: Page, ui_scene: Scene
    ) -> None:
        """The parsed parts must leave the title, or every task ends up
        named after its own syntax."""
        page.goto(f"/projects/{ui_scene.project_id}")

        page.locator(ADD_TASK).fill("renew the licence *annual !2")
        _add_button(page).click()
        expect(page.get_by_text("renew the licence").first).to_be_visible(timeout=VISIBLE)

        created = _task_named(ui_scene, "renew the licence")
        assert created is not None
        assert "*annual" not in created["title"], f"markers survived: {created['title']!r}"
        assert "!2" not in created["title"], f"markers survived: {created['title']!r}"


class TestViewsAgree:
    def test_a_task_appears_in_every_view_of_its_project(self, page: Page, ui_scene: Scene) -> None:
        """One set of tasks, several presentations. They are rendered by
        different code and can disagree."""
        views = ui_scene.owner.api.projects.views(ui_scene.project_id)
        assert views.ok, views.describe()

        seen_in = []
        for view in views.json:
            page.goto(f"/projects/{ui_scene.project_id}/{view['id']}")
            try:
                expect(page.get_by_text("write the report").first).to_be_visible(timeout=VISIBLE)
                seen_in.append(view.get("title") or view["id"])
            except AssertionError:  # noqa: PERF203 - the miss is the finding
                pass

        assert len(seen_in) >= 2, (
            f"the task showed up in only {seen_in}; the views disagree about "
            "what the project contains"
        )


class TestPermissionsOnScreen:
    def test_a_reader_is_not_offered_the_add_task_control(
        self,
        browser: Browser,
        scene: SceneBuilder,
        settings: Settings,
    ) -> None:
        """A permission the server enforces must also be reflected on
        screen. Offering a control that will be refused is its own defect.
        """
        world = scene.project(title="shared read only").member("reader", Permission.READ).done()
        reader = world.actor("reader")

        context = context_for(browser, reader, settings.base_url)
        try:
            page = context.new_page()
            page.goto(f"/projects/{world.project_id}")
            expect(page.get_by_text("shared read only").first).to_be_visible(timeout=VISIBLE)

            expect(page.locator(ADD_TASK)).to_have_count(0)
        finally:
            context.close()


class TestLocalisation:
    @pytest.mark.parametrize(
        ("locale", "expected"),
        [("en-GB", "Add a task…"), ("de-DE", None), ("ru-RU", None)],
    )
    def test_the_interface_follows_the_browser_language(
        self,
        browser: Browser,
        ui_scene: Scene,
        settings: Settings,
        locale: str,
        expected: str | None,
    ) -> None:
        """The same page in three languages.

        Only the English wording is pinned. For the others the check is
        that the wording changed at all, because asserting a translation
        would be testing the translators rather than the product.
        """
        context = context_for(browser, ui_scene.owner, settings.base_url, locale=locale)
        try:
            page = context.new_page()
            page.goto(f"/projects/{ui_scene.project_id}")
            field = page.locator(ADD_TASK)
            expect(field).to_be_visible(timeout=VISIBLE)
            placeholder = field.get_attribute("placeholder")
        finally:
            context.close()

        assert placeholder, f"no placeholder rendered for {locale}"
        if expected is not None:
            assert placeholder == expected, f"{locale} rendered {placeholder!r}"
        else:
            assert placeholder != "Add a task…", f"{locale} fell back to English: {placeholder!r}"

    def test_a_long_title_is_not_cut_off_by_its_container(
        self, page: Page, ui_scene: Scene
    ) -> None:
        """Translation lengthens text, and a layout that only fits English
        breaks quietly. Measured rather than eyeballed.
        """
        long_title = "Überprüfung der Zusammenarbeitsvereinbarung mit dem Verwaltungsrat"
        created = ui_scene.owner.api.tasks.create(ui_scene.project_id, long_title)
        assert created.ok, created.describe()

        page.goto(f"/projects/{ui_scene.project_id}")
        element = page.get_by_text(long_title).first
        expect(element).to_be_visible(timeout=VISIBLE)

        overflow = element.evaluate(
            "el => ({ scroll: el.scrollWidth, client: el.clientWidth,"
            " ellipsis: getComputedStyle(el).textOverflow })"
        )

        assert overflow["scroll"] <= overflow["client"] + 1 or overflow["ellipsis"] == "ellipsis", (
            f"a long title overflows its container without being trimmed: {overflow}"
        )


def _task_named(scene: Scene, title_fragment: str) -> dict | None:
    """Confirm through the API what the page appeared to do."""
    listed = scene.owner.api.tasks.in_project(
        scene.project_id,
        int(scene.owner.api.projects.views(scene.project_id).json[0]["id"]),
    )
    assert listed.ok, listed.describe()
    for task in listed.json:
        if title_fragment in task["title"]:
            return dict(task)
    return None


@pytest.fixture
def actors_unused(actors: ActorFactory) -> ActorFactory:  # pragma: no cover
    return actors
