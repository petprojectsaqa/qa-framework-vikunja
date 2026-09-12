"""One set of tasks behind two doors, the API and CalDAV.

A thin slice on purpose, as the coverage matrix sets out: not a CalDAV
conformance suite, but the checks that matter once the same data can be
reached two ways. Each asks whether the doors agree, in both directions,
because the two directions run through different code in the product.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest

from vikunja_qa.actors.actor import Actor
from vikunja_qa.domain import icalendar
from vikunja_qa.scenes import SceneBuilder
from vikunja_qa.testing.fixtures import CalendarOpener
from vikunja_qa.transport.response import ApiResponse

pytestmark = pytest.mark.covers("DAV")

#: Two scripts and a symbol, and long enough in octets to be folded on the
#: wire, so the product's unfolding is exercised along with its encoding.
NON_LATIN_TITLE = "Проверить квартальный отчёт перед отправкой — 四半期報告書を確認する ✓"


def _todos(answered: ApiResponse) -> list[icalendar.Component]:
    assert answered.ok, answered.describe()
    return icalendar.parse(answered.content).children("VTODO")


def _api_task(actor: Actor, project_id: int, title: str) -> dict[str, Any] | None:
    listed = actor.api.tasks.all()
    assert listed.ok, listed.describe()
    return next(
        (
            dict(task)
            for task in listed.json
            if task["project_id"] == project_id and task["title"] == title
        ),
        None,
    )


def _new_uid() -> str:
    return str(uuid.uuid4())


# --- what the API writes, the calendar reads ---------------------------------


@pytest.mark.smoke
def test_a_task_created_over_the_api_appears_in_the_calendar(
    scene: SceneBuilder, calendar_for: CalendarOpener
) -> None:
    world = scene.project().task(title="write the report").done()

    todos = _todos(calendar_for(world.owner).calendar(world.project_id))

    assert [todo.text_of("SUMMARY") for todo in todos] == ["write the report"]


def test_a_due_date_set_over_the_api_reaches_the_calendar(
    scene: SceneBuilder, calendar_for: CalendarOpener
) -> None:
    world = scene.project().task(title="file the return").done()
    due = datetime(2026, 11, 15, 8, 30, tzinfo=UTC)

    updated = world.owner.api.tasks.update(
        world.task_id, title="file the return", due_date=due.isoformat().replace("+00:00", "Z")
    )
    assert updated.ok, updated.describe()

    (todo,) = _todos(calendar_for(world.owner).calendar(world.project_id))
    stated = todo.first("DUE")
    assert stated is not None, "the calendar shows no due date for a task that has one"
    assert icalendar.parse_utc(stated.value) == due


def test_a_task_deleted_over_the_api_leaves_the_calendar(
    scene: SceneBuilder, calendar_for: CalendarOpener
) -> None:
    world = scene.project().task("kept", title="keep me").task("gone", title="delete me").done()

    deleted = world.owner.api.tasks.delete(int(world.tasks["gone"]["id"]))
    assert deleted.ok, deleted.describe()

    summaries = [
        todo.text_of("SUMMARY")
        for todo in _todos(calendar_for(world.owner).calendar(world.project_id))
    ]
    assert summaries == ["keep me"], f"the calendar still lists a deleted task: {summaries}"


# --- what a calendar client writes, the API reads -----------------------------


@pytest.mark.smoke
def test_a_task_saved_by_a_calendar_client_appears_in_the_api(
    scene: SceneBuilder, calendar_for: CalendarOpener
) -> None:
    world = scene.project().done()
    uid = _new_uid()

    saved = calendar_for(world.owner).put_todo(
        world.project_id, uid, icalendar.todo(uid, "book the venue")
    )
    assert saved.ok, saved.describe()

    assert _api_task(world.owner, world.project_id, "book the venue") is not None, (
        "a task saved over CalDAV never appeared in the API"
    )


def test_a_due_date_changed_by_a_calendar_client_reaches_the_api(
    scene: SceneBuilder, calendar_for: CalendarOpener
) -> None:
    """Saved once without a due date and again with one, which is how a
    calendar client edits: the same UID, a replacement document."""
    world = scene.project().done()
    calendar = calendar_for(world.owner)
    uid = _new_uid()
    due = datetime(2026, 12, 1, 17, 0, tzinfo=UTC)

    first = calendar.put_todo(world.project_id, uid, icalendar.todo(uid, "renew the lease"))
    assert first.ok, first.describe()
    edited = calendar.put_todo(
        world.project_id, uid, icalendar.todo(uid, "renew the lease", due=due)
    )
    assert edited.ok, edited.describe()

    task = _api_task(world.owner, world.project_id, "renew the lease")
    assert task is not None, "the task saved over CalDAV never appeared in the API"
    assert task["due_date"] == "2026-12-01T17:00:00Z"


def test_a_task_deleted_by_a_calendar_client_leaves_the_api(
    scene: SceneBuilder, calendar_for: CalendarOpener
) -> None:
    world = scene.project().done()
    calendar = calendar_for(world.owner)
    uid = _new_uid()

    saved = calendar.put_todo(world.project_id, uid, icalendar.todo(uid, "cancel the order"))
    assert saved.ok, saved.describe()
    task = _api_task(world.owner, world.project_id, "cancel the order")
    assert task is not None, "the task saved over CalDAV never appeared in the API"

    removed = calendar.delete_todo(world.project_id, uid)
    assert removed.ok, removed.describe()

    after = world.owner.api.tasks.get(int(task["id"]))
    assert after.status == 404, (
        f"a task deleted over CalDAV is still in the API\n{after.describe()}"
    )


# --- text that is not plain Latin -------------------------------------------


def test_a_non_latin_title_from_the_api_reads_back_unchanged_in_the_calendar(
    scene: SceneBuilder, calendar_for: CalendarOpener
) -> None:
    world = scene.project().task(title=NON_LATIN_TITLE).done()

    (todo,) = _todos(calendar_for(world.owner).calendar(world.project_id))

    assert todo.text_of("SUMMARY") == NON_LATIN_TITLE


def test_a_non_latin_title_from_a_calendar_client_reads_back_unchanged_in_the_api(
    scene: SceneBuilder, calendar_for: CalendarOpener
) -> None:
    world = scene.project().done()
    uid = _new_uid()

    saved = calendar_for(world.owner).put_todo(
        world.project_id, uid, icalendar.todo(uid, NON_LATIN_TITLE)
    )
    assert saved.ok, saved.describe()

    assert _api_task(world.owner, world.project_id, NON_LATIN_TITLE) is not None, (
        "the title did not survive the trip from a calendar client to the API"
    )
