"""The value every call returns.

Wrapping the raw response buys two things the suite needs everywhere:
failure messages that show what actually happened, and one place that
understands both error shapes the product speaks.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ApiResponse:
    method: str
    url: str
    status: int
    headers: dict[str, str]
    body: Any
    elapsed_ms: float
    request_body: Any = None
    auth_label: str = ""
    text: str = field(default="", repr=False)

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


def _render(value: Any, limit: int) -> str:
    if isinstance(value, (dict, list)):
        rendered = json.dumps(value, ensure_ascii=False, indent=2, default=str)
    else:
        rendered = str(value)
    if len(rendered) > limit:
        return f"{rendered[:limit]}... [{len(rendered) - limit} more characters]"
    return rendered
