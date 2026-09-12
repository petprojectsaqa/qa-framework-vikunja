"""Turning the product's own permission catalogue into test cases.

A scoped API token carries a map of area to actions, and the product
publishes every valid key itself at `/routes`. So the matrix that checks
those scopes does not need maintaining: it is derived from the same
catalogue the product validates tokens against, and an area added
tomorrow is covered the next time the suite runs.

Each entry there looks like

    "labels": {
        "read_all": {"path": "/api/v1/labels",        "method": "GET"},
        "create":   {"path": "/api/v1/labels",        "method": "PUT"},
        "update":   {"path": "/api/v1/labels/:label", "method": "POST"},
        ...
    }
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

#: Never generate a case for these. The product's test-support area can
#: empty every table, which would destroy the stand mid-run.
EXCLUDED_AREAS = frozenset({"test"})

#: Actions that read. Preferred as the granted scope so that proving a
#: token *can* do something never creates anything.
READ_ACTIONS = ("read_all", "read_one")

ABSENT_ID = "999999999"


@dataclass(frozen=True)
class Action:
    area: str
    name: str
    method: str
    path: str

    @property
    def concrete_path(self) -> str:
        """The catalogue writes parameters as `:name`; fill them with a
        value that matches nothing, so a case that gets past the scope
        check still touches no real data."""
        parts = [
            ABSENT_ID if part.startswith(":") else part for part in self.path.strip("/").split("/")
        ]
        return "/" + "/".join(parts)

    @property
    def label(self) -> str:
        return f"{self.area}.{self.name}"


@dataclass(frozen=True)
class ScopeCase:
    """One area, one granted action, and the siblings that must stay shut."""

    area: str
    granted: Action
    denied: tuple[Action, ...]

    @property
    def id(self) -> str:
        return f"{self.area}-{self.granted.name}"


def parse_routes(payload: Any) -> dict[str, list[Action]]:
    areas: dict[str, list[Action]] = {}
    if not isinstance(payload, dict):
        return areas
    for area, actions in payload.items():
        if area in EXCLUDED_AREAS or not isinstance(actions, dict):
            continue
        parsed = [
            Action(area=area, name=name, method=str(spec["method"]), path=str(spec["path"]))
            for name, spec in actions.items()
            if isinstance(spec, dict) and "method" in spec and "path" in spec
        ]
        if parsed:
            areas[area] = parsed
    return areas


def cases_for(payload: Any) -> list[ScopeCase]:
    """One case per area that has a read action and at least one sibling.

    The granted scope is a read wherever possible: proving that a token
    reaches what it should must not leave rows behind, and a `create`
    would.
    """
    cases = []
    for area, actions in parse_routes(payload).items():
        granted = next((a for a in actions if a.name in READ_ACTIONS), None)
        if granted is None:
            continue
        denied = tuple(a for a in actions if a.name != granted.name)
        if not denied:
            continue
        cases.append(ScopeCase(area=area, granted=granted, denied=denied))
    return sorted(cases, key=lambda c: c.area)
