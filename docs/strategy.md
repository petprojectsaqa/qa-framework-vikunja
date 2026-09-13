# Strategy and architecture

English | [Русский](strategy.ru.md)

This document answers "how it is built". The [coverage matrix](coverage-matrix.md) answers "what is checked". They are meant to be read together.

Every decision below was made for this particular system under test, and most rest on facts taken from its source. Where a decision is arguable, the rejected alternative is named along with the reason. That is deliberate: the document has to survive the question "why not the other way".

---

## 1. Isolation, the decision everything else follows from

The system under test is one running application over one database. Tests have to run in parallel without disturbing each other. There are four ways to do that, and the choice decides the rest of the design.

**Rejected: truncating the database between tests.** The product has a testing API that empties every table. Tempting, and fatal to parallelism: while one test clears the database, every other test loses its data.

**Rejected: rolling back a transaction.** The classic unit-test trick does not apply, because the application is a separate process with its own connection pool. Our transaction is invisible to it.

**Rejected: separating by name.** Weak isolation that rests on the discipline of filtering, and collapses at the first mistake in a query.

**Chosen: isolation by ownership.** In Vikunja everything belongs to a user: projects are created by a user, tasks live inside projects, permissions are granted by the owner. Two tests running as different users physically cannot see each other's data. Isolation becomes a property of the construction rather than of the cleanup.

Every test gets fresh accounts by default, created through the ordinary registration endpoint, mail confirmation included, because the stand runs with the mailer on.

The consequences, taken honestly:

- Registration costs one round trip per actor in a test. That is the price of isolation, and it is accepted knowingly. If a measurement ever shows it to be the bottleneck, that is when to optimise it.
- **The generated families share one account for the whole run.** They are read-only and there are hundreds of them; minting accounts there would buy nothing.
- Cleanup between tests is not needed at all. Nothing is deleted, so after a red run the data that produced it is still there to look at.

**What ownership cannot isolate.** The list of all users, metrics counters, global configuration, instance-administrator actions and rate limiting are shared by everyone. In practice only one group in the suite touches that shared state today, the resilience layer, and it runs on its own.

**The rule for metrics.** Counters are global, so assertions about them are built on the difference measured around an action. Absolute values are not asserted.

---

## 2. The product's testing API

The product exposes two testing endpoints, switched on by a secret in its configuration: empty every table, and fill one table with given contents.

The rule for using them is strict, because the temptation is large.

**Allowed in two cases.** One: a single reset before a run begins. Two: preparing states the public API cannot reach, such as an already-expired token, a user with the instance-administrator flag, or a row dated in the past.

**Forbidden everywhere else.** Ordinary data is prepared through the public API only. The reason is not stylistic: a test that assembles state behind the product's back is testing its own idea of the schema rather than the product. It breaks at the first migration and finds no real defects.

**What the suite actually uses, today: the first case and nothing else.** `scripts/check_stand.py` empties every table once, before a run begins, in a function called `reset_the_stand` that says in its own name and in its output that it is destructive. No test touches those endpoints. The second allowance has not been needed yet, because everything the suite has wanted so far has been reachable through the public API; it stays written down here because the day it is needed, the rule for it should already exist.

The other half of the rule is a guard rather than a habit. The generated sweep walks every operation both descriptions publish, and two of those operations are exactly these — so `contracts/sweep.py` names them in `NEVER_CALL` and matches them by shape rather than by parameter name, because a description that renames `{table}` must not be able to turn the sweep into a reset.

---

## 3. Layers

The framework is a stack with a one-way dependency. Reaching upwards is an architectural defect.

```
tests                 assertions, and nothing else
  ↓
vikunja_qa.testing    the pytest side: fixtures, conventions, the plugin
  ↓
scenes                declarative construction of state
  ↓
actors                an identity, its credential, and clients bound to it
  ↓
clients               typed clients per area of the API, and the CalDAV door
  ↓
transport             HTTP, reporting, contract validation
  ↓
config, domain        settings, and the product's own vocabulary
```

Page objects stand to the side and rest on the same layers, because they prepare data through API calls rather than through clicks.

The rules, each of them checked:

- **No test speaks HTTP directly.** A test reaches the product through clients, so every call is stamped with a credential, recorded in the report and validated against the contract.
- **Nothing below the tests asserts.** A client returns an answer; deciding whether it is right belongs to a test. An assertion further down turns a product defect into a framework error, in the wrong file, with the wrong message.
- **A page object contains no assertions.** It knows how to act on a page and how to read it; the test judges.
- **The transport layer knows no domain.** It has never heard of tasks or projects.
- **Only `vikunja_qa.testing` knows about pytest.** Everything else stays usable from a plain script, which is how the reproduction scripts and the stand check work.

