"""The page showing one project and its tasks.

A page object knows how to find things and how to act; it never decides
whether what it finds is right. Tests do that, with Playwright's `expect`,
against the locators this class hands back. Keeping selectors here means a
changed class name in the product is one edit, not a hunt through tests.

Selectors prefer roles and visible text, and fall back to structural
classes only where nothing accessible identifies an element. The product
emits few test attributes, so leaning on them would buy little.
"""

from __future__ import annotations

from playwright.sync_api import Locator, Page


class ProjectPage:
    #: The whole add-a-task block. Scoping lookups to it keeps them away
    #: from the several other "Add ..." controls elsewhere on the page.
    _ADD_TASK_BLOCK = ".task-add"
    _ADD_TASK_FIELD = "textarea.add-task-textarea"

    def __init__(self, page: Page) -> None:
        self.page = page

    def open(self, project_id: int, view_id: int | None = None) -> ProjectPage:
        path = f"/projects/{project_id}" + (f"/{view_id}" if view_id is not None else "")
        self.page.goto(path)
        return self

    # --- adding tasks -------------------------------------------------------

    @property
    def add_task_field(self) -> Locator:
        return self.page.locator(self._ADD_TASK_FIELD)

    @property
    def add_task_button(self) -> Locator:
        """Reads ADD on screen and "Add" in the markup: the capitals come
        from a stylesheet, and an accessible name is computed from text,
        not from how it is painted."""
        return self.page.locator(self._ADD_TASK_BLOCK).get_by_role("button", name="Add", exact=True)

    def add_task(self, text: str) -> None:
        self.add_task_field.fill(text)
        self.add_task_button.click()

    # --- reading ------------------------------------------------------------

    def task(self, title: str) -> Locator:
        return self.page.get_by_text(title).first

    def heading(self, title: str) -> Locator:
        return self.page.get_by_text(title).first
