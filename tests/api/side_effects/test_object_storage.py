"""Files, which this stand keeps in S3-compatible object storage.

Storing attachments outside the application's own disk is the longer code
path and the one a real deployment is likelier to run, so it is the one the
stand is configured to use. Getting the same bytes back proves it end to end.
"""

from __future__ import annotations

import pytest

from vikunja_qa.scenes import SceneBuilder

pytestmark = pytest.mark.covers("ASY")


@pytest.mark.smoke
def test_an_attachment_survives_a_round_trip(scene: SceneBuilder) -> None:
    """Compared byte for byte, including bytes that are not text, since a
    payload that only survives as text has not really survived."""
    world = scene.project().task().done()
    content = b"bytes that must come back unchanged \x00\x01\x02\xff"

    uploaded = world.owner.api.tasks.attach(world.task_id, "payload.bin", content)
    assert uploaded.ok, uploaded.describe()
    listed = world.owner.api.tasks.attachments(world.task_id)
    assert listed.ok, listed.describe()

    fetched = world.owner.api.tasks.attachment(world.task_id, int(listed.json[0]["id"]))

    assert fetched.status == 200, fetched.describe()
    assert fetched.content == content, (
        f"{len(content)} bytes went in and {len(fetched.content)} different bytes came back"
    )
