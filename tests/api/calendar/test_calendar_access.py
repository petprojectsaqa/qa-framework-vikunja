"""Who may open the calendar door, and with what.

CalDAV has its own way in, HTTP Basic, and it accepts three secrets: the
account password, a CalDAV token, and an API token carrying the `caldav`
permission. Each is a separate check in the product, which makes each a
separate place for a permission to go missing.
"""

from __future__ import annotations

import pytest

from vikunja_qa.clients.calendar import CalendarClient
from vikunja_qa.scenes import SceneBuilder
from vikunja_qa.testing.fixtures import CalendarOpener

pytestmark = pytest.mark.covers("DAV")


@pytest.mark.covers("AUT")
def test_the_calendar_refuses_a_caller_without_credentials(
    scene: SceneBuilder, calendar_anonymous: CalendarClient
) -> None:
    world = scene.project().task().done()

    answered = calendar_anonymous.calendar(world.project_id)

    assert answered.status == 401, answered.describe()
    challenge = answered.headers.get("WWW-Authenticate", "")
    assert challenge.lower().startswith("basic"), (
        f"a 401 without a Basic challenge leaves a calendar client nothing to answer: {challenge!r}"
    )


@pytest.mark.covers("ACL")
def test_a_stranger_cannot_read_someone_elses_calendar(
    scene: SceneBuilder, calendar_for: CalendarOpener
) -> None:
    world = scene.project().task(title="private plans").outsider().done()
    stranger = calendar_for(world.actor("outsider"))

    read = stranger.calendar(world.project_id)
    listed = stranger.listing(world.project_id)

    assert read.status == 404, read.describe()
    assert listed.status == 404, listed.describe()
    for answered in (read, listed):
        assert b"private plans" not in answered.content, "a stranger received the task itself"


def test_a_revoked_caldav_token_no_longer_opens_the_calendar(
    scene: SceneBuilder, calendar_for: CalendarOpener
) -> None:
    world = scene.project().task().done()
    minted = world.owner.api.user.create_caldav_token()
    assert minted.ok, minted.describe()
    secret, token_id = str(minted["token"]), int(minted["id"])

    before = calendar_for(world.owner, secret).calendar(world.project_id)
    assert before.ok, f"a fresh CalDAV token did not open the calendar\n{before.describe()}"

    revoked = world.owner.api.user.delete_caldav_token(token_id)
    assert revoked.ok, revoked.describe()

    after = calendar_for(world.owner, secret).calendar(world.project_id)
    assert after.status == 401, f"a revoked CalDAV token still works\n{after.describe()}"


@pytest.mark.covers("SCP")
@pytest.mark.parametrize(
    ("permissions", "expected"),
    [
        pytest.param({"caldav": ["access"]}, 200, id="with-caldav-permission"),
        pytest.param({"projects": ["read_all"], "tasks": ["read_all"]}, 401, id="without-it"),
    ],
)
def test_an_api_token_opens_the_calendar_only_with_the_caldav_permission(
    scene: SceneBuilder,
    calendar_for: CalendarOpener,
    permissions: dict[str, list[str]],
    expected: int,
) -> None:
    """Read permissions on projects and tasks are not calendar access: the
    catalogue lists `caldav` as its own area, so the token must name it."""
    world = scene.project().task().done()
    minted = world.owner.api.tokens.create("calendar door", permissions)
    assert minted.ok, minted.describe()

    answered = calendar_for(world.owner, str(minted["token"])).calendar(world.project_id)

    assert answered.status == expected, answered.describe()


@pytest.mark.covers("SCP")
def test_an_api_token_is_refused_under_another_accounts_username(
    scene: SceneBuilder, calendar_for: CalendarOpener
) -> None:
    """The username in the Basic header must be the token owner's. Otherwise
    the header claims one account while the token acts for another."""
    world = scene.project().task().outsider().done()
    minted = world.owner.api.tokens.create("calendar door", {"caldav": ["access"]})
    assert minted.ok, minted.describe()

    answered = calendar_for(world.actor("outsider"), str(minted["token"])).calendar(
        world.project_id
    )

    assert answered.status == 401, answered.describe()


@pytest.mark.finding("VKJ-012")
@pytest.mark.xfail(
    reason=(
        "VKJ-012: GET and HEAD on the calendar home answer 500 with an empty body, "
        "while PROPFIND on the same collection works"
    ),
)
def test_the_calendar_home_answers_a_plain_get_without_a_server_error(
    scene: SceneBuilder, calendar_for: CalendarOpener
) -> None:
    world = scene.done()

    answered = calendar_for(world.owner).home()

    assert answered.status < 500, answered.describe()
