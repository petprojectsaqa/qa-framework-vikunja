"""Declaring the world a test needs.

A suite this size stays readable only if setup is described rather than
programmed. A test says what should exist and who should be able to see
it; the builder performs the calls, in the right order, and hands back
one object to reach everything through.

    scene = (
        build(actors)
        .project()
        .member("writer", Permission.WRITE)
        .member("reader", Permission.READ)
        .share("public", Permission.READ)
        .task()
        .done()
    )

    scene.actor("reader").api.tasks.delete(scene.task_id)

Everything is created as it is declared, so a failure points at the line
that caused it rather than at a later build step. Anything the test did
not ask for is never created.

Link shares become actors like anyone else, so an access-matrix row does
not care whether its caller arrived by session, by team membership or
through a public link.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import allure

from vikunja_qa.actors.actor import Actor
from vikunja_qa.actors.factory import ActorFactory
from vikunja_qa.auth.strategies import LinkShareToken
from vikunja_qa.domain.permissions import Permission
from vikunja_qa.transport.response import ApiResponse


class SetupError(AssertionError):
    """Raised when building the scenario fails.

    Distinct from a test failure on purpose: it means the world could not
    be arranged, so whatever the test was going to check was never
    reached.
    """


@dataclass
class Scene:
    """The world a test asked for."""

    owner: Actor
    actors: dict[str, Actor] = field(default_factory=dict)
    projects: dict[str, dict[str, Any]] = field(default_factory=dict)
    tasks: dict[str, dict[str, Any]] = field(default_factory=dict)
    teams: dict[str, dict[str, Any]] = field(default_factory=dict)
    labels: dict[str, dict[str, Any]] = field(default_factory=dict)
    shares: dict[str, dict[str, Any]] = field(default_factory=dict)

    # --- the common case, unnamed -------------------------------------------

    @property
    def project(self) -> dict[str, Any]:
        return self._only(self.projects, "project")

    @property
    def project_id(self) -> int:
        return int(self.project["id"])

    @property
    def task(self) -> dict[str, Any]:
        return self._only(self.tasks, "task")

    @property
    def task_id(self) -> int:
        return int(self.task["id"])

    # --- named access -------------------------------------------------------

    def actor(self, role: str) -> Actor:
        if role not in self.actors:
            raise SetupError(f"no actor {role!r} in this scene; it has {sorted(self.actors)}")
        return self.actors[role]

    def everyone(self, *roles: str) -> list[Actor]:
        """Several actors at once, for parameterised matrix rows."""
        return [self.actor(role) for role in roles]

    @staticmethod
    def _only(items: dict[str, dict[str, Any]], kind: str) -> dict[str, Any]:
        if not items:
            raise SetupError(f"this scene has no {kind}; add one with .{kind}()")
        return next(iter(items.values()))


class SceneBuilder:
    def __init__(self, actors: ActorFactory) -> None:
        self._factory = actors
        self._owner = actors.user("owner")
        self._scene = Scene(owner=self._owner, actors={"owner": self._owner})

    # --- people -------------------------------------------------------------

    def user(self, role: str) -> SceneBuilder:
        """An account with no relationship to anything in this scene."""
        self._scene.actors[role] = self._factory.user(role)
        return self

    def outsider(self, role: str = "outsider") -> SceneBuilder:
        """The actor that proves an authorization check checks anything."""
        return self.user(role)

    def member(
        self,
        role: str,
        permission: Permission = Permission.READ,
        *,
        on: str | None = None,
    ) -> SceneBuilder:
        """A new account granted a permission on a project directly."""
        project = self._project(on)
        actor = self._factory.user(role)
        self._scene.actors[role] = actor
        with allure.step(f"grant {permission} on project to {role}"):
            self._expect(
                self._owner.api.projects.add_user(int(project["id"]), actor.username, permission),
                f"grant {permission} to {role}",
            )
        return self

    # --- projects and tasks -------------------------------------------------

    def project(self, name: str = "main", title: str | None = None, **fields: Any) -> SceneBuilder:
        with allure.step(f"create project {name}"):
            created = self._expect(
                self._owner.api.projects.create(title or f"project {name}", **fields),
                f"create project {name}",
            )
        self._scene.projects[name] = dict(created.json)
        return self

    def task(
        self, name: str = "task", *, in_: str | None = None, title: str | None = None, **fields: Any
    ) -> SceneBuilder:
        project = self._project(in_)
        with allure.step(f"create task {name}"):
            created = self._expect(
                self._owner.api.tasks.create(int(project["id"]), title or f"task {name}", **fields),
                f"create task {name}",
            )
        self._scene.tasks[name] = dict(created.json)
        return self

    def label(self, name: str = "label", title: str | None = None) -> SceneBuilder:
        with allure.step(f"create label {name}"):
            created = self._expect(
                self._owner.api.labels.create(title or f"label {name}"), f"create label {name}"
            )
        self._scene.labels[name] = dict(created.json)
        return self

    # --- teams --------------------------------------------------------------

    def team(
        self,
        name: str = "team",
        *,
        members: tuple[str, ...] = (),
        permission: Permission | None = None,
        on: str | None = None,
    ) -> SceneBuilder:
        """A team, optionally with fresh members and a grant on a project.

        The second route into a project: a caller can hold no direct
        grant yet still get in through a team.
        """
        with allure.step(f"create team {name}"):
            created = self._expect(self._owner.api.teams.create(name), f"create team {name}")
        team = dict(created.json)
        self._scene.teams[name] = team

        for role in members:
            actor = self._factory.user(role)
            self._scene.actors[role] = actor
            self._expect(
                self._owner.api.teams.add_member(int(team["id"]), actor.username),
                f"add {role} to team {name}",
            )

        if permission is not None:
            project = self._project(on)
            self._expect(
                self._owner.api.projects.add_team(int(project["id"]), int(team["id"]), permission),
                f"grant {permission} on project to team {name}",
            )
        return self

    # --- link shares --------------------------------------------------------

    def share(
        self,
        role: str = "share",
        permission: Permission = Permission.READ,
        *,
        on: str | None = None,
        password: str | None = None,
    ) -> SceneBuilder:
        """A public link, exposed as an actor.

        The token it yields is meant to reach exactly one project, which
        is the boundary GHSA-2pv8-4c52-mf8j crossed.
        """
        project = self._project(on)
        with allure.step(f"create link share {role} ({permission})"):
            created = self._expect(
                self._owner.api.shares.create(
                    int(project["id"]), permission, password=password, name=role
                ),
                f"create link share {role}",
            )
            share = dict(created.json)
            self._scene.shares[role] = share

            authenticated = self._expect(
                self._owner.api.shares.authenticate(str(share["hash"]), password=password),
                f"authenticate link share {role}",
            )

        token = LinkShareToken(str(authenticated["token"]), share_hash=str(share["hash"]))
        self._scene.actors[role] = self._owner.using(token, role=role)
        return self

    # --- finish -------------------------------------------------------------

    def done(self) -> Scene:
        return self._scene

    # --- internals ----------------------------------------------------------

    def _project(self, name: str | None) -> dict[str, Any]:
        if not self._scene.projects:
            raise SetupError("declare a project before anything that lives in one")
        if name is None:
            return next(iter(self._scene.projects.values()))
        if name not in self._scene.projects:
            raise SetupError(
                f"no project {name!r} in this scene; it has {sorted(self._scene.projects)}"
            )
        return self._scene.projects[name]

    @staticmethod
    def _expect(response: ApiResponse, what: str) -> ApiResponse:
        if not response.ok:
            raise SetupError(f"could not {what}\n{response.describe()}")
        return response


def build(actors: ActorFactory) -> SceneBuilder:
    """Entry point. Creates the owning account straight away, since every
    scene has one."""
    return SceneBuilder(actors)
