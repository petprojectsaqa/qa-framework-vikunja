"""The suite's plugin, run for real against small throwaway test trees.

Each test builds a miniature repository with pytest's own `pytester`, runs
pytest on it with the plugin switched on, and reads the outcome the way a
person would: exit code, summary and output. Nothing here needs the stand;
the miniature tests never touch the network.

Most runs happen in-process, which is quick. The ones that need pytest-xdist
or Allure run in a subprocess, because both keep state that must not leak
into the session running these tests. pytest-playwright is switched off in
the miniatures: they open no browser, and its soft-assertion scope is a
global that cannot nest inside the session running these tests.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vikunja_qa.testing import traceability

PLUGIN = ("-p", "vikunja_qa.testing.plugin")

#: One test covering every P0 check, so a coverage gate at P0 can pass.
ALL_P0 = ", ".join(
    repr(check.code) for check in traceability.CHECKS.values() if check.priority == "P0"
)


@pytest.fixture
def repo(pytester: pytest.Pytester) -> pytest.Pytester:
    """A root with the suite's shape: tests/<layer>/<area>/ and docs/findings."""
    pytester.makepyprojecttoml(
        "[tool.pytest.ini_options]\n"
        'addopts = "-p no:cacheprovider -p no:playwright --strict-markers"\n'
    )
    (pytester.path / "docs" / "findings" / "VKJ-001-something-real").mkdir(parents=True)
    return pytester


def _write(repo: pytest.Pytester, relative: str, source: str) -> Path:
    path = repo.path / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    return path


# --- conventions --------------------------------------------------------------


def test_a_product_test_that_covers_nothing_is_refused_before_anything_runs(
    repo: pytest.Pytester,
) -> None:
    _write(repo, "tests/api/area/test_bare.py", "def test_nothing():\n    pass\n")
    _write(
        repo,
        "tests/api/area/test_fine.py",
        "import pytest\n\n@pytest.mark.covers('ACL')\ndef test_fine():\n    pass\n",
    )

    result = repo.runpytest(*PLUGIN)

    assert result.ret == pytest.ExitCode.INTERRUPTED
    result.stdout.fnmatch_lines(
        [
            "*tests that do not follow the suite's conventions*",
            "*test_bare.py::test_nothing",
            "*declares no matrix check*",
        ]
    )
    result.assert_outcomes(errors=1)


def test_a_harness_test_and_a_unit_test_need_no_matrix_check(repo: pytest.Pytester) -> None:
    _write(repo, "tests/api/framework/test_harness.py", "def test_harness():\n    pass\n")
    _write(repo, "tests/unit/test_pure.py", "def test_pure():\n    pass\n")

    result = repo.runpytest(*PLUGIN)

    result.assert_outcomes(passed=2)


def test_convention_errors_read_the_same_under_xdist(repo: pytest.Pytester) -> None:
    """Raised from a later hook, the same refusal crashed xdist workers into
    an internal error. As a collection error it reads cleanly."""
    _write(
        repo,
        "tests/api/area/test_bad.py",
        "import pytest\n\n@pytest.mark.finding('VKJ-999')\n"
        "@pytest.mark.covers('ACL')\ndef test_bad():\n    pass\n",
    )

    result = repo.runpytest_subprocess(*PLUGIN, "-n", "2")

    assert result.ret != pytest.ExitCode.OK
    result.stdout.fnmatch_lines(["*names finding VKJ-999, which has no folder*"])
    assert "INTERNALERROR" not in result.stdout.str()


# --- selection ----------------------------------------------------------------


def test_matrix_markers_are_derived_and_select_like_declared_ones(repo: pytest.Pytester) -> None:
    _write(
        repo,
        "tests/api/area/test_mixed.py",
        "import pytest\n\n"
        "@pytest.mark.covers('ACL')\ndef test_access():\n    pass\n\n"
        "@pytest.mark.covers('INT')\ndef test_integrity():\n    pass\n",
    )

    result = repo.runpytest(*PLUGIN, "-m", "acl")

    result.assert_outcomes(passed=1, deselected=1)


