"""Putting a browser in front of an account that already exists.

No test signs in through the form. The account is registered, confirmed
and logged in over the API, and the session token is placed in browser
storage before the application boots. A test then opens straight onto the
page it is about to examine.

That is worth more than the seconds it saves. A test fails only when the
thing it checks is broken, rather than whenever the sign-in form changes,
and the data it needs is built by one API call instead of forty clicks.

Two scripts run before any page script:

`token` is where the frontend keeps its session, so writing it there is
exactly what signing in would have done.

`TESTING` makes the application emit its `data-cy` attributes, which its
production build otherwise strips. The product's own source says this
flag is meant to be injected by a test runner, which is what we are.
Selectors here still prefer roles and text where those identify an
element; the attribute is for the cases where nothing else does.
"""

from __future__ import annotations

import json

from playwright.sync_api import Browser, BrowserContext, Page

from vikunja_qa.actors.actor import Actor
from vikunja_qa.auth.strategies import SessionToken


class NotASessionError(AssertionError):
    pass


def _token_of(actor: Actor) -> str:
    if not isinstance(actor.auth, SessionToken):
        raise NotASessionError(
            f"{actor} holds a {actor.auth.label} credential; the browser can only "
            "carry a session token"
        )
    return actor.auth.token


#: Pinned rather than inherited. The application follows the browser's
#: language, so leaving this to the machine running the suite would make
#: every text-based selector depend on where it ran. The localisation
#: tests set it deliberately instead.
DEFAULT_LOCALE = "en-GB"


def context_for(
    browser: Browser,
    actor: Actor,
    base_url: str,
    *,
    locale: str = DEFAULT_LOCALE,
    **kwargs: object,
) -> BrowserContext:
    """A browser context already signed in as this actor."""
    context = browser.new_context(base_url=base_url, locale=locale, **kwargs)  # type: ignore[arg-type]
    context.add_init_script(
        "window.TESTING = true;\n"
        f"try {{ localStorage.setItem('token', {json.dumps(_token_of(actor))}); }} catch (e) {{}}"
    )
    return context


def open_at(context: BrowserContext, path: str = "/") -> Page:
    """A page already on the route the test cares about."""
    page = context.new_page()
    page.goto(path)
    return page
