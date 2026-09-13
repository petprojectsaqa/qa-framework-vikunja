# Coverage matrix

English | [Русский](coverage-matrix.ru.md)

System under test: Vikunja v2.6.0, run locally from `docker/docker-compose.yml`.

This document says what is checked, at which level, and why. Every test in the suite declares the checks it provides, the report links back to the rows below, and a check with no tests shows up in the run summary. The document and the suite cannot drift apart quietly: `tests/unit/test_documentation.py` fails the build if they do.

---

## 1. The principle everything follows

Multiplying 170 operations by 12 actors by 16 kinds of check gives tens of thousands of combinations, half of which check nothing. Coverage is split into two layers of a different nature instead.

**A wide, shallow layer, generated from the product's own descriptions.** Contract validation, the demand for a credential on every operation and the API token scope matrix apply to every operation automatically. Nothing there is written by hand, and a new endpoint in the product is covered the day it appears.

**A narrow, deep layer, written by hand along the backbone.** The backbone is the set of resources where the permission logic lives and where published vulnerabilities have landed. Only for those is there a full access matrix, database-level verification, and side-effect checking.

That split is the main decision in this document. It is also why a suite of roughly a thousand checks covers the product better than one of three thousand would.

---

## 2. The backbone

| Resource | Why it is on the backbone |
|---|---|
| project | the root of the permission model; everything else inherits from it |
| task | the main entity, its access computed through the project |
| attachment | where CVE-2026-33678 landed: reads keyed on a single identifier |
| comment | a nested resource with a permission check of its own |
| bucket and view | where CVE-2026-55065 landed: destroying someone else's board |
| link share | the link in the GHSA-2pv8-4c52-mf8j chain |
| api token | where CVE-2026-68581 landed: taking over someone else's tokens |
| team | the second route to access, beside a direct grant |
| relation | ties tasks across projects, a classic leak |
| reaction | a polymorphic endpoint with the entity type in the path |

Off the backbone: migrations, instance administration, stock photo backgrounds, avatars. Those get smoke coverage only.

---

## 3. The actors

| Code | Who | How it is obtained |
|---|---|---|
| `owner` | created the project | registration, then creation |
| `admin_member` | granted Admin | direct grant to a user |
| `write_member` | granted Write | direct grant to a user |
| `read_member` | granted Read | direct grant to a user |
| `team_write` | access through a team | membership of a team with Write |
| `outsider` | signed in, no relationship to the project | a separate registration |
| `anon` | no credential | a request with no header |
| `share_read` | public link, read | a hash traded for a token |
| `share_write` | public link, write | a hash traded for a token |
| `share_pwd` | link behind a password | a hash and a password traded for a token |
| `token_narrow` | an API token with one narrow permission | a token issued for a single area |
| `instance_admin` | instance administrator | not enumerated: see below |

Permission levels in the product: read is zero, write is one, admin is two, and there is a fourth state, "not determined", which is minus one. The model guards against an empty JSON value quietly becoming read access. The boundary of that field's parsing is checked separately.

Public links have two independent axes, the permission level and whether a password is set. Both are enumerated.

`instance_admin` is the one actor the matrix does not enumerate, and the reason is worth stating rather than hiding. The only route to that flag from outside the database is the product's table-filling testing endpoint, which replaces the contents of a table. Used on the user table it would destroy the accounts every other test is running under, so the suite does not reach for it. Administrator-only routes are still covered by the generated families, which demand a credential of every operation.

---

## 4. The checks <a id="checks"></a>

Each row is a kind of check. A test declares the ones it provides with `@pytest.mark.covers("ACL")`, which gives it the matching selection marker (`pytest -m acl`), a severity derived from the priority below, and a report link back to this row. "Tests" is what the suite runs today, counted from a full run.

