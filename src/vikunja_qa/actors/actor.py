"""Who is making the request.

An actor bundles an identity, the credential proving it, and clients for
both API versions. Tests name a role and get one of these; they never
assemble credentials by hand.

The same person can appear under different credentials, which is what
`using` is for: `owner.using(token_auth)` is the same account arriving
through a scoped API token instead of a session.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import cached_property

from vikunja_qa.auth.strategies import AuthStrategy
from vikunja_qa.clients.api import Api
from vikunja_qa.transport.client import HttpClient


@dataclass
class Actor:
    """One caller, bound to one credential."""

    role: str
    auth: AuthStrategy
    v1: HttpClient
    v2: HttpClient
    username: str = ""
    email: str = ""
    password: str = ""
    user_id: int | None = None
    extra: dict[str, object] = field(default_factory=dict)

    def using(self, auth: AuthStrategy, role: str | None = None) -> Actor:
        """The same identity arriving with a different credential."""
        return Actor(
            role=role or f"{self.role}+{auth.label}",
            auth=auth,
            v1=self.v1.with_auth(auth),
            v2=self.v2.with_auth(auth),
            username=self.username,
            email=self.email,
            password=self.password,
            user_id=self.user_id,
            extra=dict(self.extra),
        )

    def on_its_own_connection(self, role: str | None = None) -> Actor:
        """The same identity, with a connection pool of its own.

        For callers meant to act at the same instant as each other: a
        `requests.Session` is not built to be driven from several threads
        at once, and sharing one would risk measuring the suite rather than
        the product.
        """
        return Actor(
            role=role or self.role,
            auth=self.auth,
            v1=self.v1.unshared(),
            v2=self.v2.unshared(),
            username=self.username,
            email=self.email,
            password=self.password,
            user_id=self.user_id,
            extra=dict(self.extra),
        )

    def raw(self, version: str) -> HttpClient:
        """Version-indexed transport, for tests parameterised over both."""
        if version in ("v1", "1"):
            return self.v1
        if version in ("v2", "2"):
            return self.v2
        raise ValueError(f"unknown API version {version!r}")

    @cached_property
    def api(self) -> Api:
        """Area clients speaking v1, which is where the fuller surface
        lives. Tests needing v2 reach for `api_v2` or the raw client."""
        return Api(self.v1)

    @cached_property
    def api_v2(self) -> Api:
        return Api(self.v2)

    def __str__(self) -> str:
        who = self.username or self.auth.label
        return f"{self.role}({who})"
