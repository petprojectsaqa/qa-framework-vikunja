"""Typed slots on the pytest config and on test items.

The plugin and the fixtures share a little state: the run's ledger, the
contract validator a worker built, and the matrix checks each test covers.
Stash keys keep that typed and namespaced instead of hanging ad-hoc
attributes off pytest's objects.
"""

from __future__ import annotations

import pytest

from vikunja_qa.contracts.validator import ContractValidator
from vikunja_qa.testing.conventions import Declarations
from vikunja_qa.testing.ledger import Ledger
from vikunja_qa.testing.traceability import Check

LEDGER = pytest.StashKey[Ledger]()
VALIDATOR = pytest.StashKey[ContractValidator]()

#: What a matrix-bound test declared: read at collection, counted when it runs.
DECLARED = pytest.StashKey[Declarations]()

#: Checks the coverage gate found with no tests, kept for the terminal summary.
UNCOVERED = pytest.StashKey[list[Check]]()
