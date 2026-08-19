from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="HIPPO_AI_", env_file=".env", extra="ignore")

    app_name: str = "hippo-ai"
    version: str = "0.1.0"
    admin_user: str = "hippo"
    admin_password: str = "hippo"
    jwt_secret: str = Field(default="change-me")
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 720
    data_root: Path = Path("workspace")

    @property
    def projects_dir(self) -> Path:
        return self.data_root / "projects"

    @property
    def logs_dir(self) -> Path:
        return self.data_root / "logs"

    @property
    def audit_dir(self) -> Path:
        return self.data_root / "audit"

    @property
    def backups_dir(self) -> Path:
        return self.data_root / "backups"

    @property
    def state_dir(self) -> Path:
        return self.data_root / "state"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()

