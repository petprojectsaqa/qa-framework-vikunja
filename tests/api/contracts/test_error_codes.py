"""Domain error codes, which clients translate error messages by.

The product attaches a numeric code to its errors so a client can show the
message in the user's language. The checks here are about whether that
code survives: across both API versions, and on the errors users actually
meet.
"""

from __future__ import annotations

import pytest

from vikunja_qa.scenes import Scene, SceneBuilder

pytestmark = pytest.mark.covers("ERR")

ABSENT = 99_999_999


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

    assert not refused_v1.error_code, (
        f"v1 now sends a code on a refusal, so VKJ-005 may be fixed\n{refused_v1.describe()}"
    )
    assert not refused_v2.error_code, (
        f"v2 now sends a code on a refusal, so VKJ-005 may be fixed\n{refused_v2.describe()}"
    )
