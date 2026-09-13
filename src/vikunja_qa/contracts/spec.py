"""Loads the product's own API descriptions and makes them queryable.

Both specifications are fetched from the running instance rather than
read out of the product's repository, so what gets checked is the build
that is actually up. The two differ in shape as well as in version:

    v1  Swagger 2.0, schemas under `definitions`, response schema inline
    v2  OpenAPI 3.1, schemas under `components.schemas`, response schema
        nested under a media type

Both are normalised here into the same `Operation`, so everything above
this module can ignore the difference.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

import requests

_PARAM = re.compile(r"^\{.+\}$")


@dataclass(frozen=True)
class Operation:
    """One method on one path, with whatever the spec says it returns."""

    method: str
    path_template: str
    operation_id: str
    #: What the description promises per status: the JSON schema for the
    #: body, or None where it declares the status and promises no JSON body
    #: at all. 204 No Content is like that, and so is every binary
    #: download. Keys include the `4XX` and `default` catch-alls both spec
    #: formats use.
    #:
    #: Declaring a status without a schema and not declaring it are
    #: different claims, and conflating them made the suite report a
    #: description as wrong about a status it had got right.
    responses: dict[str, dict[str, Any] | None] = field(default_factory=dict)
    #: The schema the description gives for the body a caller sends, or None
    #: where it describes no body. Responses are what the product owes the
    #: caller; this is what the caller owes the product, and until now the
    #: suite held only one side of that to the contract.
    request_schema: dict[str, Any] | None = None

    @property
    def key(self) -> str:
        return f"{self.method} {self.path_template}"

    def _candidates(self, status: int) -> tuple[str, str, str]:
        """How this status can be declared, most specific first: itself, the
        range it belongs to, and the catch-all."""
        return str(status), f"{status // 100}XX", "default"

    def declares(self, status: int) -> bool:
        """Whether the description mentions this status at all, directly or
        through a range or `default` entry."""
        return any(candidate in self.responses for candidate in self._candidates(status))

    def schema_for(self, status: int) -> dict[str, Any] | None:
        """The JSON schema this status has to satisfy, or None when there is
        none to satisfy.

        The first *declaration* wins, not the first schema. That matters
        because v2 gives almost every operation a `default` response
        carrying the error model: falling through to it would validate a
        204, or a downloaded file, against the shape of an error.
        """
        for candidate in self._candidates(status):
            if candidate in self.responses:
                return self.responses[candidate]
        return None


class SpecIndex:
    """An indexed specification, able to answer "what should this call
    have returned?" for a concrete URL."""

    def __init__(self, document: dict[str, Any], *, label: str, base_path: str) -> None:
        self.document = document
        self.label = label
        self.base_path = base_path.rstrip("/")
        self.version = str(document.get("openapi") or document.get("swagger") or "?")
        self._operations: dict[tuple[str, str], Operation] = {}
        self._index()

    # --- construction -------------------------------------------------------

    @classmethod
    def from_url(cls, url: str, *, label: str, base_path: str) -> SpecIndex:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        return cls(response.json(), label=label, base_path=base_path)

    def _index(self) -> None:
        for template, methods in self.document.get("paths", {}).items():
            if not isinstance(methods, dict):
                continue
            for method, definition in methods.items():
                if method.lower() not in {"get", "post", "put", "patch", "delete"}:
                    continue
                operation = Operation(
                    method=method.upper(),
                    path_template=template,
                    operation_id=str(definition.get("operationId") or ""),
                    responses=self._responses_of(definition),
                    request_schema=self._request_schema_of(definition),
                )
                self._operations[(operation.method, template)] = operation

    def _responses_of(self, definition: dict[str, Any]) -> dict[str, dict[str, Any] | None]:
        """Pull the JSON response schema out of either spec shape.

        Every declared status is kept. One with no JSON schema is kept with
        None rather than dropped, because dropping it loses the fact that
        the description declared it: v2 declares 204 on twenty-nine
        operations and a binary media type on six more, and a reader that
        only keeps schemas sees all of those as undeclared.
        """
        found: dict[str, dict[str, Any] | None] = {}
        for status, described in (definition.get("responses") or {}).items():
            if not isinstance(described, dict):
                continue
            schema = described.get("schema")  # Swagger 2.0
            if schema is None:  # OpenAPI 3.x
                content = described.get("content") or {}
                for media_type, media in content.items():
                    if "json" in media_type and isinstance(media, dict):
                        schema = media.get("schema")
                        break
            found[str(status)] = schema if isinstance(schema, dict) else None
        return found

    @staticmethod
    def _request_schema_of(definition: dict[str, Any]) -> dict[str, Any] | None:
        """The schema for the body a caller sends, out of either spec shape.

        Swagger 2.0 puts it in a parameter with `in: body`; OpenAPI 3.x gives
        it a `requestBody` with a media type, the same as a response. Sixty
        v1 operations describe one and eighty-nine v2 operations do.
        """
        for parameter in definition.get("parameters") or []:
            if isinstance(parameter, dict) and parameter.get("in") == "body":
                schema = parameter.get("schema")
                return schema if isinstance(schema, dict) else None

        content = (definition.get("requestBody") or {}).get("content") or {}
        for media_type, media in content.items():
            if "json" in media_type and isinstance(media, dict):
                schema = media.get("schema")
                return schema if isinstance(schema, dict) else None
        return None

    # --- lookup -------------------------------------------------------------

    @property
    def operations(self) -> list[Operation]:
        return list(self._operations.values())

    def operation(self, method: str, template: str) -> Operation | None:
        return self._operations.get((method.upper(), template))

    def match(self, method: str, url: str) -> Operation | None:
        """Find the operation a concrete URL belongs to.

        Templates are matched segment by segment. A static segment beats a
        parameter, so `/tasks/bulk` wins over `/tasks/{id}` for the same
        request instead of matching by dictionary order.
        """
        path = urlsplit(url).path
        if self.base_path and path.startswith(self.base_path):
            path = path[len(self.base_path) :]
        path = "/" + path.strip("/")
        segments = [s for s in path.split("/") if s != ""]

        best: Operation | None = None
        best_score = -1
        for (candidate_method, template), operation in self._operations.items():
            if candidate_method != method.upper():
                continue
            score = _match_score(template, segments)
            if score > best_score:
                best, best_score = operation, score
        return best if best_score >= 0 else None


def _match_score(template: str, segments: list[str]) -> int:
    """How well a template fits these segments. Higher is better, -1 is
    no match at all; the score counts literal segments so that concrete
    paths outrank parameterised ones."""
    parts = [p for p in template.split("/") if p != ""]
    if len(parts) != len(segments):
        return -1
    score = 0
    for part, segment in zip(parts, segments, strict=True):
        if _PARAM.match(part):
            continue
        if part != segment:
            return -1
        score += 1
    return score


def resolvable(schema: dict[str, Any], document: dict[str, Any]) -> dict[str, Any]:
    """Make a response schema self-contained.

    Response schemas reference shared definitions by pointer into the root
    document. Carrying those containers along with the schema lets a
    plain JSON Schema validator resolve them without a separate registry.
    """
    composed = dict(schema)
    for container in ("definitions", "components"):
        if container in document and container not in composed:
            composed[container] = document[container]
    return composed
