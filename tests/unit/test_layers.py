"""The layering, enforced instead of described.

docs/strategy.md draws the framework as layers with a one-way dependency:
tests on top, then scenes, then the area clients, then transport, then
configuration. An architecture that lives only in prose comes apart in the
third month, so the rules that matter are read out of the source here.

Everything is parsed, not imported, so this costs milliseconds and needs no
stand.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPOSITORY = Path(__file__).resolve().parents[2]
PACKAGE = REPOSITORY / "src" / "vikunja_qa"
TESTS = REPOSITORY / "tests"

#: Module prefix -> the parts of the framework it may not reach for. A layer
#: may use what is below it and must not know what is above it.
FORBIDDEN_IMPORTS = {
    "domain": ("actors", "clients", "contracts", "scenes", "testing", "transport", "ui"),
    "transport": ("actors", "clients", "scenes", "testing", "ui"),
    "auth": ("actors", "clients", "scenes", "testing", "transport", "ui"),
    "clients": ("actors", "scenes", "testing", "ui"),
    "contracts": ("actors", "clients", "scenes", "testing", "ui"),
    "scenes": ("testing",),
}

#: pytest belongs to the layer that talks to pytest, and nowhere else. The
#: rest of the framework stays usable from a plain script.
PYTEST_IS_ALLOWED_IN = "testing"

HTTP_VERBS = frozenset({"get", "post", "put", "patch", "delete", "request", "head", "options"})


def _modules(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*.py") if "__pycache__" not in path.parts)


def _imported_names(module: Path) -> set[str]:
    """Every `vikunja_qa.<part>` this module imports, as the part name."""
    tree = ast.parse(module.read_text(encoding="utf-8"))
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("vikunja_qa"):
            parts = (node.module or "").split(".")
            if len(parts) > 1:
                found.add(parts[1])
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("vikunja_qa."):
                    found.add(alias.name.split(".")[1])
    return found


def _top_level_imports(module: Path) -> set[str]:
    tree = ast.parse(module.read_text(encoding="utf-8"))
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.add(node.module.split(".")[0])
    return found


@pytest.mark.parametrize("layer", sorted(FORBIDDEN_IMPORTS), ids=lambda name: name)
def test_a_layer_never_reaches_upwards(layer: str) -> None:
    forbidden = set(FORBIDDEN_IMPORTS[layer])
    offences = []
    for module in _modules(PACKAGE / layer):
        reached = _imported_names(module) & forbidden
        if reached:
            offences.append(
                f"{module.relative_to(REPOSITORY).as_posix()} imports {sorted(reached)}"
            )

    assert not offences, "the dependency arrow only points down:\n" + "\n".join(offences)


def test_only_the_pytest_layer_knows_about_pytest() -> None:
    """Everything else has to work in a script, a notebook or another runner."""
    offences = [
        module.relative_to(REPOSITORY).as_posix()
        for module in _modules(PACKAGE)
        if "pytest" in _top_level_imports(module)
        and module.relative_to(PACKAGE).parts[0] != PYTEST_IS_ALLOWED_IN
    ]

    assert not offences, f"pytest reached outside vikunja_qa.{PYTEST_IS_ALLOWED_IN}: {offences}"


def test_nothing_below_the_tests_asserts() -> None:
    """A client returns an answer; deciding whether it is right belongs to a
    test. An assertion further down turns a product defect into a framework
    error, in the wrong file, with the wrong message.

    The exceptions are the two layers whose job is to fail: the scene
    builder, which reports that the world could not be arranged, and the
    testing package, which is part of the run.
    """
    offences = []
    for module in _modules(PACKAGE):
        area = module.relative_to(PACKAGE).parts[0]
        if area in ("testing", "scenes.py"):
            continue
        tree = ast.parse(module.read_text(encoding="utf-8"))
        lines = [node.lineno for node in ast.walk(tree) if isinstance(node, ast.Assert)]
        offences += [f"{module.relative_to(REPOSITORY).as_posix()}:{line}" for line in lines]

    assert not offences, "assertions below the tests layer:\n" + "\n".join(offences)


def test_no_test_speaks_http_directly() -> None:
    """Tests reach the product through the clients, so that every call is
    stamped with a credential, recorded in the report and validated against
    the contract. A bare `requests.get` in a test skips all three.

    Naming the exception rather than hiding it: the metrics check reads
    Prometheus, which is part of the stand and not the product, and has no
    client of its own.
    """
    allowed = {TESTS / "api" / "side_effects" / "test_metrics.py"}
    offences = []
    for module in _modules(TESTS):
        if module in allowed:
            continue
        tree = ast.parse(module.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "requests"
                and node.func.attr in HTTP_VERBS
            ):
                where = module.relative_to(REPOSITORY).as_posix()
                offences.append(f"{where}:{node.lineno} calls requests.{node.func.attr}")

    assert not offences, "\n".join(offences)


def test_the_suite_contains_no_fixed_pause_in_place_of_waiting() -> None:
    """`time.sleep` is both slower and less reliable than waiting on a
    condition, so the suite waits on conditions instead.

    Two modules are allowed it, and neither is waiting for the product.
    The mail resilience module lets a timer inside the product elapse, and
    a timer is not something a poll can observe. The concurrency helper's
    own test sleeps to make a caller slow on purpose, because staging that
    is what it exists to check.
    """
    allowed = {
        TESTS / "resilience" / "dependencies" / "test_mail.py",
        TESTS / "unit" / "test_concurrency.py",
    }
    offences = []
    for module in _modules(TESTS):
        if module in allowed:
            continue
        tree = ast.parse(module.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "time"
                and node.func.attr == "sleep"
            ):
                where = module.relative_to(REPOSITORY).as_posix()
                offences.append(f"{where}:{node.lineno}")

    assert not offences, "fixed pauses, where wait_until belongs:\n" + "\n".join(offences)