These are not prose. `tests/unit/test_layers.py` parses the source and fails the build when an arrow points the wrong way. An architecture described only in words comes apart in the third month.

---

## 4. The actor as an object

The central abstraction. An actor ties together an identity, the credential that proves it, and the clients bound to that credential.

The product supports four independent ways to prove identity, and the access matrix needs all four:

| Way | How it is obtained | Where it is used |
|---|---|---|
| Session token | trading a username and password | most of the suite |
| API token | issued in settings, `tk_` plus forty characters | the scope matrix |
| Link share token | trading a hash, with a password where required | link access checks |
| HTTP Basic | username and secret in the header | the calendar protocol |

The default session token lives for three days, so a token minted at the start of a run stays valid for all of it.

A test does not assemble an actor by hand. It names a role, and the factory builds the whole graph: the owner, the project, a second registered user, the grant, and a team if the role needs one.

`actor.using(credential)` is the same identity arriving a different way, which is what turns the access matrix into a table rather than a pile of near-identical tests.

---

## 5. Building state

A suite of this size stays readable only if setup is declared rather than programmed.

Instead of dozens of small fixtures there is one scene builder. A test describes the world it wants in a single chain; the builder performs the calls in the right order and hands back one object through which every actor and every created entity is reachable.

```python
world = scene.project().member("reader", Permission.READ).task().done()
```

What the builder guarantees:

- **The same description gives the same structure**, differing only in identifiers.
- **Nothing is created that the test did not ask for.**
- **Every construction step appears in the report as its own line**, so when setup breaks it is obvious that setup broke, and where.
- **Names carry provenance.** Every generated name holds the test's identifier and the worker's number, so a row left in the database after a red run points back at the test that made it.

Failing to build the world raises `SetupError` rather than an assertion, because it means the thing the test intended to check was never reached.

---

## 6. Contract validation as a side effect

The usual approach is a separate suite of contract tests. This one does it differently.

**Every response to every call in every test is validated against the schema for its operation, in the transport layer.** No contract tests are written: contract coverage arises as a by-product of any interaction with the product.

The descriptions are fetched from the running instance rather than from the product's repository, so the build that is actually up is the build that is checked. v1 serves Swagger 2.0; v2 serves OpenAPI 3.1, generated on the fly.

Deviations that are already written up live in a baseline, with the finding they belong to. The suite runs strict: a mismatch that is not in the baseline fails the test that produced it. The baseline exists so that what is already known does not drown out what is new, and **it may only shrink**. The end of a run prints the baseline entries nothing hit, which is how one entry was found to be describing a defect the product no longer has.

A by-product worth having: **operation coverage is counted from calls actually made**, not from intentions.

---

## 7. Waiting for the asynchronous

There is not one fixed pause standing in for a wait. The rule is enforced, not requested: `tests/unit/test_layers.py` fails the build on `time.sleep` in the suite.

Instead there is `wait_until`, which polls a condition with a deadline and a growing interval. Every use states its budget and, in the `because` argument, what it is waiting for, so a timeout explains itself instead of reporting that time ran out.

The reason for the strictness is simple. A two-second pause is both slower and less reliable than a wait: on a fast machine it wastes the difference, on a loaded one it still flakes.

**The one exception, named rather than hidden.** The mail resilience module is allowed a real sleep, because it has to let a timer inside the product elapse, and a timer is not something a poll can observe. It is the only file on the allowlist, and the allowlist is in the test.

---

## 8. Assertions

Three requirements for every assertion in the suite.

**Full context in the message.** Every response knows how to describe itself: method, URL, the credential used, what was sent, the status, the domain error code and the body. An assertion that fails prints all of it, so the first look at a failure is usually the last one needed.

**The failure names the thing, not the shape.** Messages say what the product did and why that is wrong, in the product's vocabulary.

**The report carries the evidence.** Request and response bodies are attached to every step, and a failing browser test attaches the screen and the page source as well.

Separately: the status code and the domain error code are checked together. Asserting a status alone is weak, because 400 is returned for dozens of reasons.

---

## 9. Running in parallel

Everything runs in parallel by default, because ownership isolation allows it. The api layer runs on eight workers and the browser layer on four.

The exception is the resilience layer, which stops containers the whole stand shares. It cannot be confined to the test that caused it, so it never joins the main run, and the plugin refuses `--resilience` together with `-n` rather than trusting anyone to remember.

Contract coverage is gathered per worker and merged on the controller, so the summary at the end of a run is the whole run rather than one worker's share.

---

## 10. The flakiness policy

The position is deliberate, and it is in the README because the position itself says something.

