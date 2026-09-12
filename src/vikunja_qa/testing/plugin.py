"""The suite's pytest plugin: conventions that hold because they are enforced.

What it does, in the order pytest calls it:

Registers the markers tests declare, and one marker per coverage matrix
check, so `--strict-markers` catches a typo and `pytest --markers` lists
every way the suite can be sliced.

Classifies every collected test by where it lives, `tests/<layer>/<area>/`,
and derives its report labels from that: layer as epic, area as feature,
module as story. The directory and the report cannot disagree, because one
is computed from the other.

Binds each product test to the coverage matrix. A test declares the check
it provides with `@pytest.mark.covers("ACL")`; the plugin gives it the
matching selection marker (`pytest -m acl`), a severity from the matrix
priority and a link to the matrix row, and links any finding or advisory
it names. A product test that covers nothing, or names a check, finding or
advisory that does not exist, is refused at collection, and the run is red.

Keeps the resilience layer out unless `--resilience` is given, and refuses
to run it in parallel. Deciding this by directory rather than by a marker
someone has to remember means a test that stops containers cannot drift
into the main run.

Collects what the run learned in a ledger per process, carries it from
xdist workers to the controller, and prints the combined contract coverage
and matrix traceability once, correctly, however many workers ran.
"""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest

from vikunja_qa.config import get_settings
from vikunja_qa.contracts.baseline import Baseline
from vikunja_qa.testing import conventions, state, traceability
from vikunja_qa.testing.ledger import Ledger

_WIRE_KEY = "vikunja_qa_ledger"

#: Markers a test declares itself. Matrix check markers are derived, not
#: declared, and registered from the catalogue in `pytest_configure`.
DECLARED_MARKERS: dict[str, str] = {
    "covers(*codes)": (
        "the coverage matrix checks a test provides, e.g. covers('ACL'); required on every "
        "product test outside a framework area"
    ),
    "finding(*ids)": "a defect this test pins down, e.g. finding('VKJ-007')",
    "advisory(*ids)": "a published vulnerability this test guards against, by CVE or GHSA id",
    "smoke": "critical path; the fast signal CI runs before the full suites",
    "generated": "derived from what the product publishes rather than written by hand",
}

RESILIENCE_LAYER = "resilience"


# --- configuration ----------------------------------------------------------


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("vikunja-qa")
    group.addoption(
        "--resilience",
        action="store_true",
        default=False,
        help="include the resilience layer, which stops stand containers; single process only",
    )
    group.addoption(
        "--fail-uncovered",
        metavar="PRIORITY",
        choices=traceability.PRIORITIES,
        default=None,
        help=(
            "fail the run when a coverage matrix check of this priority or a more important "
            "one ran no tests, e.g. P0; catches a test family that quietly stopped running"
        ),
    )


def pytest_configure(config: pytest.Config) -> None:
    for spec, description in DECLARED_MARKERS.items():
        config.addinivalue_line("markers", f"{spec}: {description}")
    for check in traceability.CHECKS.values():
        config.addinivalue_line(
            "markers",
            f"{check.marker}: derived from covers('{check.code}'), {check.title} "
            f"({check.priority})",
        )

    if config.getoption("resilience") and _is_distributed(config):
        raise pytest.UsageError(
            "--resilience stops containers the whole stand shares, so the layer cannot run "
            "alongside other tests; run it without -n"
        )

    config.stash[state.LEDGER] = Ledger()


def _is_distributed(config: pytest.Config) -> bool:
    """True on an xdist controller about to start workers. Workers
    themselves see `numprocesses` cleared, so this never fires inside one."""
    return bool(getattr(config.option, "numprocesses", None) or getattr(config.option, "tx", None))


