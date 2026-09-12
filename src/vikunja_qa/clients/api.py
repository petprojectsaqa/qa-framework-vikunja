"""One handle onto every area client.

Bound to a credential, so `owner.api.projects.create(...)` and
`outsider.api.projects.get(...)` are the same call made by different
people. That symmetry is what makes the access matrix a table rather
than a pile of near-identical tests.
"""

from __future__ import annotations

from functools import cached_property

from vikunja_qa.clients.projects import ProjectsClient
from vikunja_qa.clients.sharing import LabelsClient, SharesClient, TeamsClient, TokensClient
from vikunja_qa.clients.tasks import TasksClient
from vikunja_qa.transport.client import HttpClient


class Api:
    def __init__(self, http: HttpClient) -> None:
        self._http = http

    @property
    def http(self) -> HttpClient:
        return self._http

    @cached_property
    def projects(self) -> ProjectsClient:
        return ProjectsClient(self._http)

    @cached_property
    def tasks(self) -> TasksClient:
        return TasksClient(self._http)

    @cached_property
    def teams(self) -> TeamsClient:
        return TeamsClient(self._http)

    @cached_property
    def labels(self) -> LabelsClient:
        return LabelsClient(self._http)

    @cached_property
    def shares(self) -> SharesClient:
        return SharesClient(self._http)

    @cached_property
    def tokens(self) -> TokensClient:
        return TokensClient(self._http)
