"""Domain error codes, which clients translate error messages by.

The product attaches a numeric code to its errors so a client can show the
message in the user's language. The checks here are about whether that code
survives: across both API versions, and on the errors users actually meet.

The sweep at the bottom is generated. It pairs every operation both
versions describe, asks each about an identifier that cannot exist, and
holds them to the same answer. Nothing in it is written by hand, so an
operation added to both versions tomorrow is compared on the next run.
"""

from __future__ import annotations

import pytest

from vikunja_qa.actors.actor import Actor
from vikunja_qa.actors.factory import ActorFactory
from vikunja_qa.contracts.errors import ErrorCase
from vikunja_qa.scenes import Scene, SceneBuilder
from vikunja_qa.testing import discovery

pytestmark = pytest.mark.covers("ERR")

ABSENT = 99_999_999

#: Computed while pytest is still collecting, because parametrisation is
#: decided then. Skips the module with the reason when the stand cannot be
#: read, rather than failing hundreds of tests one by one.
CASES = discovery.error_cases()

#: Operations where the two versions knowingly answer an absent object with
#: different statuses, and why. Everything else has to agree.
#:
#: The list may only shrink, and it enforces that itself: an entry whose
#: operation starts answering alike fails and says so, so a divergence that
#: gets fixed cannot leave a stale note behind.
KNOWN_DIVERGENCES: dict[str, str] = {
    "DELETE /user/settings/token/caldav/{}": (
        "VKJ-016. Both versions report success for a token that does not exist; "
        "they differ only in how they spell it, v1 with 200 and v2 with 204. "
        "The defect is the false success, not the disagreement."
    ),
    "DELETE /user/settings/webhooks/{}": (
        "v1 answers 404 for a webhook that does not exist and v2 answers 403. "
        "v2 has the better of it: settling permission before existence tells "
        "the caller nothing about which identifiers are real. This is the one "
        "operation where the two versions take opposite sides on that, and it "
        "is the held finding VKJ-006 seen from the other end, so it is recorded "
        "here rather than written up twice."
    ),
}


@pytest.fixture(scope="module")
def world(module_scene: SceneBuilder) -> Scene:
    return module_scene.project().outsider().task().done()


def test_an_absent_object_carries_the_same_code_on_both_versions(world: Scene) -> None:
    """The one error path where both versions do carry a code, so the
    migration from the flat v1 error to v2's problem document is checked
    to have kept it."""
    v1 = world.owner.v1.get(f"/tasks/{ABSENT}")
    v2 = world.owner.v2.get(f"/tasks/{ABSENT}")

    assert v1.status == v2.status == 404, f"{v1.describe()}\n{v2.describe()}"
    assert v1.error_code, f"v1 carried no code at all\n{v1.describe()}"
    assert v1.error_code == v2.error_code, (
        f"the same condition reports {v1.error_code} on v1 and {v2.error_code} on v2"
    )


@pytest.mark.finding("VKJ-005")
def test_a_refusal_carries_no_usable_code(world: Scene) -> None:
    """Asserted as current behaviour, on purpose, so a fix is noticed.

    Refusals come back with code 0 on v1 and with no code at all on v2,
    while absent objects carry real ones. That leaves the errors users meet
    most often as the ones a client cannot translate. When the product
    starts sending a code, this fails and says the finding may be closed.
    """
    outsider = world.actor("outsider")

    refused_v1 = outsider.v1.get(f"/tasks/{world.task_id}")
    refused_v2 = outsider.v2.get(f"/tasks/{world.task_id}")

    # Pinned first, because the finding is about a refusal. Were the product
    # to start answering 404 here instead, a real code would appear and the
    # assertions below would announce that VKJ-005 may be fixed, which would
    # be the wrong diagnosis of a different change entirely.
    assert refused_v1.status == refused_v2.status == 403, (
        f"this is no longer a refusal, so it is not the case VKJ-005 is about\n"
        f"{refused_v1.describe()}\n{refused_v2.describe()}"
    )
    assert not refused_v1.error_code, (
        f"v1 now sends a code on a refusal, so VKJ-005 may be fixed\n{refused_v1.describe()}"
    )
    assert not refused_v2.error_code, (
        f"v2 now sends a code on a refusal, so VKJ-005 may be fixed\n{refused_v2.describe()}"
    )


