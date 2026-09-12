# Findings

English | [Русский](README.ru.md)

Defects this suite found in Vikunja v2.6.0.

Every finding reproduces in two minutes and asks for no trust in the author: each folder holds a Python script with no dependencies, importing nothing from the framework, which prints the result itself.

| Identifier | What it is | Severity | How it was found |
|---|---|---|---|
| [VKJ-001](VKJ-001-subscription-entity-type/) | the v1 description types `Subscription.entity` as an integer; the product sends a string | medium | contract validation |
| [VKJ-002](VKJ-002-v1-nullable-collections/) | the v1 description forbids `null` on collections the product returns as `null` when empty | medium | contract validation |
| [VKJ-003](VKJ-003-v2-residual-nullables/) | v2 fixed nullability nearly everywhere: four fields were left behind | low | contract validation |
| [VKJ-004](VKJ-004-undeclared-statuses/) | operations answer with statuses their description never mentions | low | contract validation |
| [VKJ-005](VKJ-005-permission-errors-carry-no-code/) | permission errors carry no domain code for a client to translate | medium | access matrix |
| VKJ-006 | held until the product's maintainers respond | low | access matrix |
| [VKJ-007](VKJ-007-label-update-verb/) | the v1 description documents label update with a verb the product rejects | high | operation sweep |
| [VKJ-008](VKJ-008-v2-auth-errors-wrong-format/) | v2 authorization errors arrive in a shape that version does not describe | high | operation sweep |
| [VKJ-009](VKJ-009-binary-endpoints-described-as-json/) | two v1 operations serving binary content declare `application/json` | low | comparing the two descriptions |
| [VKJ-010](VKJ-010-failed-upload-returns-200/) | a failed upload answers 200, with the failure hidden in the body | high | dependency outage |
| [VKJ-011](VKJ-011-redis-outage-hangs-every-request/) | with Redis gone, requests hang instead of failing | high | dependency outage |
| [VKJ-012](VKJ-012-calendar-home-get-500/) | GET on the CalDAV calendar home answers 500 with an empty body | low | CalDAV slice |
| [VKJ-013](VKJ-013-mail-daemon-stale-connection/) | after the mail server restarts, mail is lost until traffic pauses for 30 seconds | high | dependency outage |
| VKJ-014 | held until the product's maintainers respond | low | CalDAV slice |
| [VKJ-015](VKJ-015-simultaneous-task-creation-500/) | two tasks created in one project at the same moment: one caller gets a 500 | high | simultaneous writes |

## Running the reproductions

The stand has to be up:

```bash
docker compose -f docker/docker-compose.yml up -d --quiet-pull
```

Then one command for all of them:

```bash
py scripts/verify_findings.py
```

Or one finding:

```bash
py scripts/verify_findings.py VKJ-007
```

The runner finds the scripts relative to itself, so it works from any directory, checks that the stand answers, and prints one line per finding. If it finds no scripts, or the stand is silent, it says so out loud. A shell loop over a glob cannot: a pattern that matches nothing produces no output, which looks exactly like everything passing.

Each script also runs on its own, has no dependencies and imports nothing from the framework:

```bash
py docs/findings/VKJ-007-label-update-verb/reproduce.py
```

It prints what the product's description promises beside what the product does. Exit code zero means the finding still reproduces.

Three of them drive the stand's containers through `docker compose`, because that is what the finding is about: VKJ-010, VKJ-011 and VKJ-013. They put the container back in a `finally` block. The rest need nothing but the stand.

**About the interpreter's name.** In PowerShell on Windows, `python` leads to a Microsoft Store stub that does not run; the real interpreter is `py`. In Git Bash and on Linux, `python` works.

## The duplicate check

Before reporting anything, the product's tracker was searched for matches. The result:

- **VKJ-001 partly overlaps [issue #3316](https://github.com/go-vikunja/vikunja/issues/3316)**, closed on 29 July 2026. The same root cause was fixed there for the second version of the API. The first version's description was left as it was, so the finding stands, but it should be reported as a continuation of a closed issue rather than as something new.
- **VKJ-013 is adjacent to [issue #48](https://github.com/go-vikunja/vikunja/issues/48)**, closed, which reported the same log line, `not connected to SMTP server`, from the connection-closing path while mail was still being delivered. The loss of messages after a restart is not in that report.
- The rest have no match in the tracker. The searches covered the API description, the error format, statuses 401, 403, 404 and 405, field nullability, parse failures in generated clients, CalDAV, mail delivery after an outage, and the unique constraint behind VKJ-015.
- Version 2.6.0 was the latest release at the time of the check, so everything here applies to the current one.

## Status: not filed in the tracker

The findings are deliberately not raised as issues. The reason is the project's contribution rules, described below: they are reasonable, and following them for fourteen reports costs more time than it is worth right now. Short drafts are written and sit in a backlog.

That does not affect what the findings are worth. Each is confirmed by running one command against a clean stand, so a reader needs nobody's approval to believe it.

## The project's contribution rules

Vikunja's `CONTRIBUTING.md` has a section on AI participation, and it frames any report made with one:

- generated bug reports are not accepted; report only what you reproduced yourself;
- keep it short, because generated prose usually runs long;
- disclose AI involvement;
- vulnerabilities only when verified against a current version, and through their procedure.

So the detailed write-ups in this folder are for a reader of this repository, not for the tracker. What goes to a tracker is short, and every reproduction is run by hand before it is sent.

## About the two held findings

VKJ-006 and VKJ-014 both concern an authorization boundary, so by the rule adopted here their details are not published until the product's maintainers have responded.

Both are low severity: nothing leaks but the existence of an identifier, behaviour that is common in APIs and sometimes chosen deliberately. The private notice is about procedure, not danger.

VKJ-006 is pinned in the suite by two tests in `tests/api/authorization/test_existence_disclosure.py`, marked as expected failures: they state the position without breaking the build, and turn into an unexpected pass if the product changes its behaviour. VKJ-014 has no folder and no test here at all, because the product's own source says plainly that the thing it leaks was meant to stay hidden.

## How this is wired

Known deviations are recorded in a baseline (`src/vikunja_qa/contracts/baseline.py`) with the reason and the finding they belong to. The suite runs strict: a deviation that is not in the baseline fails the test that produced it. The baseline exists only so that what is already written up does not drown out what is new, and it may only shrink. The end of a run prints the entries nothing hit, which is how one was found to be describing a defect the product no longer has.

Expected failures are used for positions the suite states but does not treat as proven defects. Asserting the current behaviour there would be wrong: it would freeze disputed behaviour into the suite as though it were intended.
