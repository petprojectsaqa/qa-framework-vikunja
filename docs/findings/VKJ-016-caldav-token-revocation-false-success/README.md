# VKJ-016. Revoking a CalDAV token reports success when nothing was revoked

English | [Русский](README.ru.md)

**Severity:** medium
**Version:** Vikunja v2.6.0
**Component:** CalDAV tokens, `DELETE /user/settings/token/caldav/{id}`
**Environment:** official image `vikunja/vikunja:2.6.0`, the stand from `docker/docker-compose.yml`

## Summary

Revoking a CalDAV token answers **"The token was deleted successfully"** in two cases where no token was revoked:

```
DELETE /api/v1/user/settings/token/caldav/999999999   (no such token)
  -> 200 {"message":"The token was deleted successfully."}

DELETE /api/v1/user/settings/token/caldav/<alice's token>   (as bob)
  -> 200 {"message":"The token was deleted successfully."}
```

After the second call Alice's token is still in her list, and it still opens her calendar. v2 behaves the same way and answers 204.

## Impact

The important half is not the absent identifier. A `DELETE` that is idempotent about something already gone is a defensible design, and plenty of APIs answer that way.

The half that matters is the other account's token. Revoking a credential is a security action, and the product confirms it in so many words while the credential goes on working. Someone who revokes a token from a stale list, from a second session, or from a page opened before an account switch is told the token is gone. It is not. A CalDAV token is a standing password for the whole calendar, so the gap between what the product said and what it did is exactly the gap an operator would rely on.

There is no privilege escalation here: Bob cannot revoke Alice's token, and the check that stops him works. What is missing is the report that he did not.

## Steps to reproduce

1. Register two accounts, Alice and Bob.
2. As Alice, mint a CalDAV token: `PUT /api/v1/user/settings/token/caldav`.
3. As Bob, delete it by its id.
4. List Alice's tokens, and use the token against `/dav/`.

`reproduce.py` in this folder does all of it and prints each answer:

```bash
py docs/findings/VKJ-016-caldav-token-revocation-false-success/reproduce.py
```

## Expected

A revocation reports success only when it revoked something. A token belonging to another account gives 404, which is what the product already answers for other objects it declines to confirm the existence of.

## Actual

200 with an explicit confirmation, in both cases, and the other account's token keeps working.

## What to fix

Report what happened: answer 404 when the delete matched no row for the calling account. The existing ownership condition already knows the answer; only the response ignores it.

## How it was found

Not by a test written for it. The generated cross-version error sweep asks every operation both versions describe about an identifier that cannot exist, and compares the two answers. This operation was the one where the versions disagreed about whether anything had failed at all, which is what led to the pair of accounts.

## Related test

`tests/api/contracts/test_error_codes.py::test_revoking_a_token_that_was_not_revoked_says_so`, marked as an expected failure. It states the position without breaking the build and turns into an unexpected pass when the answer starts matching the action.
