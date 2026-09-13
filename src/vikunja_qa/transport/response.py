"""The value every call returns.

Wrapping the raw response buys two things the suite needs everywhere:
failure messages that show what actually happened, and one place that
understands both error shapes the product speaks.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ApiResponse:
    method: str
    url: str
    status: int
    #: Case-insensitive, as header names are in HTTP. The product is written
    #: in Go, which sends `Www-Authenticate`; a plain dict would make
    #: `headers.get("WWW-Authenticate")` quietly answer None.
    headers: Mapping[str, str]
    body: Any
    elapsed_ms: float
    request_body: Any = None
    auth_label: str = ""
    text: str = field(default="", repr=False)
    #: The body exactly as received. For binary payloads such as attachments,
    #: where decoding to text and back would not return the same bytes.
    content: bytes = field(default=b"", repr=False)
    #: Whether the body parsed as JSON. `body` falls back to the raw text
    #: when it did not, and the two cases look identical from the outside:
    #: a product answering `"ok"` and a product answering an HTML error page
    #: both leave a string behind. The contract check needs to tell them
    #: apart, because only one of them is a body it can hold to a schema.
    parsed: bool = True

    # --- reading the payload ------------------------------------------------

    @property
    def json(self) -> Any:
        """The parsed body. Raises if the response was not JSON, which is
        itself worth failing on for an API that claims to speak it."""
        if isinstance(self.body, (dict, list)):
            return self.body
        raise AssertionError(
            f"expected a JSON body but got {type(self.body).__name__}\n{self.describe()}"
        )

    def __getitem__(self, key: str) -> Any:
        return self.json[key]

    def get(self, key: str, default: Any = None) -> Any:
        body = self.body
        return body.get(key, default) if isinstance(body, dict) else default

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    # --- errors -------------------------------------------------------------

    @property
    def error_code(self) -> int | None:
        """Vikunja's numeric domain error code.

        v1 returns it as a flat `code` field. v2 answers in RFC 9457 and
        deliberately carries the same value across, because clients key
        their translations off it. Reading both shapes here is what lets
        the cross-version error checks compare like with like.
        """
        body = self.body
        if not isinstance(body, dict):
            return None
        code = body.get("code")
        return code if isinstance(code, int) else None

    @property
    def error_message(self) -> str | None:
        body = self.body
        if not isinstance(body, dict):
            return None
        for key in ("message", "detail", "title"):
            value = body.get(key)
            if isinstance(value, str):
                return value
        return None

    # --- reporting ----------------------------------------------------------

    def describe(self, max_body: int = 1500) -> str:
        """Compact rendering used in assertion messages and attachments."""
        lines = [f"{self.method} {self.url}"]
        if self.auth_label:
            lines.append(f"as: {self.auth_label}")
        if self.request_body is not None:
            lines.append(f"sent: {_render(self.request_body, max_body)}")
        lines.append(f"status: {self.status}  ({self.elapsed_ms:.0f} ms)")
        if self.error_code is not None:
            lines.append(f"domain code: {self.error_code}")
        lines.append(f"body: {_render(self.body if self.body != '' else self.text, max_body)}")
        return "\n".join(lines)

    def __str__(self) -> str:
        return self.describe()


#: Fields whose value is a credential, whatever it is worth.
#:
#: `describe` feeds two places: the message on a failed assertion, and the
#: attachments in a report this project publishes to the open web. Neither
#: needs the literal string. A reader debugging a failure needs to know a
#: token was there and roughly how long it was; nobody needs to be able to
#: replay it, and a testing tool that prints credentials into a public page
#: is teaching the wrong habit even when the stand behind them is gone.
#:
#: This redacts the rendering and nothing else. `body` is untouched, so a
#: test that reads `response["token"]` still gets the token.
SECRET_FIELDS = frozenset(
    {
        "token",
        "access_token",
        "refresh_token",
        "password",
        "new_password",
        "old_password",
        "secret",
        "totp_passcode",
        "passcode",
    }
)


def _redacted(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: (
                f"<redacted, {len(str(item))} characters>"
                if str(key).lower() in SECRET_FIELDS and item
                else _redacted(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redacted(item) for item in value]
    return value


def _render(value: Any, limit: int) -> str:
    if isinstance(value, (dict, list)):
        rendered = json.dumps(_redacted(value), ensure_ascii=False, indent=2, default=str)
    else:
        rendered = str(value)
    if len(rendered) > limit:
        return f"{rendered[:limit]}... [{len(rendered) - limit} more characters]"
    return rendered