def _link_url(config: pytest.Config, link_type: str, value: str) -> str:
    """The full URL for a report link to the matrix or to a finding.

    Built here because Allure applies `--allure-link-pattern` only inside its
    own decorators, which format the URL at import time. A link marker added
    during collection keeps whatever value it was given, so it has to be
    complete already. A pattern given on the command line still wins.
    """
    given = dict(getattr(config.option, "allure_link_pattern", None) or [])
    repository = get_settings().repository_url.rstrip("/")
    defaults = {
        "tms": f"{repository}/blob/main/docs/coverage-matrix.md#{{}}",
        "issue": f"{repository}/tree/main/docs/findings/{{}}",
    }
    pattern: str = given.get(link_type) or defaults[link_type]
    return pattern.format(value)


def pytest_report_header(config: pytest.Config) -> list[str]:
    settings = get_settings()
    resilience = "included" if config.getoption("resilience") else "left out (pass --resilience)"
    return [
        f"stand: {settings.base_url}, contracts {settings.contract_mode}",
        f"resilience layer: {resilience}",
    ]


# --- collection -------------------------------------------------------------

#: Where the suite lives, relative to the root directory pytest settles on.
TESTS_DIRECTORY = "tests"
FINDINGS_DIRECTORY = Path("docs") / "findings"


@pytest.hookimpl(wrapper=True)
def pytest_make_collect_report(
    collector: pytest.Collector,
) -> Generator[None, pytest.CollectReport, pytest.CollectReport]:
    """Refuse a module whose tests break the conventions, as a collection error.

    A collection error is the failure pytest and pytest-xdist both report
    cleanly. A single process stops before running anything. Under xdist
    the offending module contributes no tests, the rest still run, and the
    run ends red with the same message at the top of the summary. Raising
    from a later hook instead crashes xdist workers into an internal error
    that buries the message.
    """
    report = yield
    if not report.passed or not report.result:
        return report
    found = _violations_among(collector.config, report.result)
    if not found:
        return report
    return pytest.CollectReport(collector.nodeid, "failed", longrepr=_describe(found), result=[])


def _violations_among(
    config: pytest.Config, nodes: list[pytest.Item | pytest.Collector]
) -> dict[str, list[str]]:
    tests_root, findings_root = _roots(config)
    found: dict[str, list[str]] = {}
    for node in nodes:
        if not isinstance(node, pytest.Item):
            continue
        placement = traceability.place(node.path, tests_root)
        if placement is None or not placement.is_product_test:
            continue
        problems = conventions.violations(
            placement, conventions.Declarations.of(node), findings_root
        )
        if problems:
            listed = found.setdefault(_test_name(node), [])
            listed.extend(problem for problem in problems if problem not in listed)
    return found


