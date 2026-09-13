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
    #: The list of tasks, and the box one task's title is drawn into.
    #:
    #: There is deliberately no heading locator here, and the reason is worth
    #: writing down because it is a trap. The project view has no visible
    #: heading of its own: its `<h1>` carries `project-title-print` and is
    #: `display: none` on screen, and the visible `.project-title` is the
    #: entry in the navigation, outside `<main>`. So a heading found by text
    #: says only that the project exists somewhere on the page — it appears
    #: as soon as the sidebar loads, for anyone the project is shared with,
    #: whether or not the view itself ever rendered. The task list is the
    #: thing that means the view has painted.
    _TASK_LIST = ".tasks"
    _TASK_TEXT = ".tasktext"
    #: One row of the list view, and the box that finishes the task in it.
    #: The checkbox is the product's own `data-cy` hook, which only exists
    #: because the session injects the testing flag.
    _TASK_ROW = ".tasks .task"
    _DONE_BOX = "[data-cy=checkbox] label"
    #: The board. A card carries the task's identifier, which is what makes
    #: it possible to say which card moved rather than which text moved.
    _BUCKET = ".kanban .bucket"
    _BUCKET_TITLE = ".bucket-header .title"
    _CARD = ".kanban-card"
    #: How a drag is delivered: enough intermediate positions for a sortable
    #: to recognise one, and a drop near the top of the target column.
    _DRAG_STEPS = 25
    _DROP_DEPTH = 80

    def __init__(self, page: Page) -> None:
        self.page = page

    #: A settings screen opens as a dialog over the project. `modalPrimary`
    #: is the product's own hook on the button that carries the action out.
    _CONFIRMATION = ".modal-content"
    _CONFIRM = "[data-cy=modalPrimary]"

    def open(self, project_id: int, view_id: int | None = None) -> ProjectPage:
        path = f"/projects/{project_id}" + (f"/{view_id}" if view_id is not None else "")
        self.page.goto(path)
        return self

    def open_settings(self, project_id: int, screen: str) -> ProjectPage:
        """One of the project's settings dialogs, by the name in its URL."""
        self.page.goto(f"/projects/{project_id}/settings/{screen}")
        return self

    @property
    def confirmation(self) -> Locator:
        """The dialog a settings screen opens in."""
        return self.page.locator(self._CONFIRMATION)

    @property
    def confirm(self) -> Locator:
        """The button that carries the dialog's action out."""
        return self.page.locator(self._CONFIRM)

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

    @property
    def task_list(self) -> Locator:
        """The list the tasks are drawn into.

        What a test waits for before asserting that something is *not* on
        the page: an absence measured while the view is still painting is
        not an absence.
        """
        return self.page.locator(self._TASK_LIST)

    def task_row(self, title: str) -> Locator:
        """One row of the list view, whole. What a person clicks on."""
        return self.page.locator(self._TASK_ROW).filter(has_text=title)

    def done_box(self, title: str) -> Locator:
        """The box that finishes a task from the list.

        The label rather than the input: the input is `is-sr-only`, so
        Playwright refuses to click it and the label is what a person hits.
        """
        return self.task_row(title).locator(self._DONE_BOX)

    def bucket(self, title: str) -> Locator:
        """One column of the board, found by its heading.

        By the heading and not by the column's text, because a column
        contains its cards: a board with a task called "Done" in it would
        otherwise have two columns answering to that name.
        """
        return self.page.locator(self._BUCKET).filter(
            has=self.page.locator(self._BUCKET_TITLE, has_text=title)
        )

    def card(self, title: str) -> Locator:
        return self.page.locator(self._CARD).filter(has_text=title)

    def drag_card_into(self, title: str, bucket_title: str) -> None:
        """Move a card to another column the way a hand does.

        Not `Locator.drag_to`, and not for want of trying. That helper
        speaks HTML5 drag-and-drop, and this board has no `draggable`
        attribute anywhere on it: the columns are a pointer-driven sortable,
        which starts a drag only after a press followed by movement. A
        single jump from source to target never crosses that threshold, so
        the card is picked up and put straight back down.

        Hence the steps. They are not a pause waiting for the product —
        there is no sleep here and the suite's rule against one stands — but
        the gesture itself: a drag is a path, and sending it as a path is
        what makes it a drag.
        """
        card, bucket = self.card(title).first, self.bucket(bucket_title).first
        card.scroll_into_view_if_needed()
        from_box, to_box = card.bounding_box(), bucket.bounding_box()
        if from_box is None or to_box is None:
            raise AssertionError(
                f"cannot drag {title!r} into {bucket_title!r}: "
                f"card box {from_box}, column box {to_box}"
            )

        start = (from_box["x"] + from_box["width"] / 2, from_box["y"] + from_box["height"] / 2)
        # Near the top of the column rather than its middle: a column is tall
        # and mostly empty, and its lower half can fall outside the viewport.
        end = (to_box["x"] + to_box["width"] / 2, to_box["y"] + self._DROP_DEPTH)

        self.page.mouse.move(*start)
        self.page.mouse.down()
        for step in range(1, self._DRAG_STEPS + 1):
            fraction = step / self._DRAG_STEPS
            self.page.mouse.move(
                start[0] + (end[0] - start[0]) * fraction,
                start[1] + (end[1] - start[1]) * fraction,
            )
        self.page.mouse.up()

    def task_text(self, title: str) -> Locator:
        """The box one task's title is drawn into, and the box that clips it.

        Separate from `task` because the two answer different questions. The
        title itself sits in an inline `<a>`, and an inline box has no width
        of its own: `scrollWidth` and `clientWidth` both read zero, so a
        layout measurement taken on it says "it fits" whatever the text is.
        """
        return self.page.locator(self._TASK_TEXT).filter(has_text=title)