| Code | Check | How | Priority | Tests |
|---|---|---|---|---|
| <a id="con"></a>`CON` | Responses match their contract | generated | P0 | 362 |
| <a id="aut"></a>`AUT` | Every operation demands a credential | generated | P0 | 366 |
| <a id="err"></a>`ERR` | Domain error codes are preserved | generated | P0 | 50 |
| <a id="scp"></a>`SCP` | API token scopes hold | generated | P0 | 37 |
| <a id="acl"></a>`ACL` | Access matrix | table-driven | P0 | 53 |
| <a id="int"></a>`INT` | Data integrity, verified in the database | hand-written | P0 | 6 |
| <a id="cve"></a>`CVE` | Regressions for published vulnerabilities | hand-written | P0 | 5 |
| <a id="fun"></a>`FUN` | Business rules | hand-written | P1 | 8 |
| <a id="neg"></a>`NEG` | Boundaries and invalid input | hand-written | P1 | 28 |
| <a id="asy"></a>`ASY` | Asynchronous side effects | hand-written | P1 | 6 |
| <a id="xvr"></a>`XVR` | Consistency across API versions | hand-written | P1 | 9 |
| <a id="ui"></a>`UI` | Behaviour only a browser can check | Playwright | P1 | 13 |
| <a id="cnc"></a>`CNC` | Concurrency and idempotency | hand-written | P2 | 5 |
| <a id="i18"></a>`I18` | Languages, time zones and formats | Playwright | P2 | 4 |
| <a id="dav"></a>`DAV` | Calendar protocol, a thin slice | hand-written | P2 | 16 |
| <a id="res"></a>`RES` | Behaviour when a dependency fails | separate run | P2 | 6 |

Priority reads as severity in the report: P0 is critical, P1 normal, P2 minor.

**Where the suite stands.** Every row has tests behind it, and none is a token. The generated families carry most of the count, which is the design working as intended rather than a distortion: they cover every operation the product publishes, and they cost nothing to maintain.

The api job runs with `--fail-uncovered P0`, so a P0 row falling to zero turns the build red. That is not hypothetical. `SCP` sat at zero for weeks without anyone noticing, because the family was skipped at collection by a `KeyError` one line long.

---

## 5. Coverage by area

Areas come from the tags in the v1 description. The number is the count of operations.

| Area | Ops | CON | AUT | ERR | SCP | ACL | FUN | NEG | INT | ASY | XVR | CVE | Priority |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| auth (6) | 6 | + | + | + | | | + | + | + | | + | | **P0** |
| user (27) | 27 | + | + | + | + | | + | + | + | + | | + | **P0** |
| project (23) | 23 | + | + | + | + | + | + | + | + | + | + | + | **P0** |
| task (26) | 26 | + | + | + | + | + | + | + | + | + | + | + | **P0** |
| sharing (14) | 14 | + | + | + | + | + | + | + | + | | + | + | **P0** |
| api (4) | 4 | + | + | + | + | + | + | + | + | | | + | **P0** |
| team (8) | 8 | + | + | + | + | + | + | + | + | | | | P1 |
| labels (9) | 9 | + | + | + | + | + | + | + | | | + | | P1 |
| assignees (4) | 4 | + | + | + | + | + | + | + | | + | | | P1 |
| webhooks (10) | 10 | + | + | + | + | + | + | + | | + | | | P1 |
| subscriptions (5) | 5 | + | + | + | + | | + | | | + | | | P2 |
| filter (4) | 4 | + | + | + | + | + | + | + | | | | | P2 |
| admin (8) | 8 | + | + | + | + | + | | | | | | | P2 |
| migration (19) | 19 | + | + | + | | | | | | | | | P3, smoke |

A `+` in a generated column (CON, AUT, ERR, SCP) is a fact: those families walk every operation, or every operation both versions describe. A `+` in a hand-written column is the intent for that area, and section 4 says how far the suite has got.

---

## 6. The access matrix

Built once as a table of data and executed as parameters. A row is a resource, an operation, an actor and the expected status.

One project is built once per module and reached through every route the product offers: a direct grant at each level, a team, a public read link, an outsider and an anonymous caller. The rows as the suite runs them today:

| Operation | owner | admin | writer | reader | teammate | share_read | share_write | share_pwd | token_narrow | outsider | anon |
|---|---|---|---|---|---|---|---|---|---|---|---|
| read the task | 200 | 200 | 200 | 200 | 200 | 200 | 200 | 200 | 200 | 403 | 401 |
| update the task | 200 | 200 | 200 | 403 | 200 | 403 | 200 | 403 | 401 | 403 | 401 |
| delete the task | 200 | 200 | 200 | 403 | 200 | 403 | 200 | 403 | 401 | 403 | 401 |
| delete the project | 200 | 200 | 403 | 403 | 403 | 403 | 403 | 403 | 401 | 403 | 401 |

`token_narrow` is the row worth reading twice. A token carrying one action on one area is refused **401** everywhere outside it, not 403: the product declines to accept the credential for that route at all, rather than accepting it and then weighing permissions.

