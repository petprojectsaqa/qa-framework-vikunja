"""Makes actors.

Isolation in this suite comes from ownership, not from cleaning up: every
test works under its own freshly registered accounts, and accounts that
have never met cannot see each other's data. That buys full parallelism
with no truncation between tests. See docs/strategy.md, section 1.

Registration here walks the product's real path, confirmation mail
included, because the stand runs with the mailer on.
"""

from __future__ import annotations

import re
import uuid

import allure

from vikunja_qa.actors.actor import Actor
from vikunja_qa.auth.strategies import Anonymous, AuthStrategy, SessionToken
from vikunja_qa.config import Settings
from vikunja_qa.transport.client import HttpClient, ResponseHook
from vikunja_qa.transport.mailpit import MailpitClient

# Vikunja accepts more than this, but keeping generated names to lowercase
# alphanumerics avoids arguing with validation rules that are not under test.
_UNSAFE = re.compile(r"[^a-z0-9]+")


class RegistrationError(AssertionError):
    pass


class ActorFactory:
    """Creates accounts and hands back actors bound to them.

    `label` is threaded into every generated username so that a row left
    in the database after a red run points straight back at the test that
    made it.
    """

    def __init__(
        self,
        settings: Settings,
        mail: MailpitClient,
        *,
        label: str = "test",
        hooks: list[ResponseHook] | None = None,
        mail_timeout: float | None = None,
    ) -> None:
        self._settings = settings
        self._mail = mail
        self._label = self._normalise(label)
        self._hooks = hooks if hooks is not None else []
        #: How long to wait for the welcome mail. Overridable because
        #: registering during collection, on a runner where nothing is warm
        #: yet, needs more patience than registering mid-run; the client's
        #: own default is never reached, since this is always passed on.
        self._mail_timeout = settings.mail_timeout if mail_timeout is None else mail_timeout

    # --- naming -------------------------------------------------------------

    @staticmethod
    def _normalise(label: str) -> str:
        cleaned = _UNSAFE.sub("", label.lower())
        return cleaned[-24:] or "test"

    def _new_username(self, role: str) -> str:
        return f"{self._normalise(role)}{self._label}{uuid.uuid4().hex[:8]}"

    # --- clients ------------------------------------------------------------

    def _client(self, base: str, auth: AuthStrategy) -> HttpClient:
        return HttpClient(
            base,
            auth,
            timeout=self._settings.request_timeout,
            attach_traffic=self._settings.attach_traffic,
            hooks=self._hooks,
        )

    def _actor(self, role: str, auth: AuthStrategy, **fields: object) -> Actor:
        return Actor(
            role=role,
            auth=auth,
            v1=self._client(self._settings.api_v1, auth),
            v2=self._client(self._settings.api_v2, auth),
            **fields,  # type: ignore[arg-type]
        )

    # --- producers ----------------------------------------------------------

    def anonymous(self) -> Actor:
        """A caller with no credential. Every access-matrix row needs one."""
        return self._actor("anon", Anonymous())

    def user(self, role: str = "user") -> Actor:
        """Register a fresh account, confirm its address, log in."""
        username = self._new_username(role)
        email = f"{username}@qa.local"
        password = self._settings.user_password

        with allure.step(f"create actor {role} ({username})"):
            unauthenticated = self._client(self._settings.api_v1, Anonymous())

            registered = unauthenticated.post(
                "/register",
                json={"username": username, "password": password, "email": email},
            )
            if not registered.ok:
                raise RegistrationError(f"could not register {username}\n{registered.describe()}")
            user_id = registered.get("id")

            # The mailer is on, so the account is parked until the token
            # from the welcome message is spent.
            token = self._mail.confirmation_token(email, timeout=self._mail_timeout)
            confirmed = unauthenticated.post("/user/confirm", json={"token": token})
            if not confirmed.ok:
                raise RegistrationError(f"could not confirm {email}\n{confirmed.describe()}")

            logged_in = unauthenticated.post(
                "/login", json={"username": username, "password": password}
            )
            if not logged_in.ok or not logged_in.get("token"):
                raise RegistrationError(f"could not log in {username}\n{logged_in.describe()}")

            return self._actor(
                role,
                SessionToken(str(logged_in["token"]), subject=username),
                username=username,
                email=email,
                password=password,
                user_id=user_id,
            )

    def users(self, *roles: str) -> tuple[Actor, ...]:
        """Several accounts at once, one per named role."""
        return tuple(self.user(role) for role in roles)
