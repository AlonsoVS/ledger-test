from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LEDGER_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://ledger:ledger@localhost:55432/ledger"


@lru_cache
def get_settings() -> Settings:
    return Settings()
