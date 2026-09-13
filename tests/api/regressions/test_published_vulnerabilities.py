"""Regressions for vulnerabilities this product has already had.

A fixed vulnerability is the best possible test case: someone has already
proved the code can get this wrong, and the shape of the mistake is on
record. These pin each one shut.

Every test names its advisory, so a failure here is not a puzzle. It says
which published weakness has come back.

These are regressions, not attacks. Each builds the situation the
advisory describes on a stand of our own and checks the product now
refuses it.
"""

from __future__ import annotations

import pytest

from vikunja_qa.actors.factory import ActorFactory
from vikunja_qa.domain import icalendar
from vikunja_qa.domain.permissions import Permission
from vikunja_qa.scenes import SceneBuilder, build
from vikunja_qa.testing.fixtures import CalendarOpener

pytestmark = pytest.mark.covers("CVE")


@pytest.mark.advisory("CVE-2026-33678")
def test_an_attachment_cannot_be_read_through_someone_elses_task(
    scene: SceneBuilder, actors: ActorFactory
) -> None:
    """CVE-2026-33678.

    The read used to resolve an attachment by its own identifier alone,
    without checking it belonged to the task in the path. So naming your
    own task and someone else's attachment handed you their file.
    """
    victim = scene.project().task().done()
    uploaded = victim.owner.api.tasks.attach(victim.task_id, "secret.txt", b"the victim's data")
    assert uploaded.ok, uploaded.describe()

    listed = victim.owner.api.tasks.attachments(victim.task_id)
    assert listed.ok, listed.describe()
    victim_attachment = int(listed.json[0]["id"])

    attacker = build(actors).project().task().done()

    through_own_task = attacker.owner.api.tasks.attachment(attacker.task_id, victim_attachment)

    assert through_own_task.status in (403, 404), (
        "an attachment was reachable by naming your own task and a stranger's "
        f"attachment id; CVE-2026-33678 has returned\n{through_own_task.describe()}"
    )
    assert b"the victim's data" not in through_own_task.content, (
        "the victim's file contents came back"
    )


@pytest.mark.advisory("GHSA-2pv8-4c52-mf8j")
def test_a_link_share_token_reaches_only_its_own_project(
    scene: SceneBuilder, actors: ActorFactory
) -> None:
    """GHSA-2pv8-4c52-mf8j.

    A share hash was disclosable, and the token it yielded then reached
    attachments belonging to other projects. The hash half is not the
    part to pin; the scope of the token is.
    """
    shared = scene.project().share("guest", Permission.READ).task().done()
    guest = shared.actor("guest")

    other = build(actors).project().task().done()
    uploaded = other.owner.api.tasks.attach(other.task_id, "private.txt", b"not for the guest")
    assert uploaded.ok, uploaded.describe()
    other_attachment = int(other.owner.api.tasks.attachments(other.task_id).json[0]["id"])

    assert guest.api.tasks.get(shared.task_id).ok, "the share should reach its own project"

    for probe in (
        guest.api.projects.get(other.project_id),
        guest.api.tasks.get(other.task_id),
        guest.api.tasks.attachment(other.task_id, other_attachment),
    ):
        assert probe.status in (401, 403, 404), (
            "a link share token reached outside the project it was made for; "
            f"GHSA-2pv8-4c52-mf8j has returned\n{probe.describe()}"
        )


