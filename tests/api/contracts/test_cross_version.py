"""Two doors onto the same data.

Vikunja runs v1 and v2 side by side. v1 uses non-standard verbs, creating
with PUT and updating with POST; v2 moved onto the usual ones. That kind of
migration is where data written through one door and read through the
other quietly stops agreeing, and almost nothing tests it.

Only what both versions claim to return is compared. Differences the
product chose, such as the validation status, are asserted as differences
rather than smoothed over: pinning an intended difference is as useful as
pinning an intended equality, because a change to either should be noticed.
"""

from __future__ import annotations

import pytest

from vikunja_qa.actors.actor import Actor
from vikunja_qa.domain.permissions import Permission
from vikunja_qa.scenes import Scene, SceneBuilder

pytestmark = pytest.mark.covers("XVR")

#: Present in v2 only, and legitimately: a schema pointer, and a field v1
#: never carried on this resource.
V2_ONLY_FIELDS = frozenset({"$schema", "max_permission"})

#: What each version answers to the same invalid body. A deliberate change,
#: documented in the product's own source.
VALIDATION_V1 = 412
VALIDATION_V2 = 422


def _create_project(actor: Actor, version: str, title: str) -> int:
    response = (
        actor.v1.put("/projects", json={"title": title})
        if version == "v1"
        else actor.v2.post("/projects", json={"title": title})
    )
    assert response.status in (200, 201), response.describe()
    return int(response["id"])


def _create_task(actor: Actor, version: str, project_id: int, title: str) -> int:
    response = (
        actor.v1.put(f"/projects/{project_id}/tasks", json={"title": title})
        if version == "v1"
        else actor.v2.post(f"/projects/{project_id}/tasks", json={"title": title})
    )
    assert response.status in (200, 201), response.describe()
    return int(response["id"])


@pytest.fixture(scope="module")
def world(module_scene: SceneBuilder) -> Scene:
    return module_scene.project().member("reader", Permission.READ).outsider().task().done()


class TestWrittenHereReadThere:
    @pytest.mark.parametrize(("wrote", "read"), [("v1", "v2"), ("v2", "v1")])
    def test_a_task_reads_back_identically(
        self, scene: SceneBuilder, wrote: str, read: str
    ) -> None:
        owner = scene.done().owner
        project_id = _create_project(owner, wrote, f"written by {wrote}")
        task_id = _create_task(owner, wrote, project_id, f"task by {wrote}")

        from_writer = owner.raw(wrote).get(f"/tasks/{task_id}")
        from_reader = owner.raw(read).get(f"/tasks/{task_id}")
        assert from_writer.ok, from_writer.describe()
        assert from_reader.ok, from_reader.describe()

        shared = (set(from_writer.json) & set(from_reader.json)) - V2_ONLY_FIELDS
        assert len(shared) > 20, f"the two versions barely overlap: {sorted(shared)}"
        differing = {
            field: (from_writer.json[field], from_reader.json[field])
            for field in sorted(shared)
            if from_writer.json[field] != from_reader.json[field]
        }
        assert not differing, (
            f"the same task reads differently through {wrote} and {read}: {differing}"
        )

    def test_a_task_created_on_one_version_is_listed_by_the_other(
        self, scene: SceneBuilder
    ) -> None:
        owner = scene.done().owner
        project_id = _create_project(owner, "v1", "listed across versions")
        task_id = _create_task(owner, "v2", project_id, "created on v2")

        listed = owner.v1.get("/tasks")

        assert listed.ok, listed.describe()
        assert any(int(task["id"]) == task_id for task in listed.json), (
            "a task created through v2 is missing from the v1 listing"
        )


class TestTheSameDecision:
    """One caller, one object, two doors: the answer must not depend on
    which door was used."""

    @pytest.mark.parametrize("role", ["owner", "reader", "outsider"])
    def test_reading_a_task_is_decided_the_same_way(self, world: Scene, role: str) -> None:
        actor = world.owner if role == "owner" else world.actor(role)

        v1 = actor.v1.get(f"/tasks/{world.task_id}")
        v2 = actor.v2.get(f"/tasks/{world.task_id}")

        assert v1.status == v2.status, (
            f"{role} is let through one door and not the other: v1 {v1.status}, v2 {v2.status}"
        )


class TestDeliberateDifferences:
    """Differences the product chose, pinned so a change is noticed."""

    @pytest.mark.covers("NEG")
    def test_validation_answers_with_different_statuses(self, scene: SceneBuilder) -> None:
        owner = scene.done().owner

        v1 = owner.v1.put("/projects", json={"title": ""})
        v2 = owner.v2.post("/projects", json={"title": ""})

        assert v1.status == VALIDATION_V1, v1.describe()
        assert v2.status == VALIDATION_V2, v2.describe()

    @pytest.mark.usefixtures("contracts_suspended")
    def test_creation_uses_different_verbs(self, scene: SceneBuilder) -> None:
        """v1 creates with PUT and v2 with POST, and each rejects the other's
        verb: the likeliest thing to trip a client moving between versions.

        Contract checking is off for this test because it calls a verb no
        description declares, on purpose; being told so is the expected
        result, not a finding.
        """
        owner = scene.done().owner

        assert owner.v2.put("/projects", json={"title": "x"}).status == 405
        assert owner.v1.post("/projects", json={"title": "x"}).status in (404, 405)

    def test_handler_errors_use_different_media_types(self, world: Scene) -> None:
        """v2 answers handler errors as problem+json and v1 as plain JSON.
        VKJ-008 covers where v2 fails to keep that promise."""
        absent = 99_999_999

        v1 = world.owner.v1.get(f"/tasks/{absent}")
        v2 = world.owner.v2.get(f"/tasks/{absent}")

        assert "problem+json" not in v1.headers.get("Content-Type", "")
        assert "problem+json" in v2.headers.get("Content-Type", ""), (
            f"v2 answered a handler error as {v2.headers.get('Content-Type')!r}"
        )
