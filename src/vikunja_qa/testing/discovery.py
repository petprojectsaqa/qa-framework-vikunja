"""Reading the product at collection time, for the generated test families.

The sweep and the token scope matrix build their cases from what the
running product publishes: both API descriptions, and the catalogue of
permissions a token may carry. That has to happen while pytest is still
collecting, because parametrisation is decided then.

Two flavours, on purpose. A fixture that cannot reach the stand raises,
so the test errors loudly: a missing stand is an environment failure, and
hundreds of quiet skips in CI would hide it. A module being collected
skips instead, with the actual reason, because there is no test yet to
fail and an import-time exception would abort the whole collection.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any, NoReturn
from urllib.parse import urlsplit

import pytest

from vikunja_qa.actors.factory import ActorFactory
from vikunja_qa.config import get_settings
from vikunja_qa.contracts.errors import ErrorCase, absent_object_cases
from vikunja_qa.contracts.scopes import ScopeCase, cases_for
from vikunja_qa.contracts.spec import SpecIndex
from vikunja_qa.contracts.sweep import Call, calls_for
from vikunja_qa.transport.mailpit import MailpitClient

#: Collection runs on a cold runner before anything is warm, and the
#: catalogue needs a confirmed account; a slow first mail should not cost
#: a whole module.
_COLLECTION_MAIL_TIMEOUT = 60


# --- loaders: these raise ----------------------------------------------------


@lru_cache(maxsize=1)
def descriptions() -> tuple[SpecIndex, ...]:
    """Both API descriptions, fetched from the running instance."""
    settings = get_settings()
    return (
        SpecIndex.from_url(
            f"{settings.api_v1}/docs.json",
            label="v1",
            base_path=urlsplit(settings.api_v1).path,
        ),
        SpecIndex.from_url(
            f"{settings.api_v2}/openapi.json",
            label="v2",
            base_path=urlsplit(settings.api_v2).path,
        ),
    )


@lru_cache(maxsize=1)
def permission_catalogue() -> Any:
    """The token permission catalogue as the product publishes it.

    Reading it needs a signed-in account, so this registers one.
    """
    settings = get_settings()
    mail = MailpitClient(settings.mailpit_url, timeout=_COLLECTION_MAIL_TIMEOUT)
    reader = ActorFactory(settings, mail, label="catalogue").user("catalogue")
    return reader.api.tokens.routes().body


# --- collection: these skip the module --------------------------------------


def _skip_module(what: str, exc: BaseException) -> NoReturn:
    # allow_module_level is not optional: without it pytest raises its own
    # complaint about skipping at import time, and that complaint buries
    # the reason the stand could not be read.
    pytest.skip(f"cannot read {what}: {type(exc).__name__}: {exc}", allow_module_level=True)


def generated_calls() -> tuple[Call, ...]:
    """One safe, concrete call per operation across both descriptions."""
    try:
        specs = descriptions()
    except Exception as exc:  # noqa: BLE001 - any failure means the stand is unreadable
        _skip_module("the API descriptions", exc)
    return tuple(call for spec in specs for call in calls_for(spec))


def described_specs() -> tuple[SpecIndex, ...]:
    """The descriptions themselves, for module-level checks on the sweep."""
    try:
        return descriptions()
    except Exception as exc:  # noqa: BLE001 - any failure means the stand is unreadable
        _skip_module("the API descriptions", exc)


def error_cases() -> tuple[ErrorCase, ...]:
    """One case per operation both versions describe and can be asked about
    an identifier that does not exist."""
    try:
        specs = descriptions()
    except Exception as exc:  # noqa: BLE001 - any failure means the stand is unreadable
        _skip_module("the API descriptions", exc)
    return tuple(absent_object_cases(list(specs)))


def scope_cases() -> tuple[ScopeCase, ...]:
    """One case per area of the permission catalogue."""
    try:
        catalogue = permission_catalogue()
    except Exception as exc:  # noqa: BLE001 - any failure means the stand is unreadable
        _skip_module("the permission catalogue", exc)
    return tuple(cases_for(catalogue))
