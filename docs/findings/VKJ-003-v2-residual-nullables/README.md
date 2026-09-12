# VKJ-003. Nullability is not fixed everywhere in the second version of the specification

English | [Русский](README.ru.md)

**Severity:** low
**Version:** Vikunja v2.6.0
**Component:** the second-version API specification
**Environment:** official image `vikunja/vikunja:2.6.0`, the stand from `docker/docker-compose.yml`

## Summary

The second version of the API specification mostly accounts for empty collections arriving as `null`, and declares them with the type `["array", "null"]`. But several fields are still declared as plain `object` or `array`, although the product returns `null` in them:

| Field | Where it appears | Declared | Returned |
|---|---|---|---|
| `related_tasks` | task | `object` | `null` |
| `reactions` | task, comment | `object` | `null` |
| `extra_settings_links` | user settings | `object` | `null` |
| `filter` | project view | `$ref` to the `TaskCollection` object | `null` |

The neighbouring `bucket_configuration` field in the same view is declared as `["array", "null"]`, that is, it has already been fixed. It is given here as an example of what the other four should look like.

This is what is left of the same defect as described in [VKJ-002](../VKJ-002-v1-nullable-collections/), but now in the new version of the specification, where the other fields have been fixed.

## Why this is its own finding

VKJ-002 is about the old version of the specification, which can be taken as frozen. This one is about the new version, generated from the code and actively developed. A fix here is worth making, because this is the version that will be used from now on, and it is already nearly correct: four fields are missing.

## Impact

A second-version client generated in a strictly typed language fails on parsing a task that has no related tasks and no reactions, which is to say any ordinary task.

## Reproduction

```bash
py docs/findings/VKJ-003-v2-residual-nullables/reproduce.py
```

The script reads the second-version specification from a running stand, asks the product for the same fields alongside it, and prints the declared type against the value that came back.

## What to fix

Mark nullability on these four fields the same way it is already marked on the neighbouring `bucket_configuration`.

## Related test

Caught by the contract check in the transport layer. Recorded in the baseline as `VKJ-003`.
