"""The ledger that carries a run's findings from xdist workers to the controller.

Its one job is to add up correctly after crossing a process boundary, so
that is what these check: counting, merging, and surviving the trip as
plain data.
"""

from __future__ import annotations

import json
from collections import Counter

from vikunja_qa.testing.ledger import Ledger


def _snapshot(exercised: list[str], violations: list[dict[str, object]] | None = None) -> dict:  # type: ignore[type-arg]
    return {
        "described": {"v1": 170, "v2": 196},
        "exercised": {"v1": exercised},
        "violations": violations or [],
        "accepted": ["VKJ-002", "VKJ-002", "VKJ-004"],
    }


def test_a_test_counts_once_towards_every_check_it_covers() -> None:
    ledger = Ledger()

    ledger.record_test(("ACL", "INT"), generated=False)
    ledger.record_test(("ACL",), generated=True)

    assert ledger.executed == 2
    assert ledger.generated == 1
    assert ledger.covered == Counter({"ACL": 2, "INT": 1})


def test_merging_adds_counts_and_unites_what_was_seen() -> None:
    first, second = Ledger(), Ledger()
    first.record_test(("ACL",), generated=False)
    first.absorb_contracts(_snapshot(["GET /tasks/{id}"]))
    second.record_test(("ACL",), generated=True)
    second.absorb_contracts(_snapshot(["GET /tasks/{id}", "PUT /projects"]))

    first.merge(second)

    assert first.executed == 2
    assert first.covered["ACL"] == 2
    assert first.exercised["v1"] == {"GET /tasks/{id}", "PUT /projects"}
    assert first.described == {"v1": 170, "v2": 196}, "descriptions are the same, not additive"
    assert first.accepted == Counter({"VKJ-002": 4, "VKJ-004": 2})


def test_the_wire_form_is_plain_json_and_round_trips() -> None:
    """xdist carries worker output over execnet, which accepts built-in types
    only; JSON-serialisable is the practical proof of that."""
    ledger = Ledger()
    ledger.record_test(("CON", "AUT"), generated=True)
    ledger.absorb_contracts(
        _snapshot(
            ["GET /user"],
            [{"spec": "v1", "operation": "GET /user", "status": 200, "kind": "schema"}],
        )
    )

    wire = json.loads(json.dumps(ledger.to_wire()))

    assert Ledger.from_wire(wire) == ledger


def test_coverage_is_reported_per_api_version() -> None:
    ledger = Ledger()
    ledger.absorb_contracts(_snapshot(["GET /user", "GET /tasks/{id}"]))

    assert ledger.operation_coverage() == {"v1": (2, 170), "v2": (0, 196)}


def test_the_same_violation_seen_many_times_is_listed_once() -> None:
    violation = {"spec": "v1", "operation": "GET /user", "status": 200, "kind": "schema"}
    other = {**violation, "status": 404}
    ledger = Ledger(violations=[violation, dict(violation), other, dict(violation)])

    assert ledger.distinct_violations() == [violation, other]


def test_an_untouched_ledger_is_empty_and_a_used_one_is_not() -> None:
    ledger = Ledger()
    assert ledger.is_empty

    ledger.record_test(("UI",), generated=False)
    assert not ledger.is_empty
