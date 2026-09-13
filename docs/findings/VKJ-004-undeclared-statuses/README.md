# VKJ-004. Operations answer with statuses that are not in their specification

English | [Русский](README.ru.md)

**Severity:** low
**Version:** Vikunja v2.6.0
**Component:** the API specification
**Environment:** official image `vikunja/vikunja:2.6.0`, the stand from `docker/docker-compose.yml`

## Summary

Some operations return response codes that are not listed in their specification. Measured across every operation both descriptions publish, once the generated families had walked them all: **191 operation-and-status pairs**, on 190 v1 operations and one v2 one.

| Spec | Status | Operations | What it is |
|---|---|---|---|
| v1 | 401 | 142 | the normal answer to a missing or expired token, on the whole protected surface |
| v1 | 404 | 33 | an identifier that resolves to nothing, on operations declaring only 200, 403 and 500 |
| v1 | 403 | 5 | the mirror of the row above: these declare 404 and answer 403 |
| v1 | 412 | 4 | a field that failed validation (domain code 2002), and a write to an archived project (3008) |
| v1 | 400 | 3 | a malformed argument, among them a reaction kind the product does not know |
| v1 | 405 | 2 | a verb the description declares and the router does not serve |
| v1 | 201 | 1 | `PUT /user/settings/token/caldav` answers 201 while declaring 200 |
| v2 | 401 | 1 | `POST /user/export/download`, the only v2 operation with no `default` response |

Two things stand out. The 401 row is the bulk of it: only two v1 operations declare 401 at all, so a client reading the description has no way to know that an expired session is a documented outcome anywhere. And the 404 and 403 rows together mean the description gets the distinction between "not found" and "not allowed" the wrong way round on thirty-eight operations.

The second version is almost clean here, and for a structural reason: it gives 195 of its 196 operations a shared `default` response carrying its error model, which covers every status it did not name individually.

## Impact

A consumer of the specification does not know which errors to handle. A generated client lands in its "unexpected response" branch on the most ordinary scenario there is, an expired session. The API documentation misleads in exactly the part that is needed most during integration.

## Reproduction

```bash
python reproduce.py
```

## What to fix

Add 401 to every protected operation in the specification, and 412 where a precondition is checked. Since 401 applies to the whole protected surface, it makes more sense to describe it once as a shared response than to list it in every operation.

## Related test

Caught by the contract check in the transport layer, violation kind "undeclared status". Recorded in the baseline as `VKJ-004`.

This entry used to be the one exception in the baseline: it named the kind of violation and nothing else, so it accepted every undeclared status, on either description, at any status, for any operation. That is not a baseline entry — it is the check switched off, and an unexpected 500 on an operation that does not declare one was being filed as already known.

It is now eight entries, one per status class, with the counts above. Two of the smallest are pinned to the single operation they describe, and the 405 on `PUT /labels/{id}` moved to [VKJ-007](../VKJ-007-label-update-verb/), where it belongs. A status class not on that list — a 409, a 429, an unexpected 500 — is a new deviation and ends the run red. `tests/unit/test_contracts.py::TestBaseline::test_no_entry_switches_a_whole_check_off` is what stops an entry that wide being written again.

## What the suite learned from this

The narrowing turned up two errors of our own, both of which had been hiding behind the wildcard:

- The reader of the descriptions kept a status only if it found a JSON schema for it, so a status declared with no body — 204 No Content, and every binary download — read as undeclared. Thirty-seven such responses in v2 alone would have been reported as this finding.
- With those statuses dropped, a v2 204 or a file download fell through to the operation's `default` response, which is the error model. A successful download was one step away from being reported as failing to look like an error.
