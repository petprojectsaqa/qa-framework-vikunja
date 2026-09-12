"""Root of the suite.

Deliberately almost empty. Fixtures and conventions are part of the
framework and live in `vikunja_qa.testing`, where they are importable,
typed and documented once; this file only switches them on.

Layout, and why it is split the way it is:

    tests/unit/          the framework testing itself; runs with the stand off
    tests/api/<area>/    product tests over HTTP and CalDAV
    tests/ui/<area>/     product tests through a browser
    tests/resilience/    product tests that take a dependency away

The top level is the execution layer, because layers differ in what they
need to run: nothing, a stand, a browser, control over containers. Those
differences decide fixtures, CI jobs and retry policy, so they belong in
the filesystem. The second level is the capability under test. What cuts
across both is a marker, since no single directory can express an overlap:
`smoke` is declared, and one marker per coverage matrix check, such as
`acl` or `cve`, is derived from `covers(...)`.

`pytester` is pytest's own harness for testing plugins. The unit layer
uses it to run the suite's plugin against small throwaway test trees, and
it has to be switched on here, in the top-level conftest, or not at all.
"""

pytest_plugins = (
    "pytester",
    "vikunja_qa.testing.fixtures",
    "vikunja_qa.testing.plugin",
)
