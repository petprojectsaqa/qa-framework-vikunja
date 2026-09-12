"""Pairing the two descriptions so the same failure can be asked of both.

The product carries a numeric domain error code, and clients key their
translations off it. v1 returns it as a `code` field. v2 renders errors as
RFC 9457 and carries the same value across, because otherwise every v2
client reads zero.

The invariant, then: where v1 names a failure with a domain code, v2 has
to name it with the same one. Any error path that bypasses the translation
shows up as a missing or different code.

The pairs are computed, not listed. The two versions describe the same
operation under different parameter names, `/projects/{projectID}/users/{userID}`
against `/projects/{project}/users/{user}`, so matching on the literal
template finds barely half of what the versions actually share. Matching on
the shape of the path finds the rest.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from vikunja_qa.contracts.spec import Operation, SpecIndex
from vikunja_qa.contracts.sweep import concrete_path, is_callable

_PLACEHOLDER = re.compile(r"\{[^}]+\}")

#: Only a read or a delete, and only of an identifier that cannot exist.
#: Both are safe whichever version answers: there is nothing there to
#: change. Creating or updating to provoke an error would need a body per
#: operation, which is the hand-written work this family exists to avoid.
SAFE_VERBS = ("GET", "DELETE")


def shape(template: str) -> str:
    """`/projects/{projectID}/users/{userID}` becomes `/projects/{}/users/{}`."""
    return _PLACEHOLDER.sub("{}", template)


@dataclass(frozen=True)
class ErrorCase:
    """One operation both versions describe, and how to make each fail."""

    method: str
    operation: str
    v1_path: str
    v2_path: str

    @property
    def id(self) -> str:
        return f"{self.method}-{self.operation.lstrip('/').replace('/', '-')}"


def _paired(specs: list[SpecIndex]) -> dict[tuple[str, str], dict[str, Operation]]:
    found: dict[tuple[str, str], dict[str, Operation]] = {}
    for spec in specs:
        for operation in spec.operations:
            key = (operation.method, shape(operation.path_template))
            found.setdefault(key, {})[spec.label] = operation
    return found


def absent_object_cases(specs: list[SpecIndex]) -> list[ErrorCase]:
    """Every shared operation that can be asked about something absent.

    One case per operation, not per version: the point is the comparison.
    """
    cases = []
    for (method, path_shape), versions in _paired(specs).items():
        if method not in SAFE_VERBS or "{}" not in path_shape:
            continue
        if set(versions) != {"v1", "v2"} or not all(map(is_callable, versions.values())):
            continue
        cases.append(
            ErrorCase(
                method=method,
                operation=path_shape,
                v1_path=concrete_path(versions["v1"].path_template),
                v2_path=concrete_path(versions["v2"].path_template),
            )
        )
    return sorted(cases, key=lambda case: (case.operation, case.method))
