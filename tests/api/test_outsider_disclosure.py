"""What a stranger can learn from a refusal.

The access matrix records that an outsider gets 403. These tests ask the
separate question of whether that 403 tells them something they should
not know.

They are marked as expected failures rather than asserted as current
behaviour, deliberately. Asserting 403 would freeze the discrepancy into
the suite as if it were intended. Expecting 404 and failing states the
position without breaking the build, and if the product ever changes its
mind the result turns into an unexpected pass, which is exactly the
signal wanted.
"""

from __future__ import annotations

import pytest

from vikunja_qa.scenes import Scene, SceneBuilder

ABSENT = 99_999_999

REASON = (
    "The product answers 403 for an object that exists and 404 for one "
    "that does not, so the pair of responses reveals which identifiers "
    "are real. Reported as an observation; see docs/findings."
)


@pytest.fixture(scope="module")
def world(module_scene: SceneBuilder) -> Scene:
    return module_scene.project().outsider().task().done()


@pytest.mark.xfail(reason=REASON, strict=False)
def test_a_task_that_exists_is_indistinguishable_from_one_that_does_not(
    world: Scene,
) -> None:
    outsider = world.actor("outsider")

    existing = outsider.api.tasks.get(world.task_id)
    absent = outsider.api.tasks.get(ABSENT)

    assert existing.status == absent.status, (
        "the two answers differ, so identifiers can be enumerated\n"
        f"exists  -> {existing.status} {existing.error_message}\n"
        f"absent  -> {absent.status} {absent.error_message}"
    )


@pytest.mark.xfail(reason=REASON, strict=False)
def test_a_project_that_exists_is_indistinguishable_from_one_that_does_not(
    world: Scene,
) -> None:
    outsider = world.actor("outsider")

    existing = outsider.api.projects.get(world.project_id)
    absent = outsider.api.projects.get(ABSENT)

    assert existing.status == absent.status, (
        "the two answers differ, so identifiers can be enumerated\n"
        f"exists  -> {existing.status} {existing.error_message}\n"
        f"absent  -> {absent.status} {absent.error_message}"
    )


def test_a_refusal_carries_no_domain_error_code(world: Scene) -> None:
    """VKJ-005, asserted as current behaviour so a fix is noticed.

    Clients localise errors by the numeric domain code. Absent objects
    come back with a real one; refusals come back with zero on v1 and
    with none at all on v2. That leaves the errors users meet most often
    as the ones a client cannot translate.
    """
    outsider = world.actor("outsider")

    refused_v1 = outsider.v1.get(f"/tasks/{world.task_id}")
    absent_v1 = outsider.v1.get(f"/tasks/{ABSENT}")
    refused_v2 = outsider.v2.get(f"/tasks/{world.task_id}")

    assert absent_v1.error_code, (
        "a missing object should carry a domain code; if this fails the "
        f"product has changed\n{absent_v1.describe()}"
    )
    assert not refused_v1.error_code, (
        "refusals used to carry no usable code on v1; this now passes one, "
        f"so VKJ-005 may be fixed\n{refused_v1.describe()}"
    )
    assert not refused_v2.error_code, (
        "refusals used to carry no code on v2; this now passes one, so "
        f"VKJ-005 may be fixed\n{refused_v2.describe()}"
    )
