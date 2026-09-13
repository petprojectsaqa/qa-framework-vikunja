"""Turning a specification into test cases.

Every operation either needs a credential or is public on purpose. There
are a few hundred of them across two versions, which is far too many to
keep a hand-written list of, and exactly the sort of thing that rots: a
new endpoint added without authentication would slip past a suite that
only checks the endpoints somebody remembered to write a test for.

So the list comes from the product. This module turns the descriptions
into concrete, safe calls, and names the handful of operations that are
public by design, each with a reason.
"""

from __future__ import annotations

from dataclasses import dataclass

from vikunja_qa.contracts.spec import Operation, SpecIndex

#: Operations that must answer without a credential, and why.
#: Anything not listed here has to demand one.
PUBLIC: dict[str, str] = {
    "GET /info": "instance capabilities, read before login",
    "GET /health": "liveness probe",
    "POST /login": "issues the credential",
    "POST /register": "creates the account that will hold one",
    "POST /user/confirm": "spends the token from the welcome mail",
    "POST /user/password/reset": "the caller has lost their credential",
    "POST /user/password/token": "the caller has lost their credential",
    "POST /auth/openid/{provider}/callback": "external identity provider lands here",
    "POST /oauth/token": "issues the credential",
    "POST /shares/{share}/auth": "trades a public hash for a scoped token",
}

#: Never call anything under this. The product's test-support API empties
#: every table, which would destroy the stand out from under the run.
#:
#: Matched as the first segment of the path rather than as a literal
#: template. `/test/{table}` names a parameter, and this module exists
#: because the two descriptions spell their parameters differently: a
#: denylist whose failure mode is "empty every table mid-run" must not
#: depend on one of them spelling it `table`.
NEVER_CALL_UNDER = "test"

#: Path parameters, filled with values that match nothing.
#: Authorization is decided before any lookup, so an identifier that
#: cannot exist keeps the sweep from touching real data even if an
#: endpoint turns out not to check at all.
#: Some path parameters are not identifiers at all but words the product
#: only accepts from a fixed list. Filling those with a number asks a
#: different question, and the two versions then fail for different
#: reasons: v1 looks the task up and says it is missing while v2 refuses
#: the word itself. Each one is spelled out here, per the name each
#: version gives it.
SUBSTITUTIONS: dict[str, str] = {
    "username": "nobody999",
    "kind": "tasks",
    "entitykind": "tasks",
    "entity": "task",
    "relationKind": "subtask",
    "provider": "none",
    "image": "none",
}
ABSENT_ID = "999999999"


@dataclass(frozen=True)
class Call:
    """One concrete, safe request derived from an operation."""

    spec: str
    method: str
    path: str
    operation: str
    public: bool
    reason: str = ""

    @property
    def id(self) -> str:
        return f"{self.spec}-{self.operation.replace(' ', '-')}"


def concrete_path(template: str) -> str:
    """Fill a path template with values that resolve to nothing."""
    parts = []
    for part in template.strip("/").split("/"):
        if part.startswith("{") and part.endswith("}"):
            name = part[1:-1]
            parts.append(SUBSTITUTIONS.get(name, ABSENT_ID))
        else:
            parts.append(part)
    return "/" + "/".join(parts)


def is_callable(operation: Operation) -> bool:
    segments = [part for part in operation.path_template.strip("/").split("/") if part]
    return bool(segments) and segments[0] != NEVER_CALL_UNDER


def calls_for(spec: SpecIndex) -> list[Call]:
    """Every operation in one description, as a call the sweep can make."""
    calls = []
    for operation in spec.operations:
        if not is_callable(operation):
            continue
        calls.append(
            Call(
                spec=spec.label,
                method=operation.method,
                path=concrete_path(operation.path_template),
                operation=operation.key,
                public=operation.key in PUBLIC,
                reason=PUBLIC.get(operation.key, ""),
            )
        )
    return sorted(calls, key=lambda c: (c.spec, c.operation))


def unused_public_entries(specs: list[SpecIndex]) -> list[str]:
    """Allowlist entries matching no operation in either description.

    Checked by a test. An entry that stopped matching means either the
    operation was renamed or the exemption is stale, and a stale
    exemption is how an endpoint quietly stops being tested.
    """
    known = {operation.key for spec in specs for operation in spec.operations}
    return sorted(entry for entry in PUBLIC if entry not in known)


def unused_substitutions(specs: list[SpecIndex]) -> list[str]:
    """Substitution keys matching no path parameter in either description.

    The same argument as the allowlist above, for the other table. These
    keys name the path parameters that are words rather than identifiers,
    and a key that stops matching means the parameter was renamed — at
    which point the sweep starts filling a word-shaped parameter with a
    number and asks a different question of each version, quietly. A stale
    key is the only visible sign that has happened, so it is checked.
    """
    named = {
        part[1:-1]
        for spec in specs
        for operation in spec.operations
        for part in operation.path_template.split("/")
        if part.startswith("{") and part.endswith("}")
    }
    return sorted(key for key in SUBSTITUTIONS if key not in named)
