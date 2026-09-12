# VKJ-009. Endpoints that return binary data are described in v1 as returning JSON

English | [Русский](README.ru.md)

**Severity:** low
**Version:** Vikunja v2.6.0
**Component:** the first-version API description
**Environment:** official image `vikunja/vikunja:2.6.0`, the stand from `docker/docker-compose.yml`

## Summary

Two first-version operations return something other than JSON, an image with the code in it and an export archive, but their description carries `produces: application/json`. The second-version description of the same two operations names the real types, and that settles which side is wrong.

| Operation | What it returns | Declared in v1 | Declared in v2 |
|---|---|---|---|
| `GET /user/settings/totp/qrcode` | an image with the code | `application/json`, a body of type `file` | `image/jpeg` |
| `POST /user/export/download` | an export archive | `application/json`, a body of `models.Message` | `application/zip` |

The first row contradicts itself inside a single description: the operation is declared to produce `application/json`, and right there the response body is typed as `file`.

## Impact

A client generated from the first-version description gives these operations a JSON return type and then tries to parse a binary response. The way round it is not hard, but it is found at run time rather than while reading the description.

This is an error of the same kind as the other description mismatches: the product behaves sensibly, the description lies. And, as in [VKJ-002](../VKJ-002-v1-nullable-collections/), the argument is settled not by opinion but by a second description of the same product.

## Reproduction

```bash
py docs/findings/VKJ-009-binary-endpoints-described-as-json/reproduce.py
```

The script reads both descriptions from a running stand and prints them side by side. No account is needed: the mismatch is visible in the descriptions themselves.

## What to fix

Give these operations their real content types in the first-version description, `image/jpeg` and `application/zip`, as the second version already does.

## Scope of the finding

The neighbouring binary endpoints are described honestly, and that is worth saying plainly so the finding is not taken for a wider one than it is:

- `GET /api/v1/{username}/avatar` declares `application/octet-stream`;
- `GET /api/v2/avatar/{username}` declares `application/octet-stream`.

## Related test

There is no test of its own, and there is a reason for that. The contract check in the suite validates responses, and it never reaches the binary responses of these two operations: one needs two-factor authentication switched on, the other a prepared export. The finding is proved by comparing the two descriptions, which is what the reproduction script does.