def _describe(found: dict[str, list[str]]) -> str:
    blocks = [f"{name}\n    " + "\n    ".join(problems) for name, problems in found.items()]
    return "tests that do not follow the suite's conventions:\n\n" + "\n\n".join(blocks)


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Derive markers, labels and links for every product test, then leave the
    resilience layer out unless it was asked for.

    Runs before pytest's own `-m` and `-k` selection, so the derived markers
    are already there to select on. Every item reaching this hook has passed
    the convention check, because a module that failed it produced no items.
    """
    tests_root, findings_root = _roots(config)
    for item in items:
        placement = traceability.place(item.path, tests_root)
        if placement is None or not placement.is_product_test:
            continue
        declared = conventions.Declarations.of(item)
        if declared.codes:
            item.stash[state.DECLARED] = declared
        for code in declared.codes:
            item.add_marker(traceability.check(code).marker)
        _label(item, placement, declared, findings_root)

    _deselect_resilience(config, items, tests_root)


def _label(
    item: pytest.Item,
    placement: traceability.Placement,
    declared: conventions.Declarations,
    findings_root: Path,
) -> None:
    """Derive report labels and links, deferring to anything declared by hand."""
    by_hand = {mark.kwargs.get("label_type") for mark in item.iter_markers("allure_label")}

    def label(label_type: str, value: str) -> None:
        if label_type not in by_hand:
            item.add_marker(pytest.mark.allure_label(value, label_type=label_type))

    label("epic", placement.epic)
    if placement.feature:
        label("feature", placement.feature)
    label("story", placement.story)
    label("severity", traceability.severity_of(declared.codes))

    for code in declared.codes:
        check = traceability.check(code)
        item.add_marker(
            pytest.mark.allure_link(
                _link_url(item.config, "tms", check.anchor),
                link_type="tms",
                name=f"{code}: {check.title}",
            )
        )
    for finding in declared.findings:
        # A tag for every finding, so the report filters down to the tests
        # that pin known defects; a link only where there is a write-up to
        # open. A held finding has none yet, and a link to nowhere misleads.
        item.add_marker(pytest.mark.allure_label(finding, label_type="tag"))
        folder = traceability.finding_folder(finding, findings_root)
        if folder is not None:
            item.add_marker(
                pytest.mark.allure_link(
                    _link_url(item.config, "issue", folder), link_type="issue", name=finding
                )
            )
    for advisory in declared.advisories:
        item.add_marker(
            pytest.mark.allure_link(
                traceability.advisory_url(advisory), link_type="link", name=advisory
            )
        )


def _deselect_resilience(config: pytest.Config, items: list[pytest.Item], tests_root: Path) -> None:
    if config.getoption("resilience"):
        return
    kept: list[pytest.Item] = []
    dropped: list[pytest.Item] = []
    for item in items:
        placement = traceability.place(item.path, tests_root)
        in_layer = placement is not None and placement.layer == RESILIENCE_LAYER
        (dropped if in_layer else kept).append(item)
    if dropped:
        config.hook.pytest_deselected(items=dropped)
        items[:] = kept


def _roots(config: pytest.Config) -> tuple[Path, Path]:
    return config.rootpath / TESTS_DIRECTORY, config.rootpath / FINDINGS_DIRECTORY


def _test_name(item: pytest.Item) -> str:
    """The node id without parameters: one entry per test function, however
    many cases it was parametrised into."""
    original: str | None = getattr(item, "originalname", None)
    if not original or original == item.name:
        return item.nodeid
    return item.nodeid[: len(item.nodeid) - len(item.name)] + original


# --- running ----------------------------------------------------------------


@pytest.hookimpl(wrapper=True)
def pytest_runtest_call(item: pytest.Item) -> Generator[None, Any, Any]:
    """Count a test against the checks it covers once its body has run.

    Passing, failing and expected failures all count: each exercised the
    check. A test that skipped itself exercised nothing and does not.
    """
    declared = item.stash.get(state.DECLARED, None)
    try:
        result = yield
    except pytest.skip.Exception:
        raise
    except BaseException:
        _count(item, declared)
        raise
    _count(item, declared)
    return result


def _count(item: pytest.Item, declared: conventions.Declarations | None) -> None:
    if declared is not None:
        item.config.stash[state.LEDGER].record_test(declared.codes, generated=declared.generated)


def pytest_sessionfinish(session: pytest.Session) -> None:
    config = session.config
    ledger = config.stash.get(state.LEDGER, None)
    if ledger is None:
        return
    _absorb_validator(config, ledger)
    workeroutput = getattr(config, "workeroutput", None)
    if workeroutput is not None:
        workeroutput[_WIRE_KEY] = ledger.to_wire()
        return
    _apply_coverage_gate(session, ledger)


def _apply_coverage_gate(session: pytest.Session, ledger: Ledger) -> None:
    """Turn a green run red when a required check ran no tests at all.

    Runs on the controller, after every worker's ledger has been merged, and
    only changes a run that would otherwise pass: an existing failure is
    already the more useful signal.
    """
    priority = session.config.getoption("fail_uncovered")
    if not priority:
        return
    missing = traceability.uncovered(ledger.covered, down_to=priority)
    if not missing:
        return
    session.config.stash[state.UNCOVERED] = missing
    if session.exitstatus == pytest.ExitCode.OK:
        session.exitstatus = pytest.ExitCode.TESTS_FAILED


def _absorb_validator(config: pytest.Config, ledger: Ledger) -> None:
    """Fold the contract validator's picture into the ledger, once."""
    validator = config.stash.get(state.VALIDATOR, None)
    if validator is not None:
        ledger.absorb_contracts(validator.snapshot())
        del config.stash[state.VALIDATOR]


