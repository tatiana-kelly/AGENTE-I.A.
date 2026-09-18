from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./sal_intelligence_os.db"

    supabase_relatorios_raw_url: str | None = None
    supabase_relatorios_raw_service_key: str | None = None

    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-sonnet-5"

    # Ponte SAL OS → AI Orchestrator (/v1/agent-runs). Sem estes valores o cliente não é construído.
    orchestrator_base_url: str | None = None
    agent_run_hmac_secret: str | None = None
    agent_run_principal: str = "service:sal-intelligence-os"
    agent_run_project: str = "sal-intelligence-os"

    environment: str = "development"


@lru_cache
def get_settings() -> Settings:
    return Settings()
