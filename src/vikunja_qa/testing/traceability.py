"""The coverage matrix, as data the suite can check itself against.

`docs/coverage-matrix.md` names every kind of check this suite performs and
gives each a priority. That document and the tests used to be connected
only by good intentions. Here the connection is code: every product test
declares which check it provides with `@pytest.mark.covers("ACL")`, the
plugin turns that into report labels and links, and a test in the unit
layer confirms every code below has an anchor in both language versions
of the matrix. A code nobody can find, or a test that covers nothing, fails
collection.

Everything in this module is a pure function of its input, so the unit
layer can test it without a stand, a browser or a network.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePath

# --- the catalogue ----------------------------------------------------------


@dataclass(frozen=True)
class Check:
    """One kind of check from the coverage matrix."""

    code: str
    title: str
    priority: str

    @property
    def anchor(self) -> str:
        """The `<a id>` this check carries in both matrix documents."""
        return self.code.lower()

    @property
    def marker(self) -> str:
        """The marker a covering test receives, so `pytest -m acl` selects
        every access matrix test without anyone writing it twice."""
        return self.code.lower()


#: Every check type the matrix defines, with the priority it assigns.
CHECKS: dict[str, Check] = {
    check.code: check
    for check in (
        Check("CON", "Responses match their contract", "P0"),
        Check("AUT", "Every operation demands a credential", "P0"),
        Check("ERR", "Domain error codes are preserved", "P0"),
        Check("SCP", "API token scopes hold", "P0"),
        Check("ACL", "Access matrix", "P0"),
        Check("INT", "Data integrity", "P0"),
        Check("CVE", "Regressions for published vulnerabilities", "P0"),
        Check("FUN", "Business rules", "P1"),
        Check("NEG", "Boundaries and invalid input", "P1"),
        Check("ASY", "Asynchronous side effects", "P1"),
        Check("XVR", "Consistency across API versions", "P1"),
        Check("UI", "Behaviour only a browser can check", "P1"),
        Check("CNC", "Concurrency and idempotency", "P2"),
        Check("I18", "Languages, time zones and formats", "P2"),
        Check("DAV", "Calendar protocol", "P2"),
        Check("RES", "Behaviour when a dependency fails", "P2"),
    )
}

#: Matrix priorities, most important first.
PRIORITIES = ("P0", "P1", "P2")

#: How a matrix priority reads as an Allure severity.
SEVERITY_BY_PRIORITY: dict[str, str] = {"P0": "critical", "P1": "normal", "P2": "minor"}


class UnknownCheckError(ValueError):
    pass


def check(code: str) -> Check:
    try:
        return CHECKS[code]
    except KeyError:
        known = ", ".join(sorted(CHECKS))
        raise UnknownCheckError(
            f"{code!r} is not a check the matrix defines; known: {known}"
        ) from None


def severity_of(codes: tuple[str, ...]) -> str:
    """The severity a test earns from the most important check it covers.

    A test covering nothing, such as a harness check, gets Allure's default.
    """
    priorities = {check(code).priority for code in codes}
    for priority in PRIORITIES:
        if priority in priorities:
            return SEVERITY_BY_PRIORITY[priority]
    return "normal"


def uncovered(covered: Mapping[str, int], *, down_to: str) -> list[Check]:
    """Checks at `down_to` priority or more important that no test ran for.

    `down_to="P0"` asks about P0 alone; `"P1"` about P0 and P1 together.
    """
    if down_to not in PRIORITIES:
        raise ValueError(f"{down_to!r} is not a matrix priority; known: {', '.join(PRIORITIES)}")
    considered = PRIORITIES[: PRIORITIES.index(down_to) + 1]
    return [
        check
        for check in CHECKS.values()
        if check.priority in considered and covered.get(check.code, 0) == 0
    ]


# --- findings and advisories ------------------------------------------------

FINDING_ID = re.compile(r"^VKJ-\d{3}$")
ADVISORY_ID = re.compile(r"^(CVE-\d{4}-\d{4,}|GHSA(-[0-9a-z]{4}){3})$")

#: Findings written up but deliberately kept out of the repository until
#: the product's maintainers have seen them. Referencing one is valid; it
#: simply has no folder to link to.
HELD_FINDINGS = frozenset({"VKJ-006", "VKJ-014"})


def finding_folder(finding_id: str, findings_root: Path) -> str | None:
    """The folder a finding lives in, such as `VKJ-007-label-update-verb`."""
    matches = sorted(p.name for p in findings_root.glob(f"{finding_id}-*") if p.is_dir())
    return matches[0] if matches else None


def advisory_url(advisory_id: str) -> str:
    if advisory_id.startswith("GHSA"):
        return f"https://github.com/advisories/{advisory_id}"
    return f"https://nvd.nist.gov/vuln/detail/{advisory_id}"


# --- where a test sits ------------------------------------------------------

#: The execution layers that hold product tests, and how they read in a report.
PRODUCT_LAYERS: dict[str, str] = {"api": "API", "ui": "UI", "resilience": "Resilience"}

#: Areas that prove the harness rather than the product. Their tests are
#: labelled like any other but are not required to cover a matrix check.
HARNESS_AREAS = frozenset({"framework"})


@dataclass(frozen=True)
class Placement:
    """Where a test file sits: `tests/<layer>/<area>/<module>`."""

    layer: str
    area: str | None
    module: str

    @property
    def is_product_test(self) -> bool:
        return self.layer in PRODUCT_LAYERS

    @property
    def is_harness_test(self) -> bool:
        return self.area is not None and self.area.split("/")[0] in HARNESS_AREAS

    @property
    def epic(self) -> str:
        return PRODUCT_LAYERS.get(self.layer, self.layer.title())

    @property
    def feature(self) -> str | None:
        return humanise(self.area) if self.area else None

    @property
    def story(self) -> str:
        return humanise(self.module.removeprefix("test_").removesuffix(".py"))


def place(test_file: PurePath, tests_root: PurePath) -> Placement | None:
    """Locate a test file within the suite, or None if it sits outside it."""
    try:
        parts = test_file.relative_to(tests_root).parts
    except ValueError:
        return None
    if len(parts) == 2:
        return Placement(layer=parts[0], area=None, module=parts[1])
    if len(parts) == 3:
        return Placement(layer=parts[0], area=parts[1], module=parts[2])
    if len(parts) > 3:
        return Placement(layer=parts[0], area="/".join(parts[1:-1]), module=parts[-1])
    return None


def humanise(name: str) -> str:
    """`side_effects` reads as `Side effects`; acronyms stay in capitals."""
    words = name.replace("-", "_").split("_")
    rendered = [word.upper() if word.lower() in _ACRONYMS else word for word in words]
    text = " ".join(rendered)
    return text[:1].upper() + text[1:]


_ACRONYMS = frozenset({"api", "ui", "cve", "id", "url", "db"})
