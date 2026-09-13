"""Tests for the contract machinery itself.

No stand required: these run in milliseconds and go first in the
pipeline, so a mistake in the framework is caught before anything slow
starts. A test tool with no tests of its own is not one.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from vikunja_qa.contracts.baseline import KNOWN, Baseline, Deviation
from vikunja_qa.contracts.spec import SpecIndex, resolvable
from vikunja_qa.contracts.validator import (
    ContractValidator,
    ContractViolationError,
    Mode,
    Violation,
)
from vikunja_qa.testing import traceability
from vikunja_qa.transport.response import ApiResponse

SWAGGER_2 = {
    "swagger": "2.0",
    "basePath": "/api/v1",
    "paths": {
        "/tasks/{id}": {
            "get": {
                "operationId": "getTask",
                "responses": {"200": {"schema": {"$ref": "#/definitions/Task"}}},
            }
        },
        "/tasks/bulk": {"post": {"operationId": "bulkTasks", "responses": {"200": {"schema": {}}}}},
        "/projects/{project}/views/{view}": {
            "get": {"operationId": "getView", "responses": {"default": {"schema": {}}}}
        },
        "/users": {"get": {"operationId": "listUsers", "responses": {"4XX": {"schema": {}}}}},
        # A status declared with no schema at all, which is how Swagger 2.0
        # spells 204 No Content and how OpenAPI spells a binary download.
        # Declared and unschemaed is a third state, distinct from both
        # "declared with a schema" and "not declared".
        "/labels/{id}": {
            "delete": {
                "operationId": "deleteLabel",
                "responses": {"204": {"description": "deleted"}, "403": {"schema": {}}},
            }
        },
    },
    "definitions": {"Task": {"type": "object", "properties": {"id": {"type": "integer"}}}},
}


@pytest.fixture
def spec() -> SpecIndex:
    return SpecIndex(SWAGGER_2, label="v1", base_path="/api/v1")


class TestPathMatching:
    def test_matches_a_parameterised_path(self, spec: SpecIndex) -> None:
        operation = spec.match("GET", "http://host/api/v1/tasks/42")
        assert operation is not None
        assert operation.path_template == "/tasks/{id}"

    def test_a_literal_segment_beats_a_parameter(self, spec: SpecIndex) -> None:
        """`/tasks/bulk` and `/tasks/{id}` both fit the same shape; the
        concrete one has to win regardless of dictionary order."""
        operation = spec.match("POST", "http://host/api/v1/tasks/bulk")
        assert operation is not None
        assert operation.path_template == "/tasks/bulk"

    def test_matches_several_parameters(self, spec: SpecIndex) -> None:
        operation = spec.match("GET", "http://host/api/v1/projects/7/views/3")
        assert operation is not None
        assert operation.path_template == "/projects/{project}/views/{view}"

    def test_no_match_for_a_different_segment_count(self, spec: SpecIndex) -> None:
        assert spec.match("GET", "http://host/api/v1/tasks/42/comments") is None

    def test_no_match_for_a_different_method(self, spec: SpecIndex) -> None:
        assert spec.match("DELETE", "http://host/api/v1/tasks/42") is None

    def test_query_strings_are_ignored(self, spec: SpecIndex) -> None:
        operation = spec.match("GET", "http://host/api/v1/tasks/42?expand=labels")
        assert operation is not None


class TestStatusLookup:
    def test_exact_status(self, spec: SpecIndex) -> None:
        operation = spec.operation("GET", "/tasks/{id}")
        assert operation is not None
        assert operation.schema_for(200) == {"$ref": "#/definitions/Task"}

    def test_falls_back_to_a_range(self, spec: SpecIndex) -> None:
        operation = spec.operation("GET", "/users")
        assert operation is not None
        assert operation.schema_for(404) is not None, "4XX should cover 404"

    def test_falls_back_to_default(self, spec: SpecIndex) -> None:
        operation = spec.operation("GET", "/projects/{project}/views/{view}")
        assert operation is not None
        assert operation.schema_for(418) is not None

    def test_undeclared_status_returns_nothing(self, spec: SpecIndex) -> None:
        operation = spec.operation("GET", "/tasks/{id}")
        assert operation is not None
        assert operation.schema_for(401) is None


class TestDeclaredButUnschemaed:
    """ "The description mentions this status" and "the description gives a
    schema for its body" are different questions.

    Conflating them made the suite report a description as wrong about a
    status it had got right, and then, having dropped the status, fall
    through to the operation's catch-all — which on v2 is the error model,
    so a successful download was one step from being reported as failing to
    look like an error.

    Asserted here because nothing did. A `declares` that always answered
    yes passed all 253 of the suite's own tests, which is to say the gate on
    the whole undeclared-status check was unguarded.
    """

    def test_a_status_declared_with_no_schema_is_still_declared(self, spec: SpecIndex) -> None:
        operation = spec.operation("DELETE", "/labels/{id}")
        assert operation is not None

        assert operation.declares(204) is True
        assert operation.schema_for(204) is None, (
            "a 204 declared with no body must yield no schema to validate against"
        )

    def test_a_status_declared_with_a_schema_yields_it(self, spec: SpecIndex) -> None:
        operation = spec.operation("DELETE", "/labels/{id}")
        assert operation is not None

        assert operation.declares(403) is True
        assert operation.schema_for(403) is not None

    def test_a_status_the_description_never_mentions_is_not_declared(self, spec: SpecIndex) -> None:
        operation = spec.operation("DELETE", "/labels/{id}")
        assert operation is not None

        assert operation.declares(500) is False
        assert operation.schema_for(500) is None

    def test_a_range_and_a_catch_all_both_count_as_declaring(self, spec: SpecIndex) -> None:
        by_range = spec.operation("GET", "/users")
        catch_all = spec.operation("GET", "/projects/{project}/views/{view}")
        assert by_range is not None
        assert catch_all is not None

        assert by_range.declares(404) is True, "a 4XX entry declares 404"
        assert catch_all.declares(418) is True, "a default entry declares anything"

    def test_the_validator_reports_only_the_status_that_is_absent(self, spec: SpecIndex) -> None:
        """The behaviour, through the hook, since that is what matters.

        The 204 is declared without a body and must pass in silence. The 500
        is not declared at all and must be reported. One response each, so
        neither result can be borrowed from the other.
        """
        validator = ContractValidator([spec], mode=Mode.COLLECT, baseline=Baseline(()))

        validator(_labels_response(204))
        assert validator.violations == [], (
            "a 204 the description declares without a body was reported as a deviation"
        )

        validator(_labels_response(500))
        kinds = [violation.kind for violation in validator.violations]
        assert kinds == ["undeclared status"], (
            f"a status the description never mentions went unreported: {kinds}"
        )
        assert "204, 403" in validator.violations[0].detail, (
            "the report should list what the operation does declare: "
            f"{validator.violations[0].detail!r}"
        )


def _labels_response(status: int) -> ApiResponse:
    return ApiResponse(
        method="DELETE",
        url="http://host/api/v1/labels/7",
        status=status,
        headers={},
        body="",
        elapsed_ms=1.0,
        parsed=False,
    )


def test_resolvable_carries_shared_definitions() -> None:
    """Response schemas point into the root document, so the containers
    have to travel with them for a plain validator to resolve them."""
    composed = resolvable({"$ref": "#/definitions/Task"}, SWAGGER_2)
    assert "definitions" in composed
    assert composed["definitions"]["Task"]["type"] == "object"


class TestErrorShapes:
    """Both API versions must surface the same domain code even though
    they answer in different formats."""

    def test_reads_the_flat_v1_shape(self) -> None:
        response = _response({"code": 4004, "message": "Project does not exist."})
        assert response.error_code == 4004
        assert response.error_message == "Project does not exist."

    def test_reads_the_rfc_9457_shape(self) -> None:
        response = _response(
            {"title": "Not Found", "status": 404, "detail": "no such project", "code": 4004}
        )
        assert response.error_code == 4004
        assert response.error_message == "no such project"

    def test_absent_code_is_none(self) -> None:
        assert _response({"message": "nope"}).error_code is None

    def test_non_json_body_is_survivable(self) -> None:
        assert _response("plain text").error_code is None


class TestBaseline:
    def test_accepts_a_known_deviation(self) -> None:
        baseline = Baseline(
            (
                Deviation(
                    finding="VKJ-002",
                    spec="v1",
                    kind="schema mismatch",
                    detail_pattern=r"None is not of type 'array'",
                    reason="documented",
                ),
            )
        )
        known = baseline.known(
            Violation(
                "v1",
                "GET /tasks",
                200,
                "schema mismatch",
                "labels: None is not of type 'array'",
                "u",
            )
        )
        assert known is not None
        assert known.finding == "VKJ-002"

    def test_does_not_leak_across_specs(self) -> None:
        baseline = Baseline(
            (Deviation(finding="X", spec="v1", kind="schema mismatch", reason="r"),)
        )
        assert (
            baseline.known(Violation("v2", "GET /tasks", 200, "schema mismatch", "anything", "u"))
            is None
        )

    def test_an_unrelated_mismatch_stays_new(self) -> None:
        """The point of the baseline: it must not swallow the next real
        finding while absorbing the ones already written up."""
        baseline = Baseline(
            (
                Deviation(
                    finding="VKJ-002",
                    spec="v1",
                    kind="schema mismatch",
                    detail_pattern=r"None is not of type",
                    reason="documented",
                ),
            )
        )
        new, accepted = baseline.split(
            [
                Violation(
                    "v1",
                    "GET /tasks",
                    200,
                    "schema mismatch",
                    "labels: None is not of type 'array'",
                    "u",
                ),
                Violation(
                    "v1",
                    "GET /tasks",
                    200,
                    "schema mismatch",
                    "id: 'seven' is not of type 'integer'",
                    "u",
                ),
            ]
        )
        assert len(accepted) == 1
        assert len(new) == 1
        assert "seven" in new[0].detail

    def test_every_entry_names_a_finding(self) -> None:
        """No entry may exist just to quieten the suite."""
        assert KNOWN, "an empty baseline would make every rule below vacuous"
        for deviation in KNOWN:
            assert deviation.finding.startswith("VKJ-"), deviation
            assert deviation.reason.strip(), deviation

    def test_every_entry_resolves_to_a_finding_that_exists(self) -> None:
        """The rule the baseline states about itself, checked.

        A prefix test passes for `VKJ-999`. What the module promises is that
        each entry names a finding in docs/findings, so each one is resolved
        to its folder, or to the list of findings deliberately held back.
        """
        findings_root = Path(__file__).resolve().parents[2] / "docs" / "findings"
        unresolved = [
            deviation.finding
            for deviation in KNOWN
            if deviation.finding not in traceability.HELD_FINDINGS
            and traceability.finding_folder(deviation.finding, findings_root) is None
        ]
        assert not unresolved, f"baseline entries naming no finding: {sorted(set(unresolved))}"

    def test_no_entry_switches_a_whole_check_off(self) -> None:
        """The one rule that keeps the baseline a baseline.

        An entry matching any spec, any operation, any status and any detail
        does not record a deviation, it disables a kind of check — and for a
        year one of them did exactly that, accepting every undeclared status
        on both descriptions, an unexpected 500 among them.
        """
        blanket = [deviation for deviation in KNOWN if deviation.is_blanket]
        assert not blanket, (
            "these entries accept a whole kind of violation rather than a known one: "
            + ", ".join(f"{d.finding}/{d.kind}" for d in blanket)
        )

    def test_the_baseline_only_shrinks(self) -> None:
        """Pinned, because "it only ever shrinks" is a promise nothing else
        enforces.

        Lower this number when an entry goes. Raising it means a deviation
        was accepted rather than reported, and that should take a decision
        and a line in a diff rather than happening by itself.

        Counted in entries, so the number can go up when one entry is split
        into several narrower ones — which is what happened when the single
        blanket entry for undeclared statuses became nine that each name a
        status. More entries, less accepted.
        """
        assert len(KNOWN) <= 16, f"the baseline has grown to {len(KNOWN)} entries"


class TestAKnownDeviationNeverHidesAnUnknownOne:
    """The one thing the baseline must never do, checked the way it happens.

    Driven through `validator(response)` — the transport hook itself — not
    through the pieces underneath it. That matters more than it looks. The
    version of this test that called `_validate` directly and then sorted
    the results with `Baseline.split` could not observe the defect it was
    written for, because the masking had moved one layer up: the per-response
    mismatch budget was counted over every mismatch, so a body carrying a
    documented deviation on each of its elements spent the whole budget
    before it reached an undocumented one further down. Production never
    calls `split`, and that is exactly why this now does not either.
    """

    DOCUMENT = {
        "swagger": "2.0",
        "basePath": "/api/v1",
        "paths": {
            "/tasks": {
                "get": {
                    "operationId": "listTasks",
                    "responses": {
                        "200": {
                            "schema": {
                                "type": "array",
                                "items": {"$ref": "#/definitions/Task"},
                            }
                        }
                    },
                }
            }
        },
        "definitions": {
            "Task": {
                "type": "object",
                "properties": {
                    "labels": {"type": "array"},
                    "assignees": {"type": "array"},
                    "id": {"type": "integer"},
                },
            }
        },
    }

    #: Stands for VKJ-002: a nullability the product has, written up already.
    KNOWN = Deviation(
        finding="VKJ-002",
        spec="v1",
        kind="schema mismatch",
        detail_pattern=r"(labels|assignees): None is not of type 'array'",
        reason="documented",
    )

    def _validator(self) -> ContractValidator:
        spec = SpecIndex(self.DOCUMENT, label="v1", base_path="/api/v1")
        return ContractValidator([spec], mode=Mode.COLLECT, baseline=Baseline((self.KNOWN,)))

    @staticmethod
    def _listing(length: int, *, unknown_at: int | None = None) -> list[dict[str, object]]:
        """A task listing where every element carries the known deviation,
        and one element optionally carries something nobody has seen."""
        tasks: list[dict[str, object]] = []
        for index in range(length):
            tasks.append(
                {
                    "labels": None,
                    "assignees": None,
                    "id": "seven" if index == unknown_at else index,
                }
            )
        return tasks

    def test_one_violation_per_mismatch_rather_than_one_per_response(self) -> None:
        validator = self._validator()

        validator(_listing_of(self._listing(1, unknown_at=0)))

        assert len(validator.accepted) == 2, "the two nullabilities were merged"
        assert [violation.detail for violation, _ in validator.accepted] == [
            "0/assignees: None is not of type 'array'",
            "0/labels: None is not of type 'array'",
        ]
        assert len(validator.violations) == 1, "the unknown mismatch has to survive on its own"
        assert "0/id" in validator.violations[0].detail

    def test_a_deviation_on_every_element_does_not_spend_the_budget(self) -> None:
        """Twenty elements, two documented mismatches each, and one unknown
        mismatch buried at element fifteen. Forty known mismatches come
        first, so a budget counted over all of them is long gone by then."""
        validator = self._validator()

        validator(_listing_of(self._listing(20, unknown_at=15)))

        assert len(validator.accepted) == 40, "every element's known deviation is still recorded"
        assert [violation.detail for violation in validator.violations] == [
            "15/id: 'seven' is not of type 'integer'"
        ]

    def test_truncation_is_never_silent(self) -> None:
        """The budget still applies to new mismatches, and says when it bit."""
        validator = self._validator()
        many = [{"labels": None, "assignees": None, "id": "seven"} for _ in range(30)]

        validator(_listing_of(many))

        details = [violation.detail for violation in validator.violations]
        assert len(details) == ContractValidator.NEW_MISMATCHES_PER_RESPONSE + 1
        assert details[-1] == "and 20 further new mismatches, not listed"

    def test_strict_mode_fails_on_the_unknown_one_however_deep_it_sits(self) -> None:
        validator = self._validator()
        validator._mode = Mode.STRICT

        with pytest.raises(ContractViolationError, match="15/id"):
            validator(_listing_of(self._listing(20, unknown_at=15)))


def _listing_of(body: object) -> ApiResponse:
    return ApiResponse(
        method="GET",
        url="http://host/api/v1/tasks",
        status=200,
        headers={},
        body=body,
        elapsed_ms=1.0,
    )


def _response(body: object) -> ApiResponse:
    return ApiResponse(
        method="GET",
        url="http://host/api/v1/x",
        status=404,
        headers={},
        body=body,
        elapsed_ms=1.0,
    )


class TestWhatTheSuiteSends:
    """The other half of a contract.

    A response check says the product kept its word. Nothing said the
    caller asked for something the description admits — so a client that
    drifted from the description, a field renamed or a type changed, went
    on sending the wrong thing and the suite went on calling it a pass.

    It fails in two directions and both are worth knowing. Usually it is
    the suite that drifted. Sometimes it is the description omitting
    something the product happily accepts, which is a defect in the
    description of exactly the kind this project collects.
    """

    DOCUMENT = {
        "swagger": "2.0",
        "basePath": "/api/v1",
        "paths": {
            "/projects/{id}/users": {
                "put": {
                    "operationId": "addUser",
                    "parameters": [
                        {
                            "in": "body",
                            "name": "grant",
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "username": {"type": "string"},
                                    "permission": {"type": "integer", "enum": [0, 1, 2]},
                                },
                            },
                        }
                    ],
                    "responses": {"200": {"schema": {}}},
                }
            }
        },
    }

    def _validator(self) -> ContractValidator:
        spec = SpecIndex(self.DOCUMENT, label="v1", base_path="/api/v1")
        return ContractValidator([spec], mode=Mode.COLLECT, baseline=Baseline(()))

    @staticmethod
    def _sent(body: object) -> ApiResponse:
        return ApiResponse(
            method="PUT",
            url="http://host/api/v1/projects/7/users",
            status=200,
            headers={},
            body={},
            elapsed_ms=1.0,
            request_body=body,
        )

    def test_a_body_the_description_admits_passes(self) -> None:
        validator = self._validator()

        validator(self._sent({"username": "someone", "permission": 1}))

        assert validator.violations == []

    def test_a_body_the_description_forbids_is_reported(self) -> None:
        validator = self._validator()

        validator(self._sent({"username": "someone", "permission": "1"}))

        kinds = [violation.kind for violation in validator.violations]
        assert "request body mismatch" in kinds, f"nothing was said about the body: {kinds}"

    def test_the_check_can_be_stood_down_for_a_deliberate_malformation(self) -> None:
        """Without this a test whose subject is a malformed body reports
        itself, which is the surest way to have the whole check switched
        off instead."""
        validator = self._validator()

        with validator.ignoring_requests():
            validator(self._sent({"permission": [1]}))

        assert validator.violations == []

    def test_standing_it_down_leaves_the_answer_checked(self) -> None:
        """The narrowness is the point: an endpoint handed nonsense still
        owes its caller a response in the shape it promised."""
        validator = self._validator()

        with validator.ignoring_requests():
            undocumented = self._sent({"permission": [1]})
            validator(
                ApiResponse(
                    method="DELETE",
                    url=undocumented.url,
                    status=200,
                    headers={},
                    body={},
                    elapsed_ms=1.0,
                )
            )

        assert [violation.kind for violation in validator.violations] == ["undocumented operation"]
