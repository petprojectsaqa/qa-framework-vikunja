"""The rules every product test follows, as a function the plugin can apply.

A product test sits under an area directory, declares the matrix checks it
provides, and names findings and advisories in a shape that resolves to
something real. Kept apart from the plugin so the rules can be read, and
tested, without a pytest session around them.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from vikunja_qa.testing import traceability


@dataclass(frozen=True)
class Declarations:
    """What a test says about itself through its markers."""

    codes: tuple[str, ...] = ()
    findings: tuple[str, ...] = ()
    advisories: tuple[str, ...] = ()
    generated: bool = False

    @classmethod
    def of(cls, item: pytest.Item) -> Declarations:
        """Read from the item and every node above it, so a module's
        `pytestmark` counts exactly as a decorator on the function would."""
        return cls(
            codes=_arguments(item, "covers"),
            findings=_arguments(item, "finding"),
            advisories=_arguments(item, "advisory"),
            generated=item.get_closest_marker("generated") is not None,
        )


def violations(
    placement: traceability.Placement, declared: Declarations, findings_root: Path
) -> list[str]:
    """Everything wrong with how one test is placed and declared."""
    found = []
    if placement.area is None:
        found.append(f"sits directly in tests/{placement.layer}/; move it under an area directory")
    if not declared.codes and not placement.is_harness_test:
        found.append("declares no matrix check; add @pytest.mark.covers(...)")
    for code in declared.codes:
        if code not in traceability.CHECKS:
            found.append(f"covers {code!r}, which the coverage matrix does not define")
    for finding in declared.findings:
        if not traceability.FINDING_ID.match(finding):
            found.append(f"names finding {finding!r}, which is not shaped like VKJ-000")
        elif (
            finding not in traceability.HELD_FINDINGS
            and traceability.finding_folder(finding, findings_root) is None
        ):
            found.append(f"names finding {finding}, which has no folder under docs/findings")
    for advisory in declared.advisories:
        if not traceability.ADVISORY_ID.match(advisory):
            found.append(f"names advisory {advisory!r}, which is neither a CVE nor a GHSA id")
    return found


def _arguments(item: pytest.Item, marker: str) -> tuple[str, ...]:
    values: list[str] = []
    for mark in item.iter_markers(marker):
        values.extend(str(argument) for argument in mark.args)
    return tuple(dict.fromkeys(values))
