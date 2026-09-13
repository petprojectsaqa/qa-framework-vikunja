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
    #: The status this entry accepts, or None for any. Needed because the
    #: status is not part of the detail, so an entry for "this operation
    #: answers 401 undeclared" had no way to say 401 and ended up accepting
    #: every status there is.
    status: int | None = None
    detail_pattern: str = ".*"

    def matches(self, violation: Violation) -> bool:
        if self.spec not in ("*", violation.spec):
            return False
        if self.kind != violation.kind:
            return False
        if self.operation != "*" and self.operation != violation.operation:
            return False
        if self.status is not None and self.status != violation.status:
            return False
        # Matched against the operation and the detail together, so one
        # pattern can target either. Violations that carry no template,
        # such as an undocumented operation, identify themselves by URL.
        subject = f"{violation.operation}\n{violation.detail}"
        return re.search(self.detail_pattern, subject, re.DOTALL) is not None

    @property
    def is_blanket(self) -> bool:
        """True when this entry accepts a whole kind of violation.

        An entry this wide does not record a deviation, it switches a check
        off, and a check that is off finds nothing. A test refuses one.
        """
        return (
            self.spec == "*"
            and self.operation == "*"
            and self.status is None
            and self.detail_pattern == ".*"
        )


# Collection and map fields come back as null rather than as an empty
# collection, which is what a nil slice or map serialises to in Go. The v2
# description gets this right and types them as ["array", "null"]; the v1
# description does not, so every response carrying an empty collection
# contradicts its own contract.
#
# Named field by field rather than by the message alone. An unanchored
# "None is not of type" accepts a null anywhere on any v1 response, which
# would quietly absorb a null identifier or a null foreign key — a
# different defect entirely, and a worse one. The list is what a full run
# actually produces; a field that stops appearing is an entry to delete.
# A field preceded by `/` sits inside a collection element, one preceded
# by the newline is at the root of the body.
_NULL_COLLECTION = (
    r"[\n/](assignees|attachments|bucket_configuration|created_by|extra_settings_links"
    r"|filter|labels|members|order_by|providers|reactions|related_tasks|reminders"
    r"|sort_by): None is not of type '(array|object)'"
)

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
        finding="VKJ-002",
        spec="v1",
        kind="schema mismatch",
        detail_pattern=r"max_permission: None is not of type 'integer'",
        reason=(
            "The same null on the same field, reported against the declared "
            "type rather than against the enum. Both come from one response, "
            "and each needs its own entry now that the collection pattern "
            "names its fields instead of accepting any null at all."
        ),
    ),
    Deviation(
        finding="VKJ-003",
        spec="v2",
        kind="schema mismatch",
        detail_pattern=(
            r"(related_tasks|reactions|extra_settings_links|filter): None is not of type"
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
    # --- VKJ-004, undeclared statuses ---------------------------------------
    #
    # This used to be one entry naming the kind and nothing else, which
    # accepted every undeclared status on either description, at any status,
    # for any operation. That is not a baseline entry, it is the check
    # switched off: an unexpected 500 on an operation that does not declare
    # one was filed as already known. The finding's own write-up called the
    # entry out and said it would narrow once a generated family had walked
    # every operation. It has, so here is the measured list.
    #
    # Split by status, because that is the shape of the deviation: the
    # descriptions are missing whole status classes, not individual
    # operations. Counts are from a full run of tests/api against v2.6.0,
    # 191 distinct operation-and-status pairs in all. A status class not
    # below is new, and breaks the run.
    Deviation(
        finding="VKJ-004",
        spec="v1",
        kind="undeclared status",
        status=401,
        reason=(
            "142 operations. Only two v1 operations declare 401 at all, yet "
            "every protected one answers it to a missing or expired token. "
            "The fix asked for is to describe it once, as a response shared "
            "by the whole protected surface."
        ),
    ),
    Deviation(
        finding="VKJ-004",
        spec="v2",
        kind="undeclared status",
        status=401,
        operation="POST /user/export/download",
        reason=(
            "The one v2 operation carrying no `default` response, and so the "
            "only one whose 401 is not covered by the error model the other "
            "195 share. v2 gets this right everywhere else."
        ),
    ),
    Deviation(
        finding="VKJ-004",
        spec="v1",
        kind="undeclared status",
        status=404,
        reason=(
            "33 operations that look an identifier up and answer 404 when it "
            "resolves to nothing, while declaring only 200, 403 and 500."
        ),
    ),
    Deviation(
        finding="VKJ-004",
        spec="v1",
        kind="undeclared status",
        status=403,
        reason=(
            "5 operations. The mirror of the 404 group: these declare 404 and "
            "answer 403, so between the two groups the description gets the "
            "refusal and the absence the wrong way round."
        ),
    ),
    Deviation(
        finding="VKJ-004",
        spec="v1",
        kind="undeclared status",
        status=412,
        reason=(
            "4 operations. The product answers 412 where its description "
            "would say 400: a field that failed validation (domain code "
            "2002) and a write to an archived project (3008)."
        ),
    ),
    Deviation(
        finding="VKJ-004",
        spec="v1",
        kind="undeclared status",
        status=400,
        reason=(
            "3 operations answering 400 to a malformed argument without "
            "declaring it, among them a reaction kind that is not a word the "
            "product knows."
        ),
    ),
    Deviation(
        finding="VKJ-004",
        spec="v1",
        kind="undeclared status",
        status=201,
        operation="PUT /user/settings/token/caldav",
        reason=(
            "The only undeclared success in either description: minting a "
            "CalDAV token answers 201 while its description declares 200."
        ),
    ),
    Deviation(
        finding="VKJ-004",
        spec="v1",
        kind="undeclared status",
        status=405,
        operation="POST /migration/vikunja-file/migrate",
        reason=(
            "The description declares a POST the router does not serve. The "
            "same shape as VKJ-007 on a different endpoint; kept under "
            "VKJ-004 because the write-up for VKJ-007 is about labels."
        ),
    ),
    Deviation(
        finding="VKJ-007",
        spec="v1",
        kind="undeclared status",
        status=405,
        operation="PUT /labels/{id}",
        reason=(
            "The first half of VKJ-007, seen from the other side: the "
            "description declares a PUT, and the product answers 405 to it."
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
