"""The coverage matrix as data: codes, priorities, placement and identifiers."""

from __future__ import annotations

from pathlib import Path, PurePosixPath

import pytest

from vikunja_qa.testing import traceability
from vikunja_qa.testing.traceability import Placement

TESTS = PurePosixPath("/repo/tests")


class TestCatalogue:
    def test_every_check_has_a_short_upper_case_code_and_a_known_priority(self) -> None:
        for code, check in traceability.CHECKS.items():
            assert code == check.code
            assert code.isupper(), code
            assert 2 <= len(code) <= 3, code
            assert check.priority in traceability.PRIORITIES, code

    def test_anchor_and_marker_are_the_lower_case_code(self) -> None:
        check = traceability.check("I18")

        assert check.anchor == "i18"
        assert check.marker == "i18"

    def test_an_unknown_code_is_refused_with_the_known_ones_listed(self) -> None:
        with pytest.raises(traceability.UnknownCheckError, match="ACL"):
            traceability.check("NOPE")


class TestSeverity:
    @pytest.mark.parametrize(
        ("codes", "severity"),
        [
            (("ACL",), "critical"),
            (("UI",), "normal"),
            (("DAV",), "minor"),
            (("DAV", "UI", "CVE"), "critical"),
            ((), "normal"),
        ],
    )
    def test_the_most_important_check_decides(self, codes: tuple[str, ...], severity: str) -> None:
        assert traceability.severity_of(codes) == severity


class TestUncovered:
    def test_p0_asks_about_p0_alone(self) -> None:
        covered = {code: 1 for code, check in traceability.CHECKS.items() if check.priority == "P0"}
        covered.pop("SCP")

        missing = traceability.uncovered(covered, down_to="P0")

        assert [check.code for check in missing] == ["SCP"]

    def test_a_lower_priority_includes_everything_above_it(self) -> None:
        missing = {check.code for check in traceability.uncovered({}, down_to="P1")}

        assert "ACL" in missing
        assert "FUN" in missing
        assert "DAV" not in missing

    def test_an_unknown_priority_is_refused(self) -> None:
        with pytest.raises(ValueError, match="P3"):
            traceability.uncovered({}, down_to="P3")


class TestPlacement:
    def test_layer_area_and_module_come_from_the_path(self) -> None:
        placed = traceability.place(TESTS / "api" / "side_effects" / "test_mail.py", TESTS)

        assert placed == Placement(layer="api", area="side_effects", module="test_mail.py")
        assert placed.epic == "API"
        assert placed.feature == "Side effects"
        assert placed.story == "Mail"
        assert placed.is_product_test
        assert not placed.is_harness_test

    def test_a_module_directly_in_a_layer_has_no_area(self) -> None:
        placed = traceability.place(TESTS / "api" / "test_loose.py", TESTS)

        assert placed is not None
        assert placed.area is None

    def test_nested_areas_keep_their_whole_path(self) -> None:
        placed = traceability.place(TESTS / "api" / "framework" / "deep" / "test_x.py", TESTS)

        assert placed is not None
        assert placed.area == "framework/deep"
        assert placed.is_harness_test, "a harness area stays one however deep it goes"

    def test_the_unit_layer_is_not_a_product_layer(self) -> None:
        placed = traceability.place(TESTS / "unit" / "test_waiting.py", TESTS)

        assert placed is not None
        assert not placed.is_product_test

    def test_a_file_outside_the_suite_has_no_placement(self) -> None:
        assert traceability.place(PurePosixPath("/elsewhere/test_x.py"), TESTS) is None

    @pytest.mark.parametrize(
        ("name", "readable"),
        [("side_effects", "Side effects"), ("ui_api_cve", "UI API CVE"), ("db-state", "DB state")],
    )
    def test_names_read_as_words_with_acronyms_in_capitals(self, name: str, readable: str) -> None:
        assert traceability.humanise(name) == readable


class TestIdentifiers:
    @pytest.mark.parametrize("finding", ["VKJ-001", "VKJ-012"])
    def test_finding_ids_have_three_digits(self, finding: str) -> None:
        assert traceability.FINDING_ID.match(finding)

    @pytest.mark.parametrize("finding", ["VKJ-1", "vkj-001", "VKJ-0001", "ABC-001"])
    def test_other_shapes_are_not_findings(self, finding: str) -> None:
        assert not traceability.FINDING_ID.match(finding)

    @pytest.mark.parametrize(
        ("advisory", "url"),
        [
            ("CVE-2026-35601", "https://nvd.nist.gov/vuln/detail/CVE-2026-35601"),
            ("GHSA-2pv8-4c52-mf8j", "https://github.com/advisories/GHSA-2pv8-4c52-mf8j"),
        ],
    )
    def test_advisories_resolve_to_their_public_record(self, advisory: str, url: str) -> None:
        assert traceability.ADVISORY_ID.match(advisory)
        assert traceability.advisory_url(advisory) == url

    @pytest.mark.parametrize("advisory", ["CVE-26-1", "GHSA-xxxx", "cve-2026-35601"])
    def test_malformed_advisories_are_not_accepted(self, advisory: str) -> None:
        assert not traceability.ADVISORY_ID.match(advisory)

    def test_a_finding_resolves_to_its_folder(self, tmp_path: Path) -> None:
        (tmp_path / "VKJ-007-label-update-verb").mkdir()
        (tmp_path / "VKJ-0070-not-this-one.txt").write_text("", encoding="utf-8")

        assert traceability.finding_folder("VKJ-007", tmp_path) == "VKJ-007-label-update-verb"
        assert traceability.finding_folder("VKJ-008", tmp_path) is None