@pytest.mark.generated
@pytest.mark.usefixtures("contracts_collect_only")
@pytest.mark.parametrize("case", CASES, ids=[case.id for case in CASES])
def test_both_versions_name_the_same_failure(case: ErrorCase, owner: Actor) -> None:
    """One operation, asked of both versions about something absent.

    Contract deviations are recorded rather than raised here: this walks
    error paths it did not choose, and a deviation reported from the
    transport hook would fail the test before it compared anything. The
    deviations still reach the end-of-run report.
    """
    first = owner.raw("v1").request(case.method, case.v1_path)
    second = owner.raw("v2").request(case.method, case.v2_path)
    operation = f"{case.method} {case.operation}"
    divergence = KNOWN_DIVERGENCES.get(operation)

    # The status, compared whatever it is. Comparing only whether each call
    # failed said almost nothing: every case in this family asks about an
    # identifier that cannot exist, so both sides fail, and one version
    # answering 403 where the other answers 404 read as agreement.
    if divergence is None:
        assert first.status == second.status, (
            f"the versions answer the same absent object differently: v1 with {first.status} "
            f"and v2 with {second.status}. A client cannot branch on status across the two.\n"
            f"{first.describe()}\n{second.describe()}"
        )
    else:
        assert first.status != second.status, (
            f"{operation} now answers alike on both versions, so this entry in "
            f"KNOWN_DIVERGENCES is stale and should go: {divergence}"
        )

    # The code, where there is one to compare. v1 sends 0 on a refusal
    # (VKJ-005), and 0 is not a code a client can translate, so those cases
    # have nothing to hold the versions to. Seven of the current forty-six
    # are like that; the status above is what covers them.
    if first.error_code:
        assert first.error_code == second.error_code, (
            f"the same failure is code {first.error_code} on v1 and "
            f"{second.error_code} on v2, so a client translating by code cannot "
            f"follow the product across versions\n{first.describe()}\n{second.describe()}"
        )


def test_the_paired_operations_yield_cases() -> None:
    """Guards against the pairing quietly producing nothing.

    An empty parameter set is one silent skip, and the three hand-written
    tests above keep the ERR row of the matrix non-zero, so `--fail-uncovered`
    would not notice either. The two sibling generated families carry the same
    guard; this one did not, and was the only family that could vanish without
    turning anything red.
    """
    assert len(CASES) >= 30, f"only {len(CASES)} operations paired across the two versions"


@pytest.mark.finding("VKJ-016")
@pytest.mark.xfail(
    reason=(
        "VKJ-016: revoking a CalDAV token answers 'deleted successfully' for a token that "
        "does not exist and for one belonging to another account, which goes on working"
    ),
)
def test_revoking_a_token_that_was_not_revoked_says_so(actors: ActorFactory) -> None:
    """Revoking a credential is a security action, so the answer has to
    describe what happened. Someone else's token is the half that matters:
    the product refuses to revoke it, correctly, and then reports success.
    """
    alice, bob = actors.users("alice", "bob")
    minted = alice.api.user.create_caldav_token()
    assert minted.ok, minted.describe()
    token_id = int(minted["id"])

    refused = bob.api.user.delete_caldav_token(token_id)

    surviving = alice.api.user.caldav_tokens()
    assert surviving.ok, surviving.describe()
    assert [int(token["id"]) for token in surviving.json] == [token_id], (
        "the token is gone, so this test is asking the wrong question now"
    )
    assert not refused.ok, (
        f"the token survived, and the caller was told it was deleted\n{refused.describe()}"
    )