Deleting the project is split in two. The refusals are replayed against the shared project, because a refused call changes nothing; the two rows that succeed get a world of their own, since a project made just for the row would carry none of the shared grants. A row that mutates gets a spare task, for the same reason.

Every actor in section 3 is enumerated here except the instance administrator, for the reason given there.

**The difference between 403 and 404 is treated as its own class of defect.** An outsider who gets "forbidden" rather than "not found" has been told that someone else's object exists. The product answers 403, and the suite states the position as an expected failure rather than asserting it: see the note on the held finding in [docs/findings](findings/README.md).

---

## 7. The generated families

Four families that nobody writes by hand.

**CON, contract conformance.** The descriptions are fetched from the running instance: v1 serves Swagger 2.0, v2 serves OpenAPI 3.1 generated on the fly by Huma. Every response to every call made by any test is validated against the schema for its operation, in the transport layer rather than in a test of its own. On top of that, one sweep walks every read operation.

**AUT, a credential is required.** Every operation, called with no authorization header. The expectation is 401 and nothing leaked in the body. The list of deliberate exceptions is explicit and is itself checked for staleness, so an endpoint that quietly becomes public cannot slip through.

**SCP, the token scope matrix.** An API token carries permissions as a map of area to actions, and the product publishes the full set of valid keys on an endpoint of its own. So the matrix is built from the product's answer: for each area a token is issued with exactly one action, and what that action allows must pass while everything next to it is refused.

**ERR, the domain error code invariant.** The product carries a numeric domain code that clients translate against. v1 returns it as a `code` field. v2 renders errors as RFC 9457 and carries the same code across, because otherwise v2 clients read zero. The invariant: where v1 names a failure with a domain code, v2 has to name it with the same one, and any error path that bypasses the translation surfaces as a missing or different code.

The pairs are computed rather than listed. The two versions describe the same operation under different parameter names, `/projects/{projectID}/users/{userID}` against `/projects/{project}/users/{user}`, so matching on the literal template finds barely half of what they share; matching on the shape of the path finds the rest. Every pair that can be asked about an identifier which cannot exist is asked, on both versions, and held to the same answer. Two checks beside the sweep state the rest: that an absent object does carry a code, and that a refusal does not ([VKJ-005](findings/VKJ-005-permission-errors-carry-no-code/)).

The sweep found [VKJ-016](findings/VKJ-016-caldav-token-revocation-false-success/) on its first run, which is the argument for generating this sort of thing rather than writing it.

---

## 8. The aimed-at places

**Bulk operations.** Three endpoints take a list: bulk task update, bulk labelling, bulk assignment. The classic defect of the class is checking permissions on the first element only. The scenario: two objects, rights on one and not the other. The expectation is refusal of the whole call, with nothing partially applied, confirmed against the database.

**The polymorphic reactions endpoint.** The entity type arrives in the path. Checked with another type, a non-existent type, and a type the actor has no access to.

**Relations between tasks.** A relation is created between tasks in different projects. Checked: linking your task to someone else's, and leaking the other task's content through the relation list.

**Public links.** A forty-character hash, generated by the server. The chain of disclosing a hash and then reaching another project's attachments was a real vulnerability. Checked: the scope of the link's token, and the behaviour of a link behind a password.

**Parsing the permission level.** Null, an empty string, the number as a string, the "not determined" sentinel, out of range, fractional, boolean, a list and an object. None of them may become a grant, and a refusal has to leave an existing grant alone. With no level named at all the grant lands on read, which is the safe direction to default in.

**The API token format.** The token is a `tk_` prefix and forty hexadecimal characters, looked up by its last eight with a hash comparison after. The code guards against a value too short to slice. Checked: empty, prefix only, too short to slice, right shape with the wrong value, right shape but not hexadecimal, wrong prefix, no prefix, four thousand characters, and punctuation. Every one is refused the same way, with the same status and the same domain code, because a refusal that varies by shape tells whoever is guessing which half of the guess was right.

**The generated partial-update endpoints.** v2 derives them automatically from read and write pairs. Along the backbone, partial update is compared against full update.

**What a task promises.** The rules a user would describe without mentioning HTTP, and which no status code checks: finishing a task records when and reopening it forgets, a repeating task moves its due date instead of closing, a task carries a number of its own that counts up inside its project and starts again in the next, moving a card into the Done column is the same act as ticking the box, an archived project refuses writes and stays readable, an assignee has to be someone who can open the task, a relation is visible from both of its ends, and one label goes onto one task once.

