"""What a stranger learns from a refusal.

The access matrix records that an outsider gets 403. These ask the
separate question of whether that 403 tells them something they should not
know: answering 403 for an object that exists and 404 for one that does not
lets a caller separate real identifiers from unused ones.

Written as expected failures rather than as assertions of current
behaviour. Asserting 403 would freeze the discrepancy into the suite as if
it were intended. Expecting indistinguishable answers states the position
without breaking the build, and turns into an unexpected pass the moment
the product changes, which is exactly the signal wanted.
"""

from __future__ import annotations

import pytest

from vikunja_qa.scenes import Scene, SceneBuilder

pytestmark = [pytest.mark.covers("ACL"), pytest.mark.finding("VKJ-006")]

ABSENT = 99_999_999

REASON = (
    "VKJ-006: an object that exists answers 403 and one that does not answers 404, "
    "so the pair of responses reveals which identifiers are real"
)


@pytest.fixture(scope="module")
def world(module_scene: SceneBuilder) -> Scene:
    return module_scene.project().outsider().task().done()


@pytest.mark.xfail(reason=REASON)
def test_a_task_that_exists_is_indistinguishable_from_one_that_does_not(world: Scene) -> None:
    outsider = world.actor("outsider")

    existing = outsider.api.tasks.get(world.task_id)
    absent = outsider.api.tasks.get(ABSENT)

    assert existing.status == absent.status, (
        "the two answers differ, so identifiers can be enumerated\n"
        f"exists -> {existing.status} {existing.error_message}\n"
        f"absent -> {absent.status} {absent.error_message}"
    )


@pytest.mark.xfail(reason=REASON)
def test_a_project_that_exists_is_indistinguishable_from_one_that_does_not(
    world: Scene,
) -> None:
    outsider = world.actor("outsider")

    existing = outsider.api.projects.get(world.project_id)
    absent = outsider.api.projects.get(ABSENT)

    assert existing.status == absent.status, (
        "the two answers differ, so identifiers can be enumerated\n"
        f"exists -> {existing.status} {existing.error_message}\n"
        f"absent -> {absent.status} {absent.error_message}"
    )
