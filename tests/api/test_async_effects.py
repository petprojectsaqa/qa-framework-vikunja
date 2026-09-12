"""Effects that land somewhere other than the response.

A webhook, a message, a file in object storage, a counter in the metrics
scrape: the API says it accepted the request and nothing more. Whether
the effect actually happened is a question for the service it happened
in, which is why the stand runs eight containers rather than two.

Every wait here polls a condition with an explicit deadline. There is not
one fixed pause in this file, and a timeout says what it was waiting for
rather than just that time ran out.
"""

from __future__ import annotations

import json

import pytest
import requests

from vikunja_qa.config import Settings
from vikunja_qa.scenes import SceneBuilder
from vikunja_qa.transport.mailpit import MailpitClient
from vikunja_qa.transport.webhooks import WebhookSink
from vikunja_qa.waiting import wait_until


class TestMail:
    def test_registration_sends_a_confirmation_message(
        self, scene: SceneBuilder, mailpit: MailpitClient
    ) -> None:
        """Every account in this suite already walks this path, so a
        failure here explains a failure everywhere else."""
        world = scene.done()

        message = mailpit.wait_for_message(world.owner.email, timeout=20)

        assert world.owner.username in message.get("Subject", ""), (
            f"the welcome message does not name the account: {message.get('Subject')!r}"
        )
        assert "userEmailConfirm=" in MailpitClient.body_of(message), (
            "the welcome message carries no confirmation link"
        )

    def test_a_password_reset_sends_a_token(
        self, scene: SceneBuilder, mailpit: MailpitClient
    ) -> None:
        world = scene.done()

        # The token is requested by address, not by username: the caller
        # who has lost their password may not remember the latter.
        requested = world.owner.v1.post("/user/password/token", json={"email": world.owner.email})
        assert requested.ok, requested.describe()

        token = mailpit.password_reset_token(world.owner.email, timeout=20)
        assert len(token) > 20, f"the reset token looks too short to be one: {token!r}"


class TestWebhooks:
    def test_creating_a_task_delivers_a_webhook(
        self, scene: SceneBuilder, webhooks: WebhookSink, hook_name: str
    ) -> None:
        """The product cannot report this itself: asking the API whether a
        webhook fired only says what it meant to do."""
        world = scene.project().done()
        webhooks.clear(hook_name)

        registered = world.owner.api.projects.create_webhook(
            world.project_id, webhooks.target_for(hook_name), ["task.created"]
        )
        assert registered.ok, registered.describe()

        created = world.owner.api.tasks.create(world.project_id, "task that rings a bell")
        assert created.ok, created.describe()

        delivered = webhooks.wait_for(hook_name, timeout=20)

        payload = delivered[0]["json"]
        assert payload is not None, f"the delivery carried no JSON body: {delivered[0]}"
        assert payload.get("event_name") == "task.created", (
            f"the delivery names the wrong event: {json.dumps(payload)[:200]}"
        )

    def test_a_webhook_is_not_delivered_for_an_event_it_did_not_subscribe_to(
        self, scene: SceneBuilder, webhooks: WebhookSink, hook_name: str
    ) -> None:
        """Subscribing to one event must not sign you up for the rest."""
        world = scene.project().task().done()
        webhooks.clear(hook_name)

        registered = world.owner.api.projects.create_webhook(
            world.project_id, webhooks.target_for(hook_name), ["task.deleted"]
        )
        assert registered.ok, registered.describe()

        created = world.owner.api.tasks.create(world.project_id, "a creation, not a deletion")
        assert created.ok, created.describe()

        deleted = world.owner.api.tasks.delete(int(created["id"]))
        assert deleted.ok, deleted.describe()

        delivered = webhooks.wait_for(hook_name, timeout=20)

        events = [d["json"].get("event_name") for d in delivered if d.get("json")]
        assert set(events) == {"task.deleted"}, (
            f"a webhook subscribed to task.deleted received {events}"
        )


class TestObjectStorage:
    def test_an_attachment_survives_a_round_trip(self, scene: SceneBuilder) -> None:
        """Files on this stand live in object storage rather than on the
        application's disk, so getting the same bytes back proves the
        longer path end to end."""
        world = scene.project().task().done()
        content = b"bytes that must come back unchanged \x00\x01\x02"

        uploaded = world.owner.api.tasks.attach(world.task_id, "payload.bin", content)
        assert uploaded.ok, uploaded.describe()

        listed = world.owner.api.tasks.attachments(world.task_id)
        assert listed.ok, listed.describe()
        attachment_id = int(listed.json[0]["id"])

        fetched = world.owner.api.tasks.attachment(world.task_id, attachment_id)
        assert fetched.status == 200, fetched.describe()
        assert fetched.text.encode("utf-8", "surrogateescape")[: len(content)] == content, (
            "the bytes that came back are not the bytes that went in"
        )


class TestMetrics:
    def test_creating_a_task_moves_the_task_counter(
        self, scene: SceneBuilder, settings: Settings
    ) -> None:
        """Measured as a difference around the action, never as an
        absolute value: the counter is instance-wide and every other test
        running in parallel is moving it too.
        """
        world = scene.project().done()

        def counter() -> float | None:
            response = requests.get(
                f"{settings.prometheus_url}/api/v1/query",
                params={"query": "vikunja_task_count"},
                timeout=10,
            )
            response.raise_for_status()
            result = response.json().get("data", {}).get("result", [])
            return float(result[0]["value"][1]) if result else None

        before = wait_until(
            counter, timeout=30, because="prometheus has scraped the task counter at least once"
        )

        created = world.owner.api.tasks.create(world.project_id, "a task worth counting")
        assert created.ok, created.describe()

        after = wait_until(
            lambda: (lambda now: now if now is not None and now > before else None)(counter()),
            timeout=30,
            because="the scraped task counter rises after a task is created",
        )

        assert after > before, f"counter did not move: {before} then {after}"


@pytest.mark.serial
def test_the_stand_reports_itself_healthy(settings: Settings) -> None:
    """Marked serial because it speaks for the whole instance rather than
    for anything this test owns."""
    response = requests.get(f"{settings.base_url}/health", timeout=10)

    assert response.status_code == 200, response.text