- **The api layer gets no retries at all.** Zero. An API test that flickers is either a defective test or a real race in the product. Both need investigating, not repeating.
- **The browser layer gets exactly one rerun**, and the rerun records a trace. The retry is a diagnostic instrument, not a way to reach green.
- **A test that needed the rerun gets fixed or deleted.** There is no third option.

---

## 11. Reporting

Report steps are generated at the client level rather than written into tests. Hand-placed steps clutter a test and always fall behind the code.

Labels are derived, not declared. A test's location gives its epic, feature and story; the matrix checks it declares give its severity and a link to the matrix row; a `finding` or `advisory` marker adds the link to the write-up or the advisory. That gives traceability in both directions, from a matrix row to the tests and back, and it cannot drift, because one side is computed from the other.

Attachments go through one place, `vikunja_qa.reporting`, which is silent when no test is running. That is not a nicety: attaching to Allure outside a test raises, and for a while it was silently skipping an entire generated family at collection time.

---

## 12. The framework's own quality

A testing tool with no tests of its own is a joke, and the reviewer notices first.

The unit layer covers the parts where a mistake would be invisible: specification loading and matching, the baseline, the waiting helper, the iCalendar reader and writer, the generators behind the scope and sweep families, the traceability catalogue, the conventions, the ledger that crosses process boundaries, and the transport, exercised against a canned adapter so the real client runs its real code with no network.

Three of them check the repository rather than the code: the layering, the documentation against the suite it describes, and the conventions, applied by running the plugin against small throwaway test trees with pytest's own `pytester`.

**The unit layer runs with outgoing connections refused.** A test that quietly starts depending on a live service fails at once and says so, rather than passing on a developer's machine and failing in the job that has no stand.

---

## 13. The stand

Eight containers: the application, PostgreSQL, Redis, MinIO, a mail trap, a webhook receiver, Prometheus and Grafana.

The stand differs from a production deployment deliberately:

- Rate limiting is switched off, and the three pre-authentication floors are raised besides, because that floor ignores the global switch and a parallel run walks straight into it.
- The testing API is enabled by its secret.
- Files go to object storage rather than to disk, so the more complicated path is the one under test.
- Mail goes to the trap, and registration really does go through the confirmation link.
- CalDAV is on, which is the product's default.

A run does not start until `scripts/check_stand.py` says the stand is ready. It walks one real user path end to end, so a green result means something, and it uses the standard library only, because it runs before the project's dependencies necessarily exist.

---

## 14. The build

Seven jobs, split by speed and by what they need.

| Job | What it does | Needs a stand |
|---|---|---|
| style, types, layers | ruff, ruff format, mypy | no |
| the framework's own tests | the unit layer | no |
| smoke | the critical path across both layers | yes |
| api suite | the main run, eight workers, P0 coverage gate | yes |
| browser suite | Playwright, one rerun, traces on failure | yes |
| dependency outages | the resilience layer, on a schedule and on demand | yes |
| report | builds and publishes the Allure report | no |

The fast jobs come first and cut a broken change off in seconds. Smoke gates the two full suites. The resilience layer is not in the main chain at all.

---

## 15. The technology, and why

| What | Which | Why |
|---|---|---|
| language | Python | the author's language and the target audience's |
| dependencies | uv | speed and a reproducible lock |
| runner | pytest | the standard, with the plugin system this design leans on |
| parallelism | pytest-xdist | distribution, and a controller that can merge what workers learned |
| HTTP | requests | it covers everything needed here |
| settings | pydantic-settings | typed configuration from the environment |
| schemas | jsonschema | Draft 4 for Swagger 2.0 and 2020-12 for OpenAPI 3.1 |
| database | psycopg | direct queries for the integrity checks, read-only |
| browser | Playwright | its own factories, traces and videos, reused rather than rebuilt |
| report | Allure | readable results, and labels that can be derived |
| style and types | ruff, mypy | fast, strict, and the same locally as in CI |
| layering | the suite's own unit test | the architecture is enforced, not described |

---

## 16. The order it was built in

Chosen so that each step ends with something that works end to end, rather than with half of three layers.

1. **The stand and the settings.** Compose, the readiness gate, environment profiles.
2. **Transport and identity.** The client, reporting, four credentials, the actor.
3. **Contract validation inside transport.** Both descriptions loaded, every response validated.
4. **Area clients and the scene builder.** State becomes one line.
5. **The generated families.** Authorization, token scopes, the documented-operation sweep.
6. **The access matrix along the backbone.**
7. **Integrity through the database, and the asynchronous effects.**
8. **Consistency between the two API versions.**
9. **Regressions for published vulnerabilities.**
10. **The browser layer on top of the existing factories.**
11. **The resilience layer, on its own.**
12. **The calendar slice, the conventions plugin, the coverage gate, and the findings.**

The first four steps are the skeleton. After them the suite grows linearly, with no further architectural decisions to take.
