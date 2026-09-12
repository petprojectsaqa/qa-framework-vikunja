"""Attachments with the object store gone."""

from __future__ import annotations

import pytest

from vikunja_qa import stand
from vikunja_qa.scenes import SceneBuilder

pytestmark = pytest.mark.covers("RES")


@pytest.mark.finding("VKJ-010")
@pytest.mark.xfail(
    reason=(
        "VKJ-010: a failed upload answers 200 and hides the failure in an errors array, "
        "so a caller reading the status code concludes the file was saved"
    ),
    strict=False,
)
def test_a_failed_upload_says_so_in_its_status_code(scene: SceneBuilder) -> None:
    """Written as an expected failure rather than asserting what the product
    does now: pinning the 200 would freeze a defect into the suite as though
    it were intended."""
    world = scene.project().task().done()

    with stand.stopped("minio"):
        attempted = world.owner.api.tasks.attach(world.task_id, "during-outage.txt", b"payload")

    assert not attempted.ok, (
        "the upload answered a success code although no storage was running; "
        f"the failure is visible only in the body\n{attempted.describe()}"
    )


def test_features_that_need_no_storage_keep_working_without_it(scene: SceneBuilder) -> None:
    """One dependency failing must not take unrelated features with it."""
    world = scene.project().done()

    with stand.stopped("minio"):
        created = world.owner.api.tasks.create(world.project_id, "made during an outage")

    assert created.ok, (
        "creating a task, which needs no file storage, broke when storage went away\n"
        f"{created.describe()}"
    )
