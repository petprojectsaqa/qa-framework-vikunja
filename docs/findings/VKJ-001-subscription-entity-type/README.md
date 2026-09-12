# VKJ-001. The v1 specification declares `Subscription.entity` an integer, and the product returns a string

English | [Русский](README.ru.md)

**Severity:** medium
**Version:** Vikunja v2.6.0
**Component:** the first-version API specification, `models.Subscription`
**Environment:** official image `vikunja/vikunja:2.6.0`, PostgreSQL 18, the stand from `docker/docker-compose.yml`

## Summary

The first version of the API specification describes the `entity` field of the subscription object as an integer:

```json
{ "type": "integer" }
```

The product returns a string in that field: `"task"` or `"project"`.

The subscription object is embedded in task and project responses, so the discrepancy does not touch one auxiliary endpoint but the main entities of the product.

## Why this is a specification defect and not a quibble

The second version of the API specification, which the product generates from its own code, describes the same field correctly:

```json
{
  "type": "string",
  "enum": ["project", "task"],
  "readOnly": true,
  "description": "The kind of entity this subscription is for. Either project or task; derived server-side from the request path."
}
```

Two specifications of one product describe one field incompatibly. The second matches the actual behaviour, the first does not.

## Duplicate check

The product's tracker has [issue #3316](https://github.com/go-vikunja/vikunja/issues/3316), closed on 29 July 2026. It reported the same mismatch, but **only for the second version of the API**: there the engine derived the schema from the internal integer type while serialisation returned a string. The fix added a schema override to a string enumeration.

That fix did not touch the first version of the specification. This finding is what is left of the same cause in the old specification, and it should be reported with a reference to the closed issue.

## Impact

A client generated from the first-version specification in a strictly typed language cannot parse the response for any task that has a subscription. In Java, C#, Swift, Kotlin and Rust that is a parse error, not a warning. A task subscription is created automatically when the author creates the task, so this is not an edge case but the main one.

## Steps to reproduce

1. Bring the stand up.
2. Register a user and confirm the address.
3. Create a project and a task in it.
4. Request the task and look at the `subscription.entity` field.
5. Compare with the type from the specification.

```bash
./reproduce.sh
```

## Expected

The type of the field in the specification matches the type in the response.

## Actual

```
v1 specification: {"type": "integer"}
response:         "entity": "task"
v2 specification: {"type": "string", "enum": ["project", "task"]}
```

## What to fix

Bring the annotation of the `Entity` field of the `Subscription` struct in the first-version specification to a string enumeration, as is already done in the second.

## Related test

The discrepancy is caught automatically by the contract check in the suite's transport layer. Recorded in the baseline as `VKJ-001`.
