"""Known contract deviations, accepted deliberately.

Turning a strict check on against an existing product finds a batch of
pre-existing deviations at once. Suppressing the check would throw away
its value; leaving it noisy would bury the next real one. So every
deviation already understood is written down here with the finding that
records it, and anything not on this list fails the run.

That is what makes strict mode usable: the list is the boundary between
"already reported" and "new", and it only ever shrinks.

Each entry must name a finding in docs/findings. No entry exists just to
quieten the suite.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from vikunja_qa.contracts.validator import Violation


@dataclass(frozen=True)
class Deviation:
    """One accepted deviation, matched against incoming violations."""

    finding: str
    spec: str
    kind: str
    reason: str
    operation: str = "*"
    detail_pattern: str = ".*"

    def matches(self, violation: Violation) -> bool:
        if self.spec not in ("*", violation.spec):
            return False
        if self.kind != violation.kind:
            return False
        if self.operation != "*" and self.operation != violation.operation:
            return False
        # Matched against the operation and the detail together, so one
        # pattern can target either. Violations that carry no template,
        # such as an undocumented operation, identify themselves by URL.
        subject = f"{violation.operation}\n{violation.detail}"
        return re.search(self.detail_pattern, subject, re.DOTALL) is not None


# Collection and map fields come back as null rather than as an empty
# collection, which is what a nil slice or map serialises to in Go. The v2
# description gets this right and types them as ["array", "null"]; the v1
# description does not, so every response carrying an empty collection
# contradicts its own contract.
_NULL_COLLECTION = r"None is not of type '(array|object|integer)'"

KNOWN: tuple[Deviation, ...] = (
    Deviation(
        finding="VKJ-002",
        spec="v1",
        kind="schema mismatch",
        detail_pattern=_NULL_COLLECTION,
        reason=(
            "v1 declares collection and map fields non-nullable while the "
            "product returns null for empty ones. v2 declares the same "
            "fields as nullable, so the description is what is wrong."
        ),
    ),
    Deviation(
        finding="VKJ-002",
        spec="v1",
        kind="schema mismatch",
        detail_pattern=r"max_permission: None is not one of \[0, 1, 2\]",
        reason=(
            "Same root cause: the permission type serialises its unknown "
            "value as null, which the declared enum does not admit."
        ),
    ),
    Deviation(
        finding="VKJ-003",
        spec="v2",
        kind="schema mismatch",
        detail_pattern=(
            r"(related_tasks|reactions|extra_settings_links|filter|"
            r"bucket_configuration): None is not of type"
        ),
        reason=(
            "v2 fixed nullability for most collections but left these few "
            "typed as plain object while the product still returns null."
        ),
    ),
    Deviation(
        finding="VKJ-001",
        spec="v1",
        kind="schema mismatch",
        detail_pattern=r"entity: '(task|project)' is not of type 'integer'",
        reason=(
            "v1 types Subscription.entity as an integer; the product "
            "returns a string. v2 documents it correctly as an enum of "
            "strings, which settles which side is wrong."
        ),
    ),
    Deviation(
        finding="VKJ-008",
        spec="v2",
        kind="schema mismatch",
        detail_pattern=r"Additional properties are not allowed \('message' was unexpected\)",
        reason=(
            "Errors raised before a handler runs, authentication failures "
            "above all, come back in the v1 flat shape rather than the "
            "problem+json model v2 declares for every operation."
        ),
    ),
    Deviation(
        finding="VKJ-007",
        spec="v1",
        kind="undocumented operation",
        detail_pattern=r"POST http\S*/api/v1/labels/\d+",
        reason=(
            "The other half of VKJ-007: the description omits the verb "
            "that works, POST on a single label, while declaring a PUT "
            "the product rejects."
        ),
    ),
    Deviation(
        finding="VKJ-009",
        spec="*",
        kind="not JSON",
        reason=(
            "Endpoints serving an image, a QR code or an export archive "
            "are described as returning JSON."
        ),
    ),
    Deviation(
        finding="VKJ-004",
        spec="*",
        kind="undeclared status",
        reason=(
            "Several operations answer with statuses their description "
            "never mentions, 401 and 412 among them."
        ),
    ),
)


class Baseline:
    """Splits violations into the ones already known and the rest."""

    def __init__(self, deviations: tuple[Deviation, ...] = KNOWN) -> None:
        self._deviations = deviations

    def known(self, violation: Violation) -> Deviation | None:
        for deviation in self._deviations:
            if deviation.matches(violation):
                return deviation
        return None

    def split(
        self, violations: list[Violation]
    ) -> tuple[list[Violation], list[tuple[Violation, Deviation]]]:
        """Returns (new, accepted)."""
        new: list[Violation] = []
        accepted: list[tuple[Violation, Deviation]] = []
        for violation in violations:
            deviation = self.known(violation)
            if deviation is None:
                new.append(violation)
            else:
                accepted.append((violation, deviation))
        return new, accepted

    @property
    def findings(self) -> list[str]:
        return sorted({d.finding for d in self._deviations})