def test_the_resilience_layer_runs_only_when_asked(repo: pytest.Pytester) -> None:
    _write(
        repo,
        "tests/resilience/deps/test_outage.py",
        "import pytest\n\n@pytest.mark.covers('RES')\ndef test_outage():\n    pass\n",
    )

    left_out = repo.runpytest(*PLUGIN)
    asked = repo.runpytest(*PLUGIN, "--resilience")

    left_out.assert_outcomes(deselected=1)
    left_out.stdout.fnmatch_lines(["resilience layer: left out (pass --resilience)"])
    asked.assert_outcomes(passed=1)


def test_asking_for_the_resilience_layer_leaves_everything_else_out(
    repo: pytest.Pytester,
) -> None:
    """The other half of the same rule, and the half that was missing.

    A container stopped for one test is stopped for every test sharing the
    stand. The flag refused `-n` from the start, but `testpaths` means a bare
    `pytest --resilience` collected the whole suite and ran it around the
    outage.
    """
    _write(
        repo,
        "tests/resilience/deps/test_outage.py",
        "import pytest\n\n@pytest.mark.covers('RES')\ndef test_outage():\n    pass\n",
    )
    _write(
        repo,
        "tests/api/area/test_ordinary.py",
        "import pytest\n\n@pytest.mark.covers('ACL')\ndef test_ordinary():\n    pass\n",
    )
    _write(repo, "tests/unit/test_pure.py", "def test_pure():\n    pass\n")

    result = repo.runpytest(*PLUGIN, "--resilience")

    result.assert_outcomes(passed=1, deselected=2)


def test_a_module_sitting_directly_in_tests_is_refused(repo: pytest.Pytester) -> None:
    """`tests/test_x.py` names no layer, so nothing could place it, and it
    used to be treated like a file from outside the suite: no area, no
    matrix check, no labels, and green."""
    _write(repo, "tests/test_loose.py", "def test_loose():\n    pass\n")

    result = repo.runpytest(*PLUGIN)

    assert result.ret == pytest.ExitCode.INTERRUPTED
    result.stdout.fnmatch_lines(["*sits directly in tests/; move it under a layer directory*"])


def test_the_resilience_layer_refuses_to_run_in_parallel(repo: pytest.Pytester) -> None:
    result = repo.runpytest(*PLUGIN, "--resilience", "-n", "2")

    assert result.ret == pytest.ExitCode.USAGE_ERROR
    result.stderr.fnmatch_lines(["*cannot run alongside other tests; run it without -n*"])


# --- the coverage gate --------------------------------------------------------


def test_the_coverage_gate_turns_a_green_run_red(repo: pytest.Pytester) -> None:
    _write(
        repo,
        "tests/api/area/test_some.py",
        "import pytest\n\n@pytest.mark.covers('ACL')\ndef test_access():\n    pass\n",
    )

    result = repo.runpytest(*PLUGIN, "--fail-uncovered", "P0")

    assert result.ret == pytest.ExitCode.TESTS_FAILED
    result.assert_outcomes(passed=1)
    result.stdout.fnmatch_lines(["*coverage gate P0 failed*", "*SCP (P0) API token scopes hold*"])


def test_the_coverage_gate_passes_when_every_required_check_ran(repo: pytest.Pytester) -> None:
    _write(
        repo,
        "tests/api/area/test_all.py",
        f"import pytest\n\n@pytest.mark.covers({ALL_P0})\ndef test_everything():\n    pass\n",
    )

    result = repo.runpytest(*PLUGIN, "--fail-uncovered", "P0")

    assert result.ret == pytest.ExitCode.OK


