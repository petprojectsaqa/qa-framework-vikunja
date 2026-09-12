"""Checks every response against the contract it claims to honour.

This is installed as a transport hook, which is the whole idea: contract
coverage is a side effect of the suite doing its ordinary work, so no
contract tests need writing and a newly added endpoint falls under the
check the first time any test touches it. See docs/strategy.md, section 6.

The same pass records which operations were actually exercised, giving a
coverage figure counted from real calls rather than from intent.
"""

from __future__ import annotations

import threading
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from jsonschema import Draft4Validator, Draft202012Validator
from jsonschema.protocols import Validator

from vikunja_qa.contracts.spec import Operation, SpecIndex, resolvable
from vikunja_qa.transport.response import ApiResponse

if TYPE_CHECKING:
    from vikunja_qa.contracts.baseline import Baseline, Deviation


class Mode(StrEnum):
    STRICT = "strict"
    """A violation fails the test that produced it, at the call site."""

    COLLECT = "collect"
    """Violations are recorded and reported at the end of the run."""

    OFF = "off"


class ContractViolationError(AssertionError):
    pass


@dataclass(frozen=True)
class Violation:
    spec: str
    operation: str
    status: int
    kind: str
    detail: str
    url: str

    def __str__(self) -> str:
        return f"[{self.spec}] {self.operation} -> {self.status}: {self.kind}\n  {self.detail}"


