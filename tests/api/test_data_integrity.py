"""Claims the API cannot settle about itself.

An API reports what it chose to report. When a delete is supposed to take
its children with it, or a refused bulk write is supposed to have applied
nothing, only the rows can say. These tests read the database directly
and never write to it: state is still built through the product.

The bulk cases are the point of this file. Checking permissions on the
first element of a list and then applying the whole list is a classic
defect, and it is invisible from the API side, because the refusal looks
identical whether or not something was written before it.
"""

from __future__ import annotations

from vikunja_qa.actors.factory import ActorFactory
from vikunja_qa.db import Database
from vikunja_qa.domain.permissions import Permission
from vikunja_qa.scenes import SceneBuilder, build


def test_deleting_a_project_leaves_no_orphaned_tasks(scene: SceneBuilder, db: Database) -> None:
    world = scene.project().task("a").task("b").task("c").done()
    project_id = world.project_id
    assert db.tasks_in_project(project_id) == 3

    deleted = world.owner.api.projects.delete(project_id)
    assert deleted.ok, deleted.describe()

    assert db.tasks_in_project(project_id) == 0, (
        "tasks survived their project; they are unreachable through the API "
        "but still hold the user's data"
    )


def test_a_refused_bulk_update_changes_nothing(
    scene: SceneBuilder, actors: ActorFactory, db: Database
) -> None:
    """Two tasks, one reachable and one not, in a single bulk write.

    The permission check has to hold for every identifier in the list. If
    it is consulted only for the first, the refusal still arrives but the
    rows have already moved.
    """
    mine = scene.project().task("mine", title="mine, untouched").done()
    # A second world with its own owner: the two accounts have never met,
    # so neither can reach the other's task by any legitimate route.
    stranger = build(actors).project().task("theirs", title="theirs, untouched").done()

    my_task = int(mine.tasks["mine"]["id"])
    their_task = int(stranger.tasks["theirs"]["id"])

    response = mine.owner.api.tasks.bulk_update(
        [my_task, their_task], title="changed by a bulk write"
    )

    assert not response.ok, (
        f"a bulk write naming a task the caller cannot reach was accepted\n{response.describe()}"
    )

    for task_id, expected in ((my_task, "mine, untouched"), (their_task, "theirs, untouched")):
        row = db.task(task_id)
        assert row is not None, f"task {task_id} disappeared"
        assert row["title"] == expected, (
            f"task {task_id} was modified by a bulk write that was refused; "
            "the check ran on part of the list only"
        )


def test_a_granted_permission_is_written_as_a_row(scene: SceneBuilder, db: Database) -> None:
    world = scene.project().member("reader", Permission.READ).done()

    granted = db.project_permissions(world.project_id)

    reader_id = world.actor("reader").user_id
    matching = [row for row in granted if row["user_id"] == reader_id]
    assert matching, f"no permission row for the reader; table holds {granted}"
    assert matching[0]["permission"] == int(Permission.READ), (
        f"the stored level is not the one granted: {matching[0]}"
    )


def test_an_attachment_is_recorded_against_its_task(scene: SceneBuilder, db: Database) -> None:
    """The stand stores files in object storage rather than on disk, so a
    round trip through the API proves the longer path works, and the rows
    prove the metadata followed."""
    world = scene.project().task().done()
    content = b"VKJ attachment payload"

    uploaded = world.owner.api.tasks.attach(world.task_id, "note.txt", content)
    assert uploaded.ok, uploaded.describe()

    rows = db.attachments_of(world.task_id)
    assert len(rows) == 1, f"expected one attachment row, found {rows}"

    file_row = db.file_row(int(rows[0]["file_id"]))
    assert file_row is not None, "the attachment row points at a file row that is absent"
    assert int(file_row["size"]) == len(content), (
        f"the recorded size does not match what was uploaded: {file_row}"
    )


def test_a_token_is_never_stored_in_the_clear(scene: SceneBuilder, db: Database) -> None:
    """An API token is shown once and must be unrecoverable afterwards."""
    world = scene.done()
    minted = world.owner.api.tokens.create("integrity probe", {"labels": ["read_all"]})
    assert minted.ok, minted.describe()
    secret = str(minted["token"])

    stored = db.rows(
        "select * from api_tokens where title = %(title)s", {"title": "integrity probe"}
    )
    assert stored, "the token was not recorded at all"

    for column, value in stored[0].items():
        assert secret not in str(value), (
            f"the cleartext token is recoverable from column {column!r}"
        )


def test_reading_a_token_back_never_returns_the_secret(scene: SceneBuilder) -> None:
    """The API side of the same rule."""
    world = scene.done()
    minted = world.owner.api.tokens.create("read back probe", {"labels": ["read_all"]})
    assert minted.ok, minted.describe()
    secret = str(minted["token"])

    listed = world.owner.api.tokens.all()
    assert listed.ok, listed.describe()

    assert secret not in listed.text, (
        "listing tokens hands back the secret, which is meant to be shown once"
    )
