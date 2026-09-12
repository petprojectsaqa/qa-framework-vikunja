"""Reader for the stand's mail trap.

Two jobs. It completes registration, because the stand runs with the
mailer on and Vikunja then holds new accounts at
"email confirmation required" until the token in the welcome message is
spent. And it is where the mail-related assertions look.

Going through the real message rather than flipping the account status in
the database keeps the mail pipeline under continuous test and leaves no
back door in the suite. The full round trip costs well under a second.
"""

from __future__ import annotations

import re
import time
from typing import Any
from urllib.parse import quote

import requests

CONFIRM_TOKEN = re.compile(r"userEmailConfirm=([A-Za-z0-9_\-]+)")
PASSWORD_RESET_TOKEN = re.compile(r"userPasswordReset=([A-Za-z0-9_\-]+)")


class MailNotFoundError(AssertionError):
    pass


class MailpitClient:
    def __init__(self, base_url: str, timeout: float = 20.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._session = requests.Session()

    def messages_for(self, recipient: str) -> list[dict[str, Any]]:
        response = self._session.get(
            f"{self._base_url}/api/v1/search",
            params={"query": f"to:{recipient}"},
            timeout=10,
        )
        response.raise_for_status()
        payload = response.json()
        messages = payload.get("messages", [])
        return messages if isinstance(messages, list) else []

    def wait_for_message(
        self,
        recipient: str,
        *,
        timeout: float | None = None,
        subject_contains: str | None = None,
    ) -> dict[str, Any]:
        """Poll until a message for this recipient shows up.

        Polling rather than sleeping: the wait ends the moment the mail
        lands, and the deadline is explicit. See docs/strategy.md,
        section 7.
        """
        deadline = time.monotonic() + (timeout or self._timeout)
        interval = 0.05
        while time.monotonic() < deadline:
            for summary in self.messages_for(recipient):
                if subject_contains and subject_contains not in summary.get("Subject", ""):
                    continue
                return self.message(summary["ID"])
            time.sleep(interval)
            interval = min(interval * 1.5, 0.5)

        raise MailNotFoundError(
            f"no message for {recipient}"
            + (f" with subject containing {subject_contains!r}" if subject_contains else "")
            + f" within {timeout or self._timeout:.0f}s"
        )

    def message(self, message_id: str) -> dict[str, Any]:
        response = self._session.get(
            f"{self._base_url}/api/v1/message/{quote(message_id)}", timeout=10
        )
        response.raise_for_status()
        return dict(response.json())

    @staticmethod
    def body_of(message: dict[str, Any]) -> str:
        return f"{message.get('Text') or ''}\n{message.get('HTML') or ''}"

    def confirmation_token(self, recipient: str, *, timeout: float | None = None) -> str:
        message = self.wait_for_message(recipient, timeout=timeout)
        match = CONFIRM_TOKEN.search(self.body_of(message))
        if not match:
            raise MailNotFoundError(
                f"the message to {recipient} carried no confirmation token; "
                f"subject was {message.get('Subject')!r}"
            )
        return match.group(1)

    def password_reset_token(self, recipient: str, *, timeout: float | None = None) -> str:
        message = self.wait_for_message(recipient, timeout=timeout)
        match = PASSWORD_RESET_TOKEN.search(self.body_of(message))
        if not match:
            raise MailNotFoundError(f"the message to {recipient} carried no reset token")
        return match.group(1)

    def clear(self) -> None:
        self._session.delete(f"{self._base_url}/api/v1/messages", timeout=10)
