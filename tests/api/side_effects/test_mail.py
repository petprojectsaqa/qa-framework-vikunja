"""Mail the product sends, read back from the stand's mail trap.

The API only says a message was queued. Whether it left, reached the right
address and carried a working link is a question for the mail server.
"""

from __future__ import annotations

import pytest

from vikunja_qa.scenes import SceneBuilder
from vikunja_qa.transport.mailpit import MailpitClient

pytestmark = pytest.mark.covers("ASY")


@pytest.mark.smoke
def test_registration_sends_a_confirmation_message(
    scene: SceneBuilder, mailpit: MailpitClient
) -> None:
    """Every account in the suite walks this path, so when it breaks it
    explains a failure everywhere else; worth knowing first."""
    owner = scene.done().owner

    message = mailpit.wait_for_message(owner.email, timeout=20)

    assert owner.username in message.get("Subject", ""), (
        f"the welcome message does not name the account: {message.get('Subject')!r}"
    )
    assert "userEmailConfirm=" in MailpitClient.body_of(message), (
        "the welcome message carries no confirmation link"
    )


def test_a_password_reset_sends_a_token(scene: SceneBuilder, mailpit: MailpitClient) -> None:
    owner = scene.done().owner

    # Requested by address, not by username: whoever lost their password
    # may not remember the other either.
    requested = owner.v1.post("/user/password/token", json={"email": owner.email})
    assert requested.ok, requested.describe()

    token = mailpit.password_reset_token(owner.email, timeout=20)

    assert len(token) > 20, f"the reset token looks too short to be one: {token!r}"