@pytest.hookimpl(optionalhook=True)
def pytest_testnodedown(node: Any, error: Any) -> None:  # noqa: ARG001 - hook signature
    """On the xdist controller: merge what one worker learned."""
    data = getattr(node, "workeroutput", {}).get(_WIRE_KEY)
    if data:
        node.config.stash[state.LEDGER].merge(Ledger.from_wire(data))


# --- reporting --------------------------------------------------------------


def pytest_terminal_summary(
    terminalreporter: pytest.TerminalReporter, config: pytest.Config
) -> None:
    if hasattr(config, "workerinput"):
        return
    ledger = config.stash.get(state.LEDGER, None)
    if ledger is None:
        return
    _absorb_validator(config, ledger)
    if not ledger.is_empty:
        _report_contracts(terminalreporter, ledger)
        _report_traceability(terminalreporter, ledger)
    _report_coverage_gate(terminalreporter, config)


def _report_contracts(reporter: pytest.TerminalReporter, ledger: Ledger) -> None:
    coverage = ledger.operation_coverage()
    if not coverage:
        return
    reporter.write_sep("-", "contract coverage")
    for label, (exercised, described) in coverage.items():
        percent = round(100 * exercised / described) if described else 0
        reporter.write_line(f"  {label}: {exercised}/{described} operations exercised ({percent}%)")
    if ledger.accepted:
        known = ", ".join(f"{name} x{count}" for name, count in sorted(ledger.accepted.items()))
        reporter.write_line(f"  known deviations seen: {known}")

    # The baseline may only shrink, so an entry nothing hits is a candidate for
    # deletion. Said per run rather than as a verdict: a partial run naturally
    # misses most of them, and only a full one is evidence.
    unseen = [finding for finding in Baseline().findings if finding not in ledger.accepted]
    if unseen:
        reporter.write_line(f"  baseline entries not seen in this run: {', '.join(unseen)}")

    distinct = ledger.distinct_violations()
    if not distinct:
        reporter.write_line("  no new contract violations")
        return
    reporter.write_sep("-", f"NEW contract violations ({len(distinct)})")
    for violation in distinct:
        reporter.write_line(
            f"  [{violation.get('spec')}] {violation.get('operation')} -> "
            f"{violation.get('status')}: {violation.get('kind')}"
        )
        reporter.write_line(f"    {violation.get('detail')}")


def _report_traceability(reporter: pytest.TerminalReporter, ledger: Ledger) -> None:
    if not ledger.executed:
        return
    reporter.write_sep("-", "coverage matrix, this run")
    reporter.write_line(f"  {'code':<5} {'check':<44} {'priority':<9} tests")
    for code, check in traceability.CHECKS.items():
        count = ledger.covered.get(code, 0)
        note = "   none ran" if count == 0 else ""
        reporter.write_line(f"  {code:<5} {check.title:<44} {check.priority:<9} {count:>5}{note}")
    reporter.write_line(
        f"  {ledger.generated} of {ledger.executed} matrix-bound tests were generated "
        "from the product's own descriptions"
    )


def _report_coverage_gate(reporter: pytest.TerminalReporter, config: pytest.Config) -> None:
    missing = config.stash.get(state.UNCOVERED, None)
    if not missing:
        return
    priority = config.getoption("fail_uncovered")
    reporter.write_sep("=", f"coverage gate {priority} failed", red=True, bold=True)
    for check in missing:
        reporter.write_line(f"  {check.code} ({check.priority}) {check.title}: no test ran")
    reporter.write_line(
        "  a family that errors or skips at collection shows up here first; "
        "look for SKIPPED lines above"
    )
