from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "SceneChoice"
    app_env: str = "development"
    debug: bool = False
    # Persistence is introduced in M2. The default is a file next to the
    # process working directory; deployments should set
    # SCENECHOICE_DATABASE_URL to an absolute path (see docs/ARCHITECTURE.md).
    database_url: str = Field(default="sqlite:///./scenechoice.db", min_length=1)
    deepseek_api_key: SecretStr | None = None
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"
    deepseek_timeout_seconds: float = Field(default=30.0, gt=0, le=120)
    deepseek_max_tokens: int = Field(default=4096, ge=256, le=8192)
    story_planning_max_attempts: int = Field(default=3, ge=1, le=5)
    story_planning_retry_base_seconds: float = Field(default=0.5, ge=0, le=10)
    story_planning_retry_max_seconds: float = Field(default=8.0, ge=0, le=60)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="SCENECHOICE_",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
