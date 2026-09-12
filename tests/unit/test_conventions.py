"""The rules a product test is held to, applied without a pytest session."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from _pytest.mark.structures import Mark

from vikunja_qa.testing import conventions, traceability
from vikunja_qa.testing.conventions import Declarations
from vikunja_qa.testing.traceability import Placement

PRODUCT = Placement(layer="api", area="authorization", module="test_x.py")
HARNESS = Placement(layer="api", area="framework", module="test_x.py")
LOOSE = Placement(layer="api", area=None, module="test_x.py")


@pytest.fixture
def findings(tmp_path: Path) -> Path:
    (tmp_path / "VKJ-007-label-update-verb").mkdir()
    return tmp_path


def test_a_well_declared_product_test_has_no_violations(findings: Path) -> None:
    declared = Declarations(
        codes=("ACL",), findings=("VKJ-007",), advisories=("CVE-2026-35601", "GHSA-2pv8-4c52-mf8j")
    )

    assert conventions.violations(PRODUCT, declared, findings) == []


def test_a_product_test_must_cover_a_check(findings: Path) -> None:
    found = conventions.violations(PRODUCT, Declarations(), findings)

    assert found == ["declares no matrix check; add @pytest.mark.covers(...)"]


def test_a_harness_test_may_cover_nothing(findings: Path) -> None:
    assert conventions.violations(HARNESS, Declarations(), findings) == []


def test_a_test_outside_any_area_is_told_where_to_go(findings: Path) -> None:
    found = conventions.violations(LOOSE, Declarations(codes=("ACL",)), findings)

    assert found == ["sits directly in tests/api/; move it under an area directory"]


@pytest.mark.parametrize(
    ("declared", "complaint"),
    [
        (Declarations(codes=("NOPE",)), "covers 'NOPE'"),
        (Declarations(codes=("ACL",), findings=("VKJ-7",)), "not shaped like VKJ-000"),
        (Declarations(codes=("ACL",), findings=("VKJ-999",)), "no folder under docs/findings"),
        (Declarations(codes=("ACL",), advisories=("CVE-bad",)), "neither a CVE nor a GHSA"),
    ],
)
def test_names_that_resolve_to_nothing_are_refused(
    findings: Path, declared: Declarations, complaint: str
) -> None:
    found = conventions.violations(PRODUCT, declared, findings)

    assert len(found) == 1
    assert complaint in found[0]


def test_a_held_finding_needs_no_folder(findings: Path) -> None:
    (held,) = traceability.HELD_FINDINGS

    assert (
        conventions.violations(PRODUCT, Declarations(codes=("ACL",), findings=(held,)), findings)
        == []
    )


class FakeItem:
    """Just the two marker lookups `Declarations.of` relies on, the way a
    pytest item answers them: closest node first, then its parents."""

    def __init__(self, *marks: Mark) -> None:
        self._marks = marks

    def iter_markers(self, name: str) -> Iterator[Mark]:
        return (mark for mark in self._marks if mark.name == name)

    def get_closest_marker(self, name: str) -> Mark | None:
        return next(self.iter_markers(name), None)


def test_declarations_gather_every_level_without_repeats() -> None:
    item = FakeItem(
        pytest.mark.covers("ACL", "INT").mark,
        pytest.mark.covers("ACL").mark,
        pytest.mark.finding("VKJ-007").mark,
        pytest.mark.generated.mark,
    )

    declared = Declarations.of(item)  # type: ignore[arg-type]

    assert declared == Declarations(codes=("ACL", "INT"), findings=("VKJ-007",), generated=True)
