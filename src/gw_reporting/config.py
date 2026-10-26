import os
from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    gw_enabled_tools: list[str] = []
    gw_disabled_tools: list[str] = []
    gw_base_url: str = ""
    gw_token: SecretStr = SecretStr("")
    # Preserve support for explicitly configured lab TLS exceptions.
    gw_tls_verify: bool = True
    allowed_projects: list[int] = []
    allowed_clients: list[int] = []
    gw_summary_field: str = ""
    gw_max_file_bytes: int = Field(default=20 * 1024 * 1024, gt=0, le=100 * 1024 * 1024)
    finding_type_id: int | None = Field(default=None, gt=0)


@lru_cache
def settings() -> Settings:
    return Settings(_env_file=os.environ.get("GW_REPORTING_ENV_FILE", ".env"))
