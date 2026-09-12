"""Environment configuration for the suite.

Every address and secret the tests need lives here and nowhere else.
Values default to the local stand described in docker/README.md and can
be overridden with VQA_-prefixed environment variables or a .env file,
which is how the CI job points the same suite at a different stand.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="VQA_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- system under test -------------------------------------------------
    base_url: str = "http://localhost:3456"

    # --- stand services the suite asserts against --------------------------
    mailpit_url: str = "http://localhost:18025"
    webhook_url: str = "http://localhost:18080"
    prometheus_url: str = "http://localhost:19090"
    minio_url: str = "http://localhost:19000"

    # --- database, for integrity checks the API cannot make ----------------
    db_host: str = "localhost"
    db_port: int = 15432
    db_user: str = "vikunja"
    db_password: str = "vikunja"
    db_name: str = "vikunja"

    # --- the product's own test-support API --------------------------------
    # Matches VIKUNJA_SERVICE_TESTINGTOKEN on the stand. Used only for a
    # one-off reset and for states the public API cannot reach; see
    # docs/strategy.md, section 2.
    testing_token: str = "qa-stand-testing-token"

    # --- timings -----------------------------------------------------------
    request_timeout: float = 15.0
    mail_timeout: float = 20.0

    # --- fixtures ----------------------------------------------------------
    user_password: str = "VikunjaQA123!"
    attach_traffic: bool = Field(
        default=True,
        description="Attach request and response bodies to the Allure report.",
    )

    # --- contract checking -------------------------------------------------
    # "strict" fails the test that produced a mismatch, "collect" records
    # them and reports at the end of the run, "off" disables the check.
    contract_mode: str = "strict"

    @property
    def api_v1(self) -> str:
        return f"{self.base_url.rstrip('/')}/api/v1"

    @property
    def api_v2(self) -> str:
        return f"{self.base_url.rstrip('/')}/api/v2"

    @property
    def db_dsn(self) -> str:
        return (
            f"postgresql://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
