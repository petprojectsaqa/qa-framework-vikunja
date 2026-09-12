# VKJ-007. The v1 description documents updating a label with a method the product does not accept

English | [Русский](README.ru.md)

**Severity:** high
**Version:** Vikunja v2.6.0
**Component:** the first version's API description, labels
**Environment:** official image `vikunja/vikunja:2.6.0`, the stand from `docker/docker-compose.yml`

## Summary

The first version's API description declares that a label is updated with `PUT /api/v1/labels/{id}`. The product answers that request with 405, that is, the method is not supported. What actually works is `POST`, which does not appear in the description at all.

| Method on `/api/v1/labels/{id}` | In the description | The product's answer |
|---|---|---|
| GET | yes | 200 |
| **PUT** | **yes** | **405** |
| **POST** | **no** | **200** |
| PATCH | no | 405 |
| DELETE | yes | 200 |

The discrepancy runs both ways: an operation that does not exist is documented, and an operation that does exist is not.

## Why this is not a quibble

This is not a matter of description style, but a documented capability that does not work. A client generated from the first version's description **cannot update a label at all**: the only method it knows of is rejected by the server.

The second version of the API does not have this problem, and is evidence that the fault lies in the first version's description:

| Method on `/api/v2/labels/{id}` | In the description | The product's answer |
|---|---|---|
| GET | yes | 200 |
| PUT | yes | 200 |
| PATCH | yes | 304 |
| POST | no | 405 |

## Impact

Any consumer of the first version's description, whether a generated client, a request collection or documentation for integrators, gets instructions for updating labels that do not work. The failure appears only at run time, and it looks like a server refusal rather than a client mistake, so working it out takes a long time.

Separately: the same class of discrepancy was found on `POST /api/v1/migration/vikunja-file/migrate`, which also answers 405. There are probably more cases, and a walk over every operation would give the full list.

## Steps to reproduce

```bash
python reproduce.py
```

The script creates a label and runs through the methods on it, printing side by side what the description promises and what the product answers.

## Expected

The method given in the description is accepted by the product.

## Actual

`PUT` is rejected with 405, and the undocumented `POST` works.

## What to fix

Bring the annotation of the label update operation in the first version into line with the `POST` method it actually uses.

## Related test

`tests/api/contracts/test_documented_operations.py` walks every operation of both versions and flags each one that answers 405, since such an answer means the described operation does not exist.