def test_a_test_that_skips_itself_covers_nothing(repo: pytest.Pytester) -> None:
    """A family that skips at runtime must show up as a gap, not as coverage."""
    _write(
        repo,
        "tests/api/area/test_skipping.py",
        f"import pytest\n\n@pytest.mark.covers({ALL_P0})\n"
        "def test_everything():\n    pytest.skip('the stand could not be read')\n",
    )

    result = repo.runpytest(*PLUGIN, "--fail-uncovered", "P0")

    assert result.ret == pytest.ExitCode.TESTS_FAILED
    result.stdout.fnmatch_lines(["*coverage gate P0 failed*"])


def test_the_coverage_gate_says_nothing_about_a_run_that_collected_only(
    repo: pytest.Pytester,
) -> None:
    """Nothing ran, by request. Reporting every check as uncovered would be
    true and useless, and it exited 1 on a run that did what it was asked."""
    _write(
        repo,
        "tests/api/area/test_some.py",
        "import pytest\n\n@pytest.mark.covers('ACL')\ndef test_access():\n    pass\n",
    )

    result = repo.runpytest(*PLUGIN, "--fail-uncovered", "P0", "--collect-only")

    assert result.ret == pytest.ExitCode.OK
    assert "coverage gate" not in result.stdout.str()


@pytest.mark.parametrize("narrowing", [("-k", "access"), ("-m", "acl")])
def test_the_coverage_gate_refuses_a_run_that_was_filtered(
    repo: pytest.Pytester, narrowing: tuple[str, str]
) -> None:
    """The gate asks whether every check of a priority ran. A filtered
    selection cannot answer that, and answering it anyway made the flag
    report a regression on every ordinary `-k` run."""
    result = repo.runpytest(*PLUGIN, "--fail-uncovered", "P0", *narrowing)

    assert result.ret == pytest.ExitCode.USAGE_ERROR
    result.stderr.fnmatch_lines(["*was never going to answer that*"])


def test_a_rerun_counts_once(repo: pytest.Pytester) -> None:
    """The browser layer runs with `--reruns 1`, and a rerun replays the
    same item through the same hook. Counted twice, the matrix table showed
    numbers no reader could reconcile with the number of tests."""
    _write(
        repo,
        "tests/api/area/test_flaky.py",
        "import pytest\n\n@pytest.mark.covers('ACL')\ndef test_flaky():\n    assert False\n",
    )

    result = repo.runpytest_subprocess(*PLUGIN, "--reruns", "2")

    result.stdout.fnmatch_lines(["*ACL*Access matrix*P0*1"])


def test_a_failing_test_still_counts_as_having_exercised_its_check(repo: pytest.Pytester) -> None:
    _write(
        repo,
        "tests/api/area/test_failing.py",
        f"import pytest\n\n@pytest.mark.covers({ALL_P0})\n"
        "def test_everything():\n    assert False\n",
    )

    result = repo.runpytest(*PLUGIN, "--fail-uncovered", "P0")

    result.assert_outcomes(failed=1)
    assert "coverage gate" not in result.stdout.str()


# --- the contract gate --------------------------------------------------------

#: Puts a deviation the baseline does not know into the run's ledger, the way
#: a worker's validator would after the sweep met one.
DEVIATION = (
    "from vikunja_qa.testing import state\n\n\n"
    "def pytest_sessionstart(session):\n"
    "    session.config.stash[state.LEDGER].violations.append(\n"
    "        {{'spec': 'v1', 'operation': 'GET /tasks/{{id}}', 'status': 200,\n"
    "          'kind': 'schema mismatch', 'detail': {detail!r}}}\n"
    "    )\n"
)