class ContractValidator:
    """Validates responses against whichever specification covers them."""

    #: How many mismatches one response may contribute. A body that
    #: disagrees with its schema in fifty places tells the reader the same
    #: thing as one that disagrees in ten.
    MISMATCHES_PER_RESPONSE = 10

    #: Statuses that carry no content, whatever the description declares.
    WITHOUT_A_BODY = frozenset({204, 304})

    def __init__(
        self,
        specs: list[SpecIndex],
        mode: Mode = Mode.COLLECT,
        baseline: Baseline | None = None,
    ) -> None:
        self._specs = specs
        self._mode = mode
        self._baseline = baseline
        self._lock = threading.Lock()
        self._violations: list[Violation] = []
        self._accepted: list[tuple[Violation, Deviation]] = []
        self._called: Counter[str] = Counter()
        self._validators: dict[int, Validator] = {}

    @contextmanager
    def collecting(self) -> Iterator[None]:
        """Record violations without failing the test that caused them.

        For callers that deliberately walk error paths, such as the
        generated sweep: it probes hundreds of operations with
        identifiers that match nothing, so nearly every response is an
        error, and error schemas are where deviations cluster. A test
        asking whether an endpoint demands a credential should not fail
        because of what that endpoint's error body looks like.

        Violations are still recorded and still reported at the end, so
        nothing is lost; only the failure is moved to where it belongs.
        """
        previous, self._mode = self._mode, Mode.COLLECT
        try:
            yield
        finally:
            self._mode = previous

    @contextmanager
    def suspended(self) -> Iterator[None]:
        """Check nothing at all for the duration.

        Different from `collecting`, and the difference matters. A sweep
        walks error paths it did not choose and its findings are real, so
        it records them. A test that deliberately calls an undocumented
        verb to prove it is refused has not found anything: recording it
        would put a test artefact in the report next to genuine
        deviations.
        """
        previous, self._mode = self._mode, Mode.OFF
        try:
            yield
        finally:
            self._mode = previous

    # --- the hook -----------------------------------------------------------

    def __call__(self, response: ApiResponse) -> None:
        if self._mode is Mode.OFF:
            return

        spec = self._spec_for(response.url)
        if spec is None:
            return

        operation = spec.match(response.method, response.url)
        if operation is None:
            self._report(
                Violation(
                    spec=spec.label,
                    operation=f"{response.method} {response.url}",
                    status=response.status,
                    kind="undocumented operation",
                    detail="the specification describes no operation for this call",
                    url=response.url,
                )
            )
            return

        with self._lock:
            self._called[f"{spec.label} {operation.key}"] += 1

        self._check(spec, operation, response)

    # --- checks -------------------------------------------------------------

    def _check(self, spec: SpecIndex, operation: Operation, response: ApiResponse) -> None:
        schema = operation.schema_for(response.status)
        if schema is None:
            self._report(
                Violation(
                    spec=spec.label,
                    operation=operation.key,
                    status=response.status,
                    kind="undeclared status",
                    detail=(
                        "the operation does not declare this status; declared: "
                        + ", ".join(sorted(operation.responses))
                        or "none"
                    ),
                    url=response.url,
                )
            )
            return

        if response.status in self.WITHOUT_A_BODY:
            # 204 and 304 carry no content by definition, whatever a
            # description says it would have sent. Asking for a body here
            # would report the standard as a defect.
            return

        if not isinstance(response.body, (dict, list)):
            # Some endpoints legitimately answer with plain text; only flag
            # it when the contract promised a structured body.
            if schema.get("type") in {"object", "array"} or "$ref" in schema:
                self._report(
                    Violation(
                        spec=spec.label,
                        operation=operation.key,
                        status=response.status,
                        kind="not JSON",
                        detail=f"expected a structured body, got {type(response.body).__name__}",
                        url=response.url,
                    )
                )
            return

        # One violation per mismatch, not one per response. The baseline
        # decides what is already known by matching the detail, so a
        # response carrying a known deviation beside an unknown one would
        # otherwise have both absorbed under the known finding, which is
        # exactly what the baseline must never do.
        for error in self._validate(spec, schema, response.body):
            self._report(
                Violation(
                    spec=spec.label,
                    operation=operation.key,
                    status=response.status,
                    kind="schema mismatch",
                    detail=error,
                    url=response.url,
                )
            )

    def _validate(self, spec: SpecIndex, schema: dict[str, Any], body: Any) -> list[str]:
        """Every mismatch between one body and its schema, one per entry.

        Capped, because a response that disagrees with its schema in fifty
        places says the same thing as one that disagrees in ten, and the
        report has to stay readable.
        """
        validator = self._validator_for(spec, schema)
        messages = []
        for error in sorted(validator.iter_errors(body), key=lambda e: list(e.path)):
            where = "/".join(str(p) for p in error.path) or "<root>"
            messages.append(f"{where}: {error.message}")
            if len(messages) >= self.MISMATCHES_PER_RESPONSE:
                break
        return messages

    def _validator_for(self, spec: SpecIndex, schema: dict[str, Any]) -> Validator:
        composed = resolvable(schema, spec.document)
        # Swagger 2.0 schemas are a draft-4 subset; OpenAPI 3.1 is 2020-12.
        cls = Draft4Validator if spec.version.startswith("2.") else Draft202012Validator
        return cls(composed)

    def _spec_for(self, url: str) -> SpecIndex | None:
        for spec in self._specs:
            if spec.base_path and spec.base_path in url:
                return spec
        return None

    def _report(self, violation: Violation) -> None:
        """Record a violation, and in strict mode fail on it unless the
        baseline already accounts for it."""
        known = self._baseline.known(violation) if self._baseline else None
        with self._lock:
            if known is not None:
                self._accepted.append((violation, known))
            else:
                self._violations.append(violation)
        if known is None and self._mode is Mode.STRICT:
            raise ContractViolationError(str(violation))

    # --- results ------------------------------------------------------------

    @property
    def violations(self) -> list[Violation]:
        """Violations the baseline does not account for."""
        with self._lock:
            return list(self._violations)

    @property
    def accepted(self) -> list[tuple[Violation, Deviation]]:
        """Violations matched by a known deviation, kept so the report can
        show that the check is still seeing them."""
        with self._lock:
            return list(self._accepted)

    def coverage(self) -> dict[str, dict[str, int]]:
        """Operations touched versus operations described, per specification."""
        with self._lock:
            called = dict(self._called)
        summary = {}
        for spec in self._specs:
            total = len(spec.operations)
            touched = sum(1 for key in called if key.startswith(f"{spec.label} "))
            summary[spec.label] = {
                "described": total,
                "exercised": touched,
                "percent": round(100 * touched / total) if total else 0,
            }
        return summary

    def snapshot(self) -> dict[str, Any]:
        """Everything this validator saw, as plain data.

        Built for crossing a process boundary: under xdist each worker has
        its own validator, and only plain data reaches the controller that
        prints the combined picture.
        """
        with self._lock:
            called = list(self._called)
            violations = [asdict(violation) for violation in self._violations]
            accepted = [deviation.finding for _, deviation in self._accepted]
        return {
            "described": {spec.label: len(spec.operations) for spec in self._specs},
            "exercised": {
                spec.label: sorted(
                    key.split(" ", 1)[1] for key in called if key.startswith(f"{spec.label} ")
                )
                for spec in self._specs
            },
            "violations": violations,
            "accepted": accepted,
        }

    def untouched(self, spec: SpecIndex) -> list[str]:
        """Operations no test has called yet. This is the list the
        generated sweep exists to close."""
        with self._lock:
            called = {key for key in self._called if key.startswith(f"{spec.label} ")}
        return sorted(
            operation.key
            for operation in spec.operations
            if f"{spec.label} {operation.key}" not in called
        )
