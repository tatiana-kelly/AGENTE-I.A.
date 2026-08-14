from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./sal_intelligence_os.db"

    supabase_relatorios_raw_url: str | None = None
    supabase_relatorios_raw_service_key: str | None = None

    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-sonnet-5"

    environment: str = "development"


@lru_cache
def get_settings() -> Settings:
    return Settings()