def test_a_new_contract_deviation_turns_a_green_run_red(repo: pytest.Pytester) -> None:
    """The gate the documentation promised and the code did not have.

    In strict mode a deviation fails the test that produced it. But every
    generated family runs with contract checking set to record rather than
    fail, and those are the families that walk every published operation —
    so the deviations likeliest to be new were printed under a green run.
    """
    _write(repo, "conftest.py", DEVIATION.format(detail="labels: None is not of type 'array'"))
    _write(
        repo,
        "tests/api/area/test_fine.py",
        "import pytest\n\n@pytest.mark.covers('ACL')\ndef test_fine():\n    pass\n",
    )

    result = repo.runpytest(*PLUGIN)

    assert result.ret == pytest.ExitCode.TESTS_FAILED
    result.assert_outcomes(passed=1)
    result.stdout.fnmatch_lines(
        [
            "*NEW contract violations (1)*",
            "*1 new contract deviation*",
        ]
    )


def test_two_deviations_on_one_operation_are_both_reported(repo: pytest.Pytester) -> None:
    """The report is deduplicated for reading, and the detail is part of what
    makes a deviation distinct. Left out of that key, two different
    mismatches on one operation collapsed into one line and the count above
    them said one where there were two."""
    both = DEVIATION.format(detail="labels: None is not of type 'array'").replace(
        "    )\n",
        "    )\n"
        "    session.config.stash[state.LEDGER].violations.append(\n"
        "        {'spec': 'v1', 'operation': 'GET /tasks/{id}', 'status': 200,\n"
        "         'kind': 'schema mismatch', 'detail': \"id: 'seven' is not of type 'integer'\"}\n"
        "    )\n",
    )
    _write(repo, "conftest.py", both)
    _write(repo, "tests/unit/test_pure.py", "def test_pure():\n    pass\n")

    result = repo.runpytest(*PLUGIN)

    result.stdout.fnmatch_lines(["*NEW contract violations (2)*"])


# --- reporting ----------------------------------------------------------------


def test_worker_ledgers_are_merged_into_one_summary(repo: pytest.Pytester) -> None:
    """Printed from one worker, the table showed that worker's share and
    called it the total."""
    tests = "".join(
        f"@pytest.mark.covers('ACL')\ndef test_{number}():\n    pass\n\n" for number in range(6)
    )
    _write(repo, "tests/api/area/test_many.py", f"import pytest\n\n{tests}")

    result = repo.runpytest_subprocess(*PLUGIN, "-n", "3")

    result.assert_outcomes(passed=6)
    result.stdout.fnmatch_lines(["*ACL*Access matrix*P0*6"])


def test_report_labels_and_links_are_derived_from_placement_and_declarations(
    repo: pytest.Pytester,
) -> None:
    _write(
        repo,
        "tests/api/side_effects/test_mail.py",
        "import pytest\n\n"
        "@pytest.mark.covers('ASY', 'CVE')\n"
        "@pytest.mark.finding('VKJ-001')\n"
        "@pytest.mark.advisory('CVE-2026-35601')\n"
        "def test_sends():\n    pass\n",
    )
    results = repo.path / "allure-results"

    outcome = repo.runpytest_subprocess(*PLUGIN, f"--alluredir={results}")

    outcome.assert_outcomes(passed=1)
    (written,) = [
        json.loads(path.read_text(encoding="utf-8")) for path in results.glob("*-result.json")
    ]
    labels = {(label["name"], label["value"]) for label in written["labels"]}
    assert {
        ("epic", "API"),
        ("feature", "Side effects"),
        ("story", "Mail"),
        ("severity", "critical"),
        ("tag", "VKJ-001"),
        ("tag", "asy"),
        ("tag", "cve"),
    } <= labels
    links = {(link["type"], link["name"], link["url"]) for link in written["links"]}
    repository = "https://github.com/petprojectsaqa/qa-framework-vikunja"
    assert (
        "tms",
        "ASY: Asynchronous side effects",
        f"{repository}/blob/main/docs/coverage-matrix.md#asy",
    ) in links
    assert (
        "issue",
        "VKJ-001",
        f"{repository}/tree/main/docs/findings/VKJ-001-something-real",
    ) in links
    assert (
        "link",
        "CVE-2026-35601",
        "https://nvd.nist.gov/vuln/detail/CVE-2026-35601",
    ) in links
