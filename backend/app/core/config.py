from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "development"

    postgres_db: str
    postgres_user: str
    postgres_password: str
    postgres_host: str = "postgres"
    postgres_port: int = 5432

    redis_port: int = 6379

    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60

    # OpenAI (deprecated) / External Hippo model
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"

    # Hippo model hub
    hippo_api_url: str | None = None
    hippo_api_key: str | None = None
    hippo_model: str = "hippo-ai"
    # Deprecated: local attachment parsing now covers images/screenshots/documents.
    hippo_vision_model: str | None = None

    # Optional Whisper/transcription endpoint (if you run a Whisper service)
    whisper_api_url: str | None = None
    whisper_api_key: str | None = None

    # Optional Hippo embedding endpoint
    hippo_embedding_url: str | None = None
    hippo_embedding_key: str | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )


settings = Settings()