@pytest.mark.advisory("CVE-2026-68581")
def test_an_api_token_cannot_be_read_or_revoked_by_anyone_else(
    scene: SceneBuilder, actors: ActorFactory
) -> None:
    """CVE-2026-68581.

    A low-privileged account could take control of another account's API
    tokens, which is a full account takeover by another name.
    """
    victim = scene.done()
    minted = victim.owner.api.tokens.create("victim token", {"labels": ["read_all"]})
    assert minted.ok, minted.describe()
    token_id = int(minted["id"])
    secret = str(minted["token"])

    attacker = build(actors).done()

    listed = attacker.owner.api.tokens.all()
    assert listed.ok, listed.describe()
    assert secret not in listed.text, "another account's token was listed to a stranger"
    assert all(int(row["id"]) != token_id for row in listed.json), (
        f"another account's token appears in the attacker's list; "
        f"CVE-2026-68581 has returned\n{listed.describe()}"
    )

    revoked = attacker.owner.api.tokens.delete(token_id)
    assert revoked.status in (403, 404), (
        f"a stranger revoked someone else's token\n{revoked.describe()}"
    )

    still_works = victim.owner.api.tokens.all()
    assert still_works.ok, "the victim's own token list broke"
    assert any(int(row["id"]) == token_id for row in still_works.json), (
        "the token was destroyed by someone with no rights to it"
    )


@pytest.mark.advisory("CVE-2026-55065")
def test_a_kanban_bucket_cannot_be_destroyed_without_rights_on_its_project(
    scene: SceneBuilder, actors: ActorFactory
) -> None:
    """CVE-2026-55065.

    Operations on kanban buckets did not consult the owning project, so a
    stranger could delete the columns out of someone's board.
    """
    victim = scene.project().done()
    views = victim.owner.api.projects.views(victim.project_id)
    assert views.ok, views.describe()

    # Asserted, not fallen back from, and not skipped over. Both of those
    # were here, and together they let this check quietly stop running: with
    # no board among the views it took whichever view came first, that view
    # has no columns, and the test then skipped itself. A regression test for
    # a published vulnerability is the last thing that should be able to opt
    # out of running, so every step that could go missing now says so.
    kanban = next((view for view in views.json if view.get("view_kind") == "kanban"), None)
    assert kanban is not None, (
        f"the project has no board to aim at: {[view.get('view_kind') for view in views.json]}"
    )
    view_id = int(kanban["id"])

    buckets = victim.owner.api.projects.buckets(victim.project_id, view_id)
    assert buckets.ok, buckets.describe()
    assert buckets.json, "the board has no columns to aim at, and a new project is given four"
    bucket_id = int(buckets.json[0]["id"])

    attacker = build(actors).done()

    destroyed = attacker.owner.api.projects.delete_bucket(victim.project_id, view_id, bucket_id)

    assert destroyed.status in (401, 403, 404), (
        "a stranger deleted a bucket from someone else's board; "
        f"CVE-2026-55065 has returned\n{destroyed.describe()}"
    )

    survivors = victim.owner.api.projects.buckets(victim.project_id, view_id)
    assert any(int(b["id"]) == bucket_id for b in survivors.json), (
        "the bucket is gone even though the call was refused"
    )


@pytest.mark.covers("DAV")
@pytest.mark.advisory("CVE-2026-35601")
def test_a_line_break_in_a_title_cannot_forge_calendar_properties(
    scene: SceneBuilder, calendar_for: CalendarOpener
) -> None:
    """CVE-2026-35601.

    A line break in a task title used to end its SUMMARY line in the
    calendar the product generates, so whatever followed became properties
    of their own.

    Read by the rules of RFC 5545 rather than by searching the text. A fixed
    server still sends the characters `X-INJECTED`, escaped inside the one
    SUMMARY value, and a text search would call it vulnerable. Only parsing
    the content lines tells a forged property from text that looks like one.
    """
    hostile = "innocent\r\nSUMMARY:forged\r\nX-INJECTED:yes"
    world = scene.project().task(title=hostile).done()

    answered = calendar_for(world.owner).calendar(world.project_id)
    assert answered.ok, answered.describe()

    (todo,) = icalendar.parse(answered.content).children("VTODO")
    assert not todo.all("X-INJECTED"), (
        f"a task title forged a calendar property; CVE-2026-35601 has returned\n{answered.text}"
    )
    summaries = todo.all("SUMMARY")
    assert len(summaries) == 1, f"the title produced {len(summaries)} SUMMARY properties"
    assert summaries[0].text == hostile.replace("\r\n", "\n"), (
        "the title did not survive as one value with its line breaks kept as text"
    )
