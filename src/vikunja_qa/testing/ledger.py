"""What a run learned, in a form that survives crossing process boundaries.

Under pytest-xdist every worker is a separate process with its own contract
validator and its own count of which matrix checks ran. Reporting from one
process shows one worker's share and calls it the total, which is how the
earlier contract summary silently vanished under `-n 8`.

The ledger is the fix. Each worker fills one, hands it to the controller as
plain data, and the controller merges them before printing. It holds only
built-in types on the wire, because that is what xdist can carry.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

WireData = dict[str, Any]


@dataclass
class Ledger:
    described: dict[str, int] = field(default_factory=dict)
    exercised: dict[str, set[str]] = field(default_factory=dict)
    violations: list[dict[str, Any]] = field(default_factory=list)
    accepted: Counter[str] = field(default_factory=Counter)
    covered: Counter[str] = field(default_factory=Counter)
    generated: int = 0
    executed: int = 0

    # --- filling ------------------------------------------------------------

    def record_test(self, codes: Iterable[str], *, generated: bool) -> None:
        """Count one test whose body ran, against every check it covers."""
        self.executed += 1
        self.generated += int(generated)
        for code in codes:
            self.covered[code] += 1

    def absorb_contracts(self, snapshot: WireData) -> None:
        """Take in what a contract validator saw."""
        for label, total in snapshot.get("described", {}).items():
            self.described[label] = max(self.described.get(label, 0), int(total))
        for label, operations in snapshot.get("exercised", {}).items():
            self.exercised.setdefault(label, set()).update(operations)
        self.violations.extend(snapshot.get("violations", []))
        self.accepted.update(snapshot.get("accepted", []))

    # --- combining ----------------------------------------------------------

    def merge(self, other: Ledger) -> None:
        for label, total in other.described.items():
            self.described[label] = max(self.described.get(label, 0), total)
        for label, operations in other.exercised.items():
            self.exercised.setdefault(label, set()).update(operations)
        self.violations.extend(other.violations)
        self.accepted.update(other.accepted)
        self.covered.update(other.covered)
        self.generated += other.generated
        self.executed += other.executed

    def to_wire(self) -> WireData:
        return {
            "described": dict(self.described),
            "exercised": {label: sorted(ops) for label, ops in self.exercised.items()},
            "violations": list(self.violations),
            "accepted": dict(self.accepted),
            "covered": dict(self.covered),
            "generated": self.generated,
            "executed": self.executed,
        }

    @classmethod
    def from_wire(cls, data: WireData) -> Ledger:
        return cls(
            described={k: int(v) for k, v in data.get("described", {}).items()},
            exercised={k: set(v) for k, v in data.get("exercised", {}).items()},
            violations=list(data.get("violations", [])),
            accepted=Counter({k: int(v) for k, v in data.get("accepted", {}).items()}),
            covered=Counter({k: int(v) for k, v in data.get("covered", {}).items()}),
            generated=int(data.get("generated", 0)),
            executed=int(data.get("executed", 0)),
        )

    # --- reading ------------------------------------------------------------

    @property
    def is_empty(self) -> bool:
        return not (self.executed or self.described or self.violations)

    def operation_coverage(self) -> dict[str, tuple[int, int]]:
        """Per API version: operations exercised, operations described."""
        return {
            label: (len(self.exercised.get(label, set())), total)
            for label, total in sorted(self.described.items())
        }

    def distinct_violations(self) -> list[dict[str, Any]]:
        """New contract violations, once per distinct deviation.

        The same deviation is usually hit many times across workers; the
        report is for reading, so it lists each shape once.

        The detail is part of what makes a deviation distinct, and leaving
        it out of the key would undo the reason the validator reports one
        violation per mismatch: two different mismatches on one operation
        would collapse into one line, and the count above the list would
        say one where there are two.
        """
        seen: set[tuple[Any, ...]] = set()
        distinct = []
        for violation in self.violations:
            key = (
                violation.get("spec"),
                violation.get("operation"),
                violation.get("status"),
                violation.get("kind"),
                violation.get("detail"),
            )
            if key not in seen:
                seen.add(key)
                distinct.append(violation)
        return distinct
