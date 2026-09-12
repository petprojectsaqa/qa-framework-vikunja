"""The four ways a caller can prove who it is to Vikunja.

All four appear in the access matrix, so the transport layer treats them
uniformly: a strategy knows how to stamp a request and how to describe
itself in a report. Nothing here decides whether a request *should*
succeed; that is the test's job.
"""

from __future__ import annotations

import base64
from abc import ABC, abstractmethod
from collections.abc import MutableMapping


class AuthStrategy(ABC):
    """Stamps outgoing requests with one credential."""

    @abstractmethod
    def apply(self, headers: MutableMapping[str, str]) -> None: ...

    @property
    @abstractmethod
    def label(self) -> str:
        """Short description for logs and report steps. Never the secret."""


class Anonymous(AuthStrategy):
    """No credential at all. The `anon` actor in the access matrix."""

    def apply(self, headers: MutableMapping[str, str]) -> None:
        headers.pop("Authorization", None)

    @property
    def label(self) -> str:
        return "anonymous"


class SessionToken(AuthStrategy):
    """The JWT handed out by POST /login.

    Default lifetime on the stand is 72 hours, so a token minted at the
    start of a run stays valid for its whole duration.
    """

    def __init__(self, token: str, subject: str = "") -> None:
        self._token = token
        self._subject = subject

    def apply(self, headers: MutableMapping[str, str]) -> None:
        headers["Authorization"] = f"Bearer {self._token}"

    @property
    def token(self) -> str:
        return self._token

    @property
    def label(self) -> str:
        return f"session:{self._subject}" if self._subject else "session"


class ApiToken(AuthStrategy):
    """A scoped API token.

    Sent on the same header as a session token; the product tells them
    apart by the `tk_` prefix. Permissions are a map of area to actions,
    which is what the scope matrix in the coverage doc iterates over.
    """

    PREFIX = "tk_"

    def __init__(self, token: str, title: str = "") -> None:
        self._token = token
        self._title = title

    def apply(self, headers: MutableMapping[str, str]) -> None:
        headers["Authorization"] = f"Bearer {self._token}"

    @property
    def token(self) -> str:
        return self._token

    @property
    def label(self) -> str:
        return f"api-token:{self._title}" if self._title else "api-token"


class LinkShareToken(AuthStrategy):
    """The JWT obtained by trading a share hash at POST /shares/{hash}/auth.

    Carries the permission the share was created with and is scoped to a
    single project, which is exactly what GHSA-2pv8-4c52-mf8j was about.
    """

    def __init__(self, token: str, share_hash: str = "") -> None:
        self._token = token
        self._hash = share_hash

    def apply(self, headers: MutableMapping[str, str]) -> None:
        headers["Authorization"] = f"Bearer {self._token}"

    @property
    def token(self) -> str:
        return self._token

    @property
    def label(self) -> str:
        return f"link-share:{self._hash[:8]}" if self._hash else "link-share"


class BasicAuth(AuthStrategy):
    """Username and password on the wire. The CalDAV entrance uses this."""

    def __init__(self, username: str, password: str) -> None:
        self._username = username
        self._password = password

    def apply(self, headers: MutableMapping[str, str]) -> None:
        raw = f"{self._username}:{self._password}".encode()
        headers["Authorization"] = f"Basic {base64.b64encode(raw).decode()}"

    @property
    def label(self) -> str:
        return f"basic:{self._username}"


class RawHeader(AuthStrategy):
    """Verbatim Authorization value.

    Two uses: the product's test-support API, which wants the bare secret
    with no scheme, and negative tests that deliberately send malformed
    credentials.
    """

    def __init__(self, value: str, description: str = "raw") -> None:
        self._value = value
        self._description = description

    def apply(self, headers: MutableMapping[str, str]) -> None:
        headers["Authorization"] = self._value

    @property
    def label(self) -> str:
        return self._description
