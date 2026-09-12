"""Credentials that are the wrong shape.

An API token is the prefix `tk_` and forty hexadecimal characters, looked
up by its last eight with a hash comparison after. Anything shorter than
that is a slice the product has to guard, which is the sort of guard that
gets added after the first crash and removed by accident later.

Every shape here must be refused the same way: a 401 that says the
credential was no good, never a server error and never a way in.
"""

from __future__ import annotations

import pytest

from vikunja_qa.actors.actor import Actor
from vikunja_qa.auth.strategies import ApiToken, RawHeader

pytestmark = [pytest.mark.covers("NEG"), pytest.mark.covers("AUT")]

#: Not a token, in every way a token can fail to be one.
NOT_A_TOKEN = [
    pytest.param("", id="empty"),
    pytest.param("tk_", id="prefix-only"),
    pytest.param("tk_abc", id="too-short-to-slice"),
    pytest.param("tk_" + "0" * 40, id="right-shape-wrong-value"),
    pytest.param("tk_" + "z" * 40, id="right-shape-not-hexadecimal"),
    pytest.param("xx_" + "a" * 40, id="wrong-prefix"),
    pytest.param("a" * 43, id="no-prefix"),
    pytest.param("tk_" + "a" * 4000, id="far-too-long"),
    pytest.param("tk_ ; drop table users", id="punctuation"),
]

#: Not a credential at all, in the header the product reads it from.
NOT_A_HEADER = [
    pytest.param("", id="empty"),
    pytest.param("Bearer", id="scheme-with-no-value"),
    pytest.param("Bearer ", id="scheme-with-a-space"),
    pytest.param("Basic !!!!", id="basic-that-is-not-base64"),
    pytest.param("Weird abc", id="a-scheme-nobody-offers"),
    pytest.param("Bearer a.b.c", id="something-shaped-like-a-jwt"),
]


@pytest.mark.parametrize("value", NOT_A_TOKEN)
def test_a_malformed_api_token_is_refused_without_breaking_anything(
    owner: Actor, value: str
) -> None:
    caller = owner.using(ApiToken(value, "malformed"))

    answered = caller.api.projects.all()

    assert answered.status == 401, f"the wrong credential was not refused\n{answered.describe()}"
    assert answered.error_code, (
        f"the refusal carries no domain code, so a client cannot tell why\n{answered.describe()}"
    )


@pytest.mark.parametrize("value", NOT_A_HEADER)
def test_a_malformed_authorization_header_is_refused_without_breaking_anything(
    owner: Actor, value: str
) -> None:
    caller = owner.using(RawHeader(value, "malformed"))

    answered = caller.api.projects.all()

    assert answered.status == 401, f"the wrong header was not refused\n{answered.describe()}"
    assert answered.error_code, (
        f"the refusal carries no domain code, so a client cannot tell why\n{answered.describe()}"
    )


def test_the_same_refusal_whatever_the_shape(owner: Actor) -> None:
    """One message for every bad credential. A refusal that varies with the
    shape tells whoever is guessing which half of the guess was right."""
    answers = {
        shape: owner.using(ApiToken(shape, "malformed")).api.projects.all()
        for shape in ("", "tk_", "tk_" + "0" * 40, "xx_" + "a" * 40)
    }

    distinct = {(answer.status, answer.error_code) for answer in answers.values()}

    assert len(distinct) == 1, f"the refusal differs by shape: {distinct}"
