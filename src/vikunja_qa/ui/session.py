"""Putting a browser in front of an account that already exists.

No test signs in through the form. The account is registered, confirmed
and logged in over the API, and its session token is placed in browser
storage before the application boots, so a test opens straight onto the
page it examines. A test then fails only when the thing it checks is
broken, not whenever the sign-in form changes.

Contexts come from pytest-playwright's `new_context` factory rather than
from `browser.new_context`. The factory is what records traces, videos
and screenshots according to `--tracing`, `--video` and `--screenshot`;
bypassing it leaves those options set and silently doing nothing.

Two scripts run before any page script. `token` is where the frontend
keeps its session, so writing it there is exactly what signing in would
have done. `TESTING` makes the application emit its `data-cy` attributes,
which the production build strips unless a test runner injects the flag,
as the product's own source says it should.
"""

from __future__ import annotations

import json
from typing import Protocol

from playwright.sync_api import BrowserContext, Page

from vikunja_qa.actors.actor import Actor
from vikunja_qa.auth.strategies import SessionToken

#: Pinned rather than inherited. The application follows the browser's
#: language, so leaving it to the machine running the suite would make
#: every text selector depend on where it ran. Localisation tests set a
#: locale deliberately instead.
DEFAULT_LOCALE = "en-GB"

VIEWPORT = {"width": 1400, "height": 900}


class NotASessionError(AssertionError):
    pass


class PageOpener(Protocol):
    """Opens a page signed in as someone, in a given language. What the
    browser layer's `open_as` fixture hands a test."""

    def __call__(self, actor: Actor, *, locale: str = DEFAULT_LOCALE) -> Page: ...


class AnonymousOpener(Protocol):
    """Opens a page at a path with no credential of any kind.

    Its own type rather than `PageOpener` with something falsy, because the
    two are different situations: a visitor who has never signed in is what
    a public link is for, and a context holding a bad token is a different
    question with a different failure.
    """

    def __call__(self, path: str) -> Page: ...


def session_token_of(actor: Actor) -> str:
    if not isinstance(actor.auth, SessionToken):
        raise NotASessionError(
            f"{actor} holds a {actor.auth.label} credential; a browser can only carry a "
            "session token"
        )
    return actor.auth.token


def sign_in(context: BrowserContext, actor: Actor) -> BrowserContext:
    """Make every page this context opens start signed in as the actor."""
    token = json.dumps(session_token_of(actor))
    context.add_init_script(
        f"window.TESTING = true;\ntry {{ localStorage.setItem('token', {token}); }} catch (e) {{}}"
    )
    return context
