from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="KNOWDELTA_", env_file=".env", extra="ignore")
    database_url: str = "postgresql+psycopg://knowdelta:knowdelta_local@127.0.0.1:54329/knowdelta"
    redis_url: str = "redis://127.0.0.1:63799/0"
    data_root: Path = Path("data")
    cors_origins: list[str] = [
        "http://127.0.0.1:5174",
        "http://localhost:5174",
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    ]
    max_upload_mb: int = 2048
    api_host: str = "127.0.0.1"
    api_port: int = 8000

    @property
    def jobs_root(self) -> Path:
        return self.data_root.resolve() / "jobs"


@lru_cache
def get_settings() -> Settings:
    return Settings()
