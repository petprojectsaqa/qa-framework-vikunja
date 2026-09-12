# VKJ-008. Authorisation errors in the second version of the API arrive in a format that version does not describe

English | [Русский](README.ru.md)

**Severity:** high
**Version:** Vikunja v2.6.0
**Component:** error handling in the second version of the API
**Environment:** official image `vikunja/vikunja:2.6.0`, the stand from `docker/docker-compose.yml`

## Summary

The second version of the API describes, for **every** operation, a `default` response with the `VikunjaErrorModel` schema and the `application/problem+json` content type. The schema is closed: `additionalProperties: false`.

The product returns errors in two incompatible formats, depending on where they arose.

**Domain errors come back correctly.** An example, a request for a task that does not exist:

```
Content-Type: application/problem+json
{
  "$schema": "…/schemas/VikunjaErrorModel.json",
  "title": "Not Found",
  "status": 404,
  "detail": "This task does not exist",
  "code": 4002
}
```

**Middleware errors come back in the old first-version format.** An example, a request with no token:

```
Content-Type: application/json
{
  "code": 11,
  "message": "missing, malformed, expired or otherwise invalid token provided"
}
```

The second response contradicts the description twice over: the content type is not the declared one, and the `message` field is not provided for by the schema, which is closed and so forbids extra fields.

The same goes for the 405 response, which the middleware also produces.

## Scale

A walk over every operation of the second version showed the discrepancy on roughly 180 out of 196. There is a single cause: errors that do not reach a handler never pass through the error converter, and are returned directly.

## Impact

This is not cosmetic. A 401 arises on every token expiry, that is, in the ordinary work of any client, not in an edge case.

A second-version client written to the description parses `application/problem+json` and reads the `detail` field. When the session expires it gets a different content type, a missing `detail` and an undocumented `message`. In a strict implementation that is a parse error, in a lenient one an empty message. In both cases the user is never told to sign in again.

Separately: since the `detail` field is missing, localisation breaks for these errors too, the localisation described in [VKJ-005](../VKJ-005-permission-errors-carry-no-code/).

## Steps to reproduce

```bash
python reproduce.py
```

The script prints the description, a domain error and a middleware error side by side.

## Expected

Every error in the second version is returned in the declared format and with the declared content type.

## Actual

Middleware errors are returned in the first version's format.

## What to fix

Put middleware errors through the same converter the handlers use, or describe the second format in the specification as permitted for the statuses concerned. The first is preferable: a closed schema and a single format are exactly what the second version was introduced for.

## Related tests

Caught automatically by the contract check on any request to the second version without a token. The walk in `tests/api/authorization/test_credentials_required.py` shows the full scale. Recorded in the baseline as `VKJ-008`.
