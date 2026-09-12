"""Tests for the contract machinery itself.

No stand required: these run in milliseconds and go first in the
pipeline, so a mistake in the framework is caught before anything slow
starts. A test tool with no tests of its own is not one.
"""

from __future__ import annotations

import pytest

from vikunja_qa.contracts.baseline import Baseline, Deviation
from vikunja_qa.contracts.spec import SpecIndex, resolvable
from vikunja_qa.contracts.validator import Violation
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
        for deviation in Baseline()._deviations:
            assert deviation.finding.startswith("VKJ-"), deviation
            assert deviation.reason.strip(), deviation


def _response(body: object) -> ApiResponse:
    return ApiResponse(
        method="GET",
        url="http://host/api/v1/x",
        status=404,
        headers={},
        body=body,
        elapsed_ms=1.0,
    )
