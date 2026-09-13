"""The documentation, checked against the thing it documents.

Prose rots quietly. A test path in a finding survives a rename as a string
that no longer points anywhere, and the reader who follows it concludes the
evidence was never there. These read the documents and resolve what they
claim, so a rename either updates the docs or fails the build.

No stand, no network: the repository is the only input.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from vikunja_qa.testing import traceability

REPOSITORY = Path(__file__).resolve().parents[2]
DOCS = REPOSITORY / "docs"
FINDINGS = DOCS / "findings"
TESTS = REPOSITORY / "tests"

#: `tests/api/area/test_x.py`, optionally with `::Class::test_name` after it.
TEST_REFERENCE = re.compile(r"tests/[\w/]+\.py(?:::\w+)*")
FINDING_FOLDER = re.compile(r"^VKJ-\d{3}-[a-z0-9-]+$")


def _markdown() -> list[Path]:
    return sorted([*REPOSITORY.glob("*.md"), *DOCS.rglob("*.md")])


def _defined_names(module: Path) -> set[str]:
    tree = ast.parse(module.read_text(encoding="utf-8"))
    return {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }


@pytest.mark.parametrize("document", _markdown(), ids=lambda path: str(path.name))
def test_every_test_a_document_points_at_exists(document: Path) -> None:
    """Where a document names a test, that test is there under that name."""
    unresolved = []
    for reference in TEST_REFERENCE.findall(document.read_text(encoding="utf-8")):
        path, *names = reference.split("::")
        module = REPOSITORY / path
        if not module.is_file():
            unresolved.append(f"{reference} (no such file)")
            continue
        defined = _defined_names(module)
        unresolved += [
            f"{reference} (no {name} in {path})" for name in names if name not in defined
        ]

    assert not unresolved, (
        f"{document.relative_to(REPOSITORY)} points at tests that are not there:\n"
        + "\n".join(unresolved)
    )


@pytest.mark.parametrize("index_name", ["README.md", "README.ru.md"])
def test_every_finding_folder_is_listed_in_the_index(index_name: str) -> None:
    """Both indexes, because a finding added to one language and forgotten
    in the other is exactly the drift that goes unnoticed."""
    index = (FINDINGS / index_name).read_text(encoding="utf-8")
    folders = sorted(path.name for path in FINDINGS.iterdir() if path.is_dir())

    missing = [folder for folder in folders if folder not in index]

    assert not missing, f"findings with no row in docs/findings/{index_name}: {missing}"


@pytest.mark.parametrize("index_name", ["README.md", "README.ru.md"])
def test_every_held_finding_is_named_in_the_index(index_name: str) -> None:
    """A held finding has no folder, so nothing else would notice if its
    row went missing and the numbering quietly grew a gap."""
    index = (FINDINGS / index_name).read_text(encoding="utf-8")

    unlisted = sorted(finding for finding in traceability.HELD_FINDINGS if finding not in index)

    assert not unlisted, f"held findings with no row in docs/findings/{index_name}: {unlisted}"


def test_every_finding_folder_carries_a_report_in_both_languages_and_a_reproduction() -> None:
    """The promise the index makes: two minutes, no trust in the author."""
    incomplete = {}
    for folder in sorted(path for path in FINDINGS.iterdir() if path.is_dir()):
        missing = [
            name
            for name in ("README.md", "README.ru.md", "reproduce.py")
            if not (folder / name).is_file()
        ]
        if missing:
            incomplete[folder.name] = missing

    assert not incomplete, f"findings missing their parts: {incomplete}"


def test_finding_folders_are_named_the_same_way() -> None:
    """`VKJ-000-what-it-is`, because the plugin resolves report links by
    globbing that shape."""
    odd = [
        path.name
        for path in FINDINGS.iterdir()
        if path.is_dir() and not FINDING_FOLDER.match(path.name)
    ]

    assert not odd, f"finding folders that do not follow VKJ-000-name: {odd}"


def test_every_finding_a_test_names_is_either_written_up_or_deliberately_held() -> None:
    """A `finding` marker is a promise of a write-up. The exception is a
    finding held back from publication, which is listed as held instead."""
    named = set()
    for module in TESTS.rglob("test_*.py"):
        named.update(re.findall(r'finding\("(VKJ-\d{3})"\)', module.read_text(encoding="utf-8")))

    unwritten = sorted(
        finding
        for finding in named
        if finding not in traceability.HELD_FINDINGS
        and traceability.finding_folder(finding, FINDINGS) is None
    )

    assert not unwritten, f"tests name findings with no write-up: {unwritten}"


def _matrix_row(matrix_name: str, check: traceability.Check) -> str:
    matrix = (DOCS / matrix_name).read_text(encoding="utf-8")
    anchor = f'<a id="{check.anchor}"></a>'
    rows = [line for line in matrix.splitlines() if anchor in line]
    assert len(rows) == 1, (
        f"{check.code} should have exactly one row carrying {anchor} in {matrix_name}, "
        f"and has {len(rows)}; a report link lands on that anchor"
    )
    return rows[0]


@pytest.mark.parametrize("matrix_name", ["coverage-matrix.md", "coverage-matrix.ru.md"])
@pytest.mark.parametrize("check", traceability.CHECKS.values(), ids=lambda check: check.code)
def test_every_check_has_a_row_in_both_matrices(
    check: traceability.Check, matrix_name: str
) -> None:
    """The connection `traceability` said it had, and did not.

    That module's docstring has always claimed a test confirms every check
    has an anchor in both language versions of the matrix. None did. So a
    new check, or a renamed heading, produced a dead `tms` link in every
    Allure report with nothing to catch it.
    """
    row = _matrix_row(matrix_name, check)

    assert check.priority in row, (
        f"{check.code} is {check.priority} in the code and the {matrix_name} row disagrees: {row}"
    )


@pytest.mark.parametrize("check", traceability.CHECKS.values(), ids=lambda check: check.code)
def test_every_check_reads_the_same_in_the_code_and_in_the_matrix(
    check: traceability.Check,
) -> None:
    """The English matrix only: the Russian one translates the titles, and
    holding a translation to an English string would be a rule against
    translating.

    Two rows had already drifted when this was written, so the terminal
    table printed one wording while the report linked to a row saying
    another.
    """
    row = _matrix_row("coverage-matrix.md", check)

    assert check.title in row, (
        f"{check.code} reads {check.title!r} in the code and the matrix row says: {row}"
    )


def test_the_held_findings_are_not_quietly_published() -> None:
    """The other direction: a finding marked held here must have no folder,
    or the reason it was held has been lost."""
    published = sorted(
        finding
        for finding in traceability.HELD_FINDINGS
        if traceability.finding_folder(finding, FINDINGS) is not None
    )

    assert not published, (
        f"findings listed as held from publication have folders in the repository: {published}"
    )
