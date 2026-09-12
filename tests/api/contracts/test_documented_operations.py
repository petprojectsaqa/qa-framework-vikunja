"""Every operation a description declares actually exists.

A described operation the product answers 405 to does not exist: a client
generated from the description calls it and is turned away. The list of
operations comes from the descriptions themselves, so this grows with them.

Asked anonymously on purpose. Routing decides whether a verb reaches a
path before authentication is consulted, so 405 means the same with or
without a credential, and asking without one keeps the check from creating
anything: a collection-level create such as `PUT /labels` succeeds when it
is authenticated, and a sweep should leave nothing behind.
"""

from __future__ import annotations

import pytest

from vikunja_qa.actors.factory import ActorFactory
from vikunja_qa.contracts.sweep import Call
from vikunja_qa.testing import discovery

pytestmark = [
    pytest.mark.covers("CON"),
    pytest.mark.generated,
    pytest.mark.usefixtures("contracts_collect_only"),
]

CALLS = discovery.generated_calls()

#: Described operations the product answers 405 to. Each is a reported
#: finding. Anything answering 405 that is not listed here fails, which is
#: the same arrangement the contract baseline uses: the list may only shrink.
KNOWN_ABSENT: dict[tuple[str, str], str] = {
    ("v1", "PUT /labels/{id}"): "VKJ-007",
    ("v1", "POST /migration/vikunja-file/migrate"): "VKJ-007",
}


def _marks(call: Call) -> list[pytest.MarkDecorator]:
    known = KNOWN_ABSENT.get((call.spec, call.operation))
    return [pytest.mark.finding(known)] if known else []


@pytest.mark.parametrize(
    "call",
    [pytest.param(call, id=call.id, marks=_marks(call)) for call in CALLS],
)
def test_documented_operation_exists(call: Call, actors: ActorFactory) -> None:
    response = actors.anonymous().raw(call.spec).request(call.method, call.path)
    known = KNOWN_ABSENT.get((call.spec, call.operation))

    if response.status != 405:
        assert known is None, (
            f"{call.operation} no longer answers 405, so {known} may be fixed; "
            "remove it from KNOWN_ABSENT"
        )
        return

    assert known is not None, (
        f"{call.operation} is described, but the product rejects that verb, so a client "
        f"built from the description cannot call it\n{response.describe()}"
    )