**Two callers at the same instant.** The ordinary case for a shared product, and the one a sequential suite never reaches. The callers are released together by a barrier, because work handed to a thread pool staggers, and staggered calls do not collide. What must hold whoever wins: the tasks that are accepted keep distinct numbers, simultaneous updates keep one of the writes whole, and neither a double delete nor a double label add answers with a server error. What does not hold is [VKJ-015](findings/VKJ-015-simultaneous-task-creation-500/): two tasks created in one project at the same moment collide on that number, and every caller but one gets a 500.

---

## 9. Consistency across API versions

A slice unique to this system under test, where two APIs describe the same product.

Differences that are deliberate, confirmed in the product's source:

1. v1 uses non-standard verbs: update is POST, create is PUT. v2 is ordinary REST.
2. The error shape differs: v1 returns a flat object with a code and a message, v2 returns an RFC 9457 document.
3. **Validation errors carry different statuses: v1 answers 412, v2 answers 422.** That is a decision by the authors, not a defect, and it is pinned as an expectation.

What is checked:

1. Create with v1, read with v2, compare every field.
2. The same in reverse.
3. One actor gets the same access decision from both versions.
4. The domain error code matches across different statuses and different body shapes.
5. Pagination behaves the same at the boundaries; the default page size is fifty.
6. Date fields arrive in the same format and the same zone.

---

## 10. Checks made through the database

| What | How |
|---|---|
| deleting a project leaves no orphaned tasks | counting rows by foreign key |
| a refused bulk update applied nothing, not even partly | comparing every row before and after |
| a granted permission is written as a row | selecting from the rights table |
| an attachment is recorded against its task | joining the attachment and file tables |
| a token is never stored in the clear | selecting the columns of the token table |
| reading a token back never returns the secret | the API answer beside the stored row |

Read-only, always. The suite never writes through this route: building state through anything but the product's own API would test the schema rather than the product, and would rot at the first migration.

---

## 11. Asynchronous effects

Every check waits for a result with a deadline. There is not one fixed pause in the suite.

| Effect | Where it is confirmed |
|---|---|
| the registration message | the mail trap's API, and the token in it is spent |
| the password reset message | the mail trap's API |
| an outgoing webhook on a task event | a receiver of our own, per test, body compared |
| a webhook ignoring an event it did not subscribe to | the same receiver, which must stay empty |
| an attachment reaching object storage | fetched back and compared byte for byte |
| a metrics counter moving | a query to Prometheus |

The product's internal event bus runs in the process, so an event and its handler live in the same container. That shortens the wait but does not remove the need to wait: the handlers are asynchronous, and the product's own testing API deliberately waits for them before changing data.

---

## 12. Regressions for published vulnerabilities

Each test names its advisory, so a failure here is not a puzzle. It says which published weakness has come back.

| Identifier | What it was | The check |
|---|---|---|
| CVE-2026-33678 | reading an attachment by a single identifier | another project's attachment is out of reach |
| GHSA-2pv8-4c52-mf8j | hash disclosure plus reach into other attachments | a link's token is confined to its own project |
| CVE-2026-68581 | taking over other users' API tokens | another user's token cannot be read or revoked |
| CVE-2026-55065 | destroying someone else's kanban buckets | bucket operations demand rights on the project |
| CVE-2026-35601 | a line break breaking calendar generation | a title with control characters is escaped |
| CVE-2026-27819 | archive extraction outside its directory | out of scope, noted only |

---

## 13. The calendar protocol, a thin slice

Sixteen checks. The point of the slice in one sentence: **the same data has two doors, and they have to agree.**

1. A task created over the API is visible over CalDAV, and the reverse.
2. A due date set in one door reaches the other, in both directions.
3. A deletion in one door is a deletion in the other, in both directions.
4. A title outside the Latin alphabet survives both directions unchanged.
5. A title with a line break cannot forge calendar properties: the regression for CVE-2026-35601.
6. The calendar refuses a caller with no credentials, and challenges for Basic.
7. Someone else's calendar is not readable, over GET or PROPFIND.
8. A revoked CalDAV token stops working.
9. An API token opens the calendar only when it carries the `caldav` permission, and only under its owner's username.

Answers are read by the rules of RFC 5545 rather than by searching the text: a title escaped correctly still contains the characters of the property it tried to forge, and only parsing tells a real property from text that looks like one.

---

## 14. Localisation and time

| What | The check |
|---|---|
| the interface follows the browser's language | the placeholder changes away from English for de-DE and ru-RU |
| the suite's own locale is pinned | English wording is what a default context renders |
| long words do not break the layout | measured, not eyeballed: the element either fits or is trimmed |

