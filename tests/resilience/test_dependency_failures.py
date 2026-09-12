"""What the product does when something it depends on stops answering.

Kept out of the main run deliberately. These are slow, they are unstable
by nature because they pull infrastructure out from under themselves, and
a suite that is sometimes red for that reason is worth less than one that
is smaller and always honest. They run as their own job, on a schedule
and on demand.

That trade is the point, and it is stated here rather than hidden: the
checks are valuable, and admitting where they belong is part of knowing
what they are worth.

Each test restores what it stopped, pass or fail.

Run them with:

    pytest tests/resilience -m resilience -p no:randomly
"""

from __future__ import annotations

import time

import pytest
import requests

from vikunja_qa import stand
from vikunja_qa.config import Settings
from vikunja_qa.scenes import SceneBuilder
from vikunja_qa.waiting import wait_until

pytestmark = [pytest.mark.resilience, pytest.mark.serial]


def _wait_until_healthy(settings: Settings, timeout: float = 120) -> None:
    """Give the product time to notice its dependency is back."""

    def healthy() -> bool | None:
        try:
            return requests.get(f"{settings.base_url}/health", timeout=5).status_code == 200
        except requests.RequestException:
            return None

    wait_until(healthy, timeout=timeout, because="the product reports itself healthy again")


@pytest.fixture(autouse=True)
def _restore_the_stand(settings: Settings):  # noqa: ANN202
    """Wait for the product to recover after every test in this group.

    In the teardown rather than at the end of each test, because a test
    that fails mid-outage would otherwise skip its own recovery and hand
    a broken stand to whatever runs next. One failure would become a
    cascade, and the cascade would hide the original cause.
    """
    if not stand.is_available():
        pytest.skip("the compose stand is not reachable from here")
    yield
    _wait_until_healthy(settings)


class TestObjectStorage:
    @pytest.mark.xfail(
        reason=(
            "VKJ-010: a failed upload answers 200 and hides the failure in an "
            "errors array, so a caller reading the status code concludes the "
            "file was saved."
        ),
        strict=False,
    )
    def test_an_upload_fails_clearly_when_storage_is_gone(self, scene: SceneBuilder) -> None:
        """A failed upload must say so in its status code.

        Written as an expected failure rather than asserting what the
        product currently does: pinning the 200 would freeze a defect into
        the suite as though it were intended.
        """
        world = scene.project().task().done()

        with stand.stopped("minio"):
            attempted = world.owner.api.tasks.attach(world.task_id, "during-outage.txt", b"payload")

        assert not attempted.ok, (
            "the upload answered a success code although no storage was running; "
            f"the failure is visible only in the body\n{attempted.describe()}"
        )

    def test_the_rest_of_the_product_keeps_working_without_storage(
        self, scene: SceneBuilder
    ) -> None:
        """One dependency failing should not take unrelated features with
        it."""
        world = scene.project().done()

        with stand.stopped("minio"):
            created = world.owner.api.tasks.create(world.project_id, "made during an outage")
            assert created.ok, (
                f"creating a task, which needs no file storage, broke when storage "
                f"went away\n{created.describe()}"
            )


class TestMail:
    def test_registration_is_not_lost_when_the_mail_server_is_gone(
        self, scene: SceneBuilder
    ) -> None:
        """Mail is queued, so an outage should delay a message rather than
        fail the request that triggered it."""
        world = scene.done()

        with stand.stopped("mailpit"):
            requested = world.owner.v1.post(
                "/user/password/token", json={"email": world.owner.email}
            )
            assert requested.ok, (
                f"a request that only sends mail failed outright when the mail "
                f"server was down\n{requested.describe()}"
            )


class TestKeyValueStore:
    @pytest.mark.xfail(
        reason=(
            "VKJ-011: with Redis as the key-value store, an outage makes "
            "authenticated requests hang rather than fail, so the connection "
            "pool drains and one dependency's outage becomes the product's."
        ),
        strict=False,
    )
    def test_the_product_survives_losing_redis(
        self, scene: SceneBuilder, settings: Settings
    ) -> None:
        """Losing a cache should degrade the product, not stop it.

        The budget is deliberately generous. The point is not that the
        request is slow but that it never answers at all.
        """
        world = scene.project().done()
        token = world.owner.auth.token  # type: ignore[attr-defined]
        budget = 25

        with stand.stopped("redis"):
            started = time.monotonic()
            try:
                response = requests.get(
                    f"{settings.api_v1}/user",
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=budget,
                )
            except requests.RequestException as exc:
                waited = time.monotonic() - started
                pytest.fail(
                    f"no answer in {waited:.0f}s without the key-value store "
                    f"({type(exc).__name__}); a cache outage should not block a "
                    "request that does not depend on the cache"
                )

        assert response.status_code < 500, (
            f"the product answered {response.status_code} without its cache"
        )


class TestDatabase:
    def test_health_turns_unhealthy_and_no_stack_trace_escapes(self, settings: Settings) -> None:
        """The check that orchestrators act on. It has to tell the truth,
        and the failure it reports must not describe the internals.
        """
        with stand.stopped("db"):

            def unhealthy() -> bool | None:
                try:
                    response = requests.get(f"{settings.base_url}/health", timeout=5)
                except requests.RequestException:
                    return True
                if response.status_code == 200:
                    return None
                assert "goroutine" not in response.text, (
                    "the health check handed an internal stack trace to whoever asked"
                )
                return True

            wait_until(
                unhealthy,
                timeout=60,
                because="the health check stops claiming the product is well",
            )
