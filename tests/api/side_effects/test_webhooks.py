"""Outgoing webhooks, recorded by the stand's own sink.

The product cannot report on this itself: asking the API whether a webhook
fired only tells you what it meant to do. The sink records what arrived.
Each test points its webhook at a path of its own, so deliveries from tests
running in parallel never mix.
"""

from __future__ import annotations

import json

import pytest

from vikunja_qa.scenes import SceneBuilder
from vikunja_qa.transport.webhooks import WebhookSink

pytestmark = pytest.mark.covers("ASY")


def test_creating_a_task_delivers_a_webhook(
    scene: SceneBuilder, webhooks: WebhookSink, hook_name: str
) -> None:
    world = scene.project().done()
    webhooks.clear(hook_name)
    registered = world.owner.api.projects.create_webhook(
        world.project_id, webhooks.target_for(hook_name), ["task.created"]
    )
    assert registered.ok, registered.describe()

    created = world.owner.api.tasks.create(world.project_id, "a task that rings a bell")
    assert created.ok, created.describe()

    delivered = webhooks.wait_for(hook_name, timeout=20)
    payload = delivered[0]["json"]
    assert payload is not None, f"the delivery carried no JSON body: {delivered[0]}"
    assert payload.get("event_name") == "task.created", (
        f"the delivery names the wrong event: {json.dumps(payload)[:200]}"
    )


def test_a_webhook_ignores_events_it_did_not_subscribe_to(
    scene: SceneBuilder, webhooks: WebhookSink, hook_name: str
) -> None:
    """Subscribing to one event must not sign the endpoint up for the rest.

    Relies on one stated assumption. The creation is dispatched before the
    deletion, so a wrongly delivered creation is expected to reach the sink
    first and be present when the wait returns. A delivery pipeline that
    reordered events could let one slip past; proving absence outright
    would take a fixed wait, which this suite does not use.
    """
    world = scene.project().done()
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
    events = [entry["json"].get("event_name") for entry in delivered if entry.get("json")]
    assert set(events) == {"task.deleted"}, (
        f"an endpoint subscribed to task.deleted received {events}"
    )
