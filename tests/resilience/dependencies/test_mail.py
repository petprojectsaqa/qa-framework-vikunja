"""Requests that send mail, with the mail server taken away and brought back.

Because these stop the mail server, they are also the only tests that can
leave the product's mail daemon wedged (VKJ-013). The module heals it in
teardown, so the defect these tests describe cannot cascade into the setup
of whatever runs next.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Iterator

import pytest

from vikunja_qa import stand
from vikunja_qa.config import Settings
from vikunja_qa.scenes import SceneBuilder
from vikunja_qa.transport.client import HttpClient
from vikunja_qa.transport.mailpit import MailNotFoundError, MailpitClient

pytestmark = pytest.mark.covers("RES")

#: The product's mailer.queuetimeout default. The daemon reconnects only
#: after its queue has been idle this long, which both the recovery test and
#: the healing teardown turn on.
QUEUE_TIMEOUT_S = 30
_IDLE_MARGIN_S = 6
_STEADY_INTERVAL_S = 5
_RECOVERY_WINDOW_S = 25


def _request_a_mail(settings: Settings) -> str:
    """Register a throwaway account and return its address. Registration
    sends a confirmation message, which is a mail we can then wait for."""
    anonymous = HttpClient(settings.api_v1, attach_traffic=False)
    username = f"resmail{uuid.uuid4().hex[:10]}"
    email = f"{username}@qa.local"
    registered = anonymous.post(
        "/register",
        json={"username": username, "password": settings.user_password, "email": email},
    )
    assert registered.ok, registered.describe()
    return email


def _mail_is_flowing(settings: Settings, mailpit: MailpitClient) -> bool:
    email = _request_a_mail(settings)
    try:
        mailpit.wait_for_message(email, timeout=15)
    except MailNotFoundError:
        return False
    return True


@pytest.fixture(autouse=True)
def _heal_mail(settings: Settings, mailpit: MailpitClient) -> Iterator[None]:
    """Leave the mail daemon delivering again, whatever the test did to it.

    The daemon reconnects only after an idle gap (VKJ-013), so recovery is a
    wait with no traffic, then a probe. Sending the probe first would reset
    the very timer being waited on, so the order matters.
    """
    yield
    time.sleep(QUEUE_TIMEOUT_S + _IDLE_MARGIN_S)
    assert _mail_is_flowing(settings, mailpit), (
        "mail did not recover even after an idle gap; the stand is left unhealthy for the next test"
    )


def test_a_password_reset_is_accepted_while_the_mail_server_is_down(scene: SceneBuilder) -> None:
    """Mail goes out through a queue, so an outage should delay the message,
    not fail the request that asked for it."""
    world = scene.done()

    with stand.stopped("mailpit"):
        requested = world.owner.v1.post("/user/password/token", json={"email": world.owner.email})

    assert requested.ok, (
        "a request whose only side effect is a message failed outright while the mail "
        f"server was down\n{requested.describe()}"
    )


@pytest.mark.finding("VKJ-013")
@pytest.mark.xfail(
    reason=(
        "VKJ-013: after the mail server restarts, the daemon keeps sending on the dead "
        "connection and only reconnects after a 30s idle gap, so steady traffic loses every "
        "message until it pauses"
    ),
    strict=False,
)
def test_mail_recovers_after_the_server_returns_even_under_traffic(
    settings: Settings, mailpit: MailpitClient
) -> None:
    """Once the server is back, mail should resume within a bound that does
    not depend on the traffic falling silent."""
    with stand.stopped("mailpit"):
        _request_a_mail(settings)  # attempted during the outage; poisons the connection

    sent = []
    deadline = time.monotonic() + _RECOVERY_WINDOW_S
    while time.monotonic() < deadline:
        sent.append(_request_a_mail(settings))
        time.sleep(_STEADY_INTERVAL_S)

    delivered = any(mailpit.messages_for(email) for email in sent)
    assert delivered, (
        f"none of {len(sent)} messages sent over {_RECOVERY_WINDOW_S}s of steady traffic arrived "
        "after the mail server came back; mail recovers only once traffic pauses"
    )