Only the English wording is pinned. For other languages the check is that the wording changed at all, because asserting a particular translation would test the translators rather than the product.

---

## 15. Behaviour when a dependency fails

**A layer of its own, with its own run.** It never joins the main run, because it takes the infrastructure out from under itself: these checks are slow and unstable by nature. It runs as its own CI job, on a schedule and on demand, and always in a single process, because an outage cannot be confined to the test that caused it.

| Failure | Expectation | What actually happens |
|---|---|---|
| the database is gone | the health check stops claiming health, and no stack trace escapes | as expected |
| Redis is gone | the product degrades but still answers | it hangs instead: [VKJ-011](findings/VKJ-011-redis-outage-hangs-every-request/) |
| object storage is gone | an upload fails with a clear error | it answers 200 with the failure hidden in the body: [VKJ-010](findings/VKJ-010-failed-upload-returns-200/) |
| the mail server is gone | the request does not fail; the message waits | the request holds, but mail stops until traffic pauses: [VKJ-013](findings/VKJ-013-mail-daemon-stale-connection/) |

Three of the four expectations are not met, which is a fair return for six tests.

---

## 16. The interface

Only what cannot be checked through the API. Data is prepared with API calls and the browser's session storage is filled in advance, so a page opens signed in and looking at the thing under examination.

Each row below names the thing the API cannot be asked. Where a claim is an absence, it is paired with the presence that proves the absence means something: a control missing from a read-only share is only evidence if the same page shows it to a writable one.

| What | Why only a browser can answer it |
|---|---|
| quick-add parses a label and a priority out of a plain sentence, and strips the markers from the title | the parsing is frontend work; the API only sees the result |
| a task appears in every view that lists tasks — list, table and board | four views are four pieces of frontend code over one set of data, which is how two of them come to disagree. Gantt is excluded by name: it plots by date and correctly shows nothing for a task without one |
| ticking the box in a list row finishes that task and no other | the row decides which task it is for. A list that sends a row's position rather than a task's identity passes every check made of one task alone |
| dragging a card into the last column of the board finishes the task, and dragging it into an ordinary column does not | the drop has no API shape: it is the frontend turning a press, a path and a release into one call. The board has no `draggable` attribute, so the gesture is delivered as a path |
| a public link shows the project to a visitor with no account, and offers a control for adding a task only where the share allows it | the whole public route is frontend: hash for token, token out of the path, project rendered for someone who has never signed in |
| a public link pointed at another project sends the visitor to sign in | the boundary GHSA-2pv8-4c52-mf8j crossed, asked as a URL a curious visitor can type |
| a share behind a password renders nothing until the password is given | the only place this product asks a stranger for a secret |
| a project shared read-only offers no control for adding a task, while its owner gets one | the pairing is the point: an absence asserted on its own is satisfied by a page that has not rendered |
| arriving at the page that offers to delete a project deletes nothing, and confirming deletes it | the confirmation is entirely frontend, and the route is a URL a person can be sent |
| language and layout, as in section 14 | |

A large browser suite duplicating API coverage would be slower, more fragile and worth less. This one is deliberately small, and the rows it does not have are deliberate too: teams, labels, saved filters and notifications have no browser tests, because everything they do through the interface is a form that the API already answers for.

---

## 17. How findings are written up

Findings go into `docs/findings`, one folder each, in English with a Russian version alongside.

The requirement for every report: **reproducible in two minutes without trusting the author.** The reader runs a script and sees the result.

```
docs/findings/
  README.md                    the index
  VKJ-007-label-update-verb/
    README.md                  the report
    README.ru.md               the same in Russian
    reproduce.py               a standalone reproduction, standard library only
```

Report fields: summary, severity, affected version, environment, steps, expected, actual, impact on the user, and the test that pins it.

**The exception for vulnerabilities.** If a finding looks exploitable, meaning it grants access to someone else's data or bypasses a permission, it goes to the product's maintainers through their published procedure first and reaches this folder only after a fix. Publishing a working hole in a live product is not on.

---

## 18. What is deliberately not covered

- Imports from external systems: they need credentials for those systems.
- Backgrounds from an external photo service, for the same reason.
- Plugins on the embedded interpreter: a large separate subject.
- Load and performance characteristics: a different tool and a different job.
- The product's own unit tests: its authors have written those.
- Full CalDAV conformance: deliberately limited to the slice in section 13.
