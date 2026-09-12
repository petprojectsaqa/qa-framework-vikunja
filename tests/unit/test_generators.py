"""The logic that turns what the product publishes into test cases.

Both generated families stand or fall on this: a generator that silently
drops an area or calls something destructive would be worse than none.
Tested here against crafted input, so every edge is deliberate.
"""

from __future__ import annotations

from vikunja_qa.contracts.scopes import cases_for, parse_routes
from vikunja_qa.contracts.spec import SpecIndex
from vikunja_qa.contracts.sweep import PUBLIC, calls_for, concrete_path, unused_public_entries

CATALOGUE = {
    "labels": {
        "read_all": {"path": "/api/v1/labels", "method": "GET"},
        "create": {"path": "/api/v1/labels", "method": "PUT"},
        "update": {"path": "/api/v1/labels/:label", "method": "POST"},
    },
    "webhooks": {
        "create": {"path": "/api/v1/projects/:project/webhooks", "method": "PUT"},
    },
    "test": {
        "all": {"path": "/api/v1/test/all", "method": "DELETE"},
    },
}


class TestScopeCases:
    def test_the_granted_action_is_a_read(self) -> None:
        """Proving a token can do something must not create anything."""
        (labels,) = [case for case in cases_for(CATALOGUE) if case.area == "labels"]

        assert labels.granted.name == "read_all"
        assert {action.name for action in labels.denied} == {"create", "update"}

    def test_an_area_without_a_read_is_left_out(self) -> None:
        """Granting `create` to prove a scope works would leave data behind."""
        assert all(case.area != "webhooks" for case in cases_for(CATALOGUE))

    def test_the_table_emptying_area_is_never_generated(self) -> None:
        """It would destroy the stand out from under the run."""
        assert "test" not in parse_routes(CATALOGUE)

    def test_every_path_parameter_is_filled(self) -> None:
        for case in cases_for(CATALOGUE):
            for action in (case.granted, *case.denied):
                assert ":" not in action.concrete_path, action

    def test_a_malformed_catalogue_yields_nothing_rather_than_crashing(self) -> None:
        assert cases_for(["not", "a", "mapping"]) == []


def _spec(paths: dict[str, dict[str, dict[str, object]]]) -> SpecIndex:
    return SpecIndex({"swagger": "2.0", "paths": paths}, label="v1", base_path="/api/v1")


class TestSweepCalls:
    def test_the_test_support_api_is_never_called(self) -> None:
        spec = _spec(
            {
                "/test/all": {"delete": {"responses": {}}},
                "/test/{table}": {"patch": {"responses": {}}},
                "/tasks/{id}": {"get": {"responses": {}}},
            }
        )

        paths = {call.path for call in calls_for(spec)}

        assert paths == {"/tasks/999999999"}

    def test_identifiers_are_filled_with_values_that_match_nothing(self) -> None:
        assert (
            concrete_path("/projects/{project}/tasks/{id}") == "/projects/999999999/tasks/999999999"
        )

    def test_named_parameters_get_plausible_values(self) -> None:
        assert concrete_path("/{username}/avatar") == "/nobody999/avatar"

    def test_public_operations_are_flagged_with_their_reason(self) -> None:
        spec = _spec({"/login": {"post": {"responses": {}}}})

        (call,) = calls_for(spec)

        assert call.public
        assert call.reason == PUBLIC["POST /login"]

    def test_an_allowlist_entry_matching_nothing_is_reported(self) -> None:
        spec = _spec({"/login": {"post": {"responses": {}}}})

        stale = unused_public_entries([spec])

        assert "POST /login" not in stale
        assert "GET /health" in stale
