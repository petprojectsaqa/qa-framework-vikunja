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

    def token_matching(
        self, recipient: str, pattern: re.Pattern[str], *, timeout: float | None = None
    ) -> str:
        """Wait for the message that carries this token, not merely the first.

        One address collects several messages: the welcome note, then a
        password reset, then whatever else. Taking the first one that
        arrives makes the answer depend on which message the trap happens
        to return, which is a race that shows up as an occasional failure
        under load and never on a quiet machine.
        """
        deadline = time.monotonic() + (timeout or self._timeout)
        interval = 0.05
        subjects: list[str] = []
        while time.monotonic() < deadline:
            subjects = []
            for summary in self.messages_for(recipient):
                message = self.message(summary["ID"])
                subjects.append(str(message.get("Subject")))
                match = pattern.search(self.body_of(message))
                if match:
                    return match.group(1)
            time.sleep(interval)
            interval = min(interval * 1.5, 0.5)

        raise MailNotFoundError(
            f"no message to {recipient} carried a token matching {pattern.pattern!r} "
            f"within {timeout or self._timeout:.0f}s; subjects seen: {subjects or 'none'}"
        )

    def confirmation_token(self, recipient: str, *, timeout: float | None = None) -> str:
        return self.token_matching(recipient, CONFIRM_TOKEN, timeout=timeout)

    def password_reset_token(self, recipient: str, *, timeout: float | None = None) -> str:
        return self.token_matching(recipient, PASSWORD_RESET_TOKEN, timeout=timeout)

    def clear(self) -> None:
        self._session.delete(f"{self._base_url}/api/v1/messages", timeout=10)
