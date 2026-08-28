from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "development"

    postgres_db: str
    postgres_user: str
    postgres_password: str
    postgres_host: str = "postgres"
    postgres_port: int = 5432
    postgres_schema: str = "hippoai"

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
    hippo_response_max_tokens: int = 4096
    hippo_response_max_tokens_long: int = 8192
    # Deprecated: local attachment parsing now covers images/screenshots/documents.
    hippo_vision_model: str | None = None

    # AWS / S3 project storage
    aws_region: str | None = None
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None
    aws_session_token: str | None = None
    hippo_s3_bucket_name: str | None = None
    hippo_s3_bucket_prefix: str = "hippo-ai-"
    hippo_s3_key_prefix: str = "projects"

    # SMTP notifications
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_sender: str | None = None
    smtp_use_tls: bool = True
    smtp_use_ssl: bool = False
    smtp_timeout_seconds: int = 10

    # Bootstrap admin user created on startup if missing
    bootstrap_admin_full_name: str = "Valere Youbi"
    bootstrap_admin_email: str = "v.youbi@hipposideros.de"
    bootstrap_admin_password: str = "Royaume1991."

    # Local speech-to-text backend
    stt_model: str = "base"
    stt_device: str = "cpu"
    stt_compute_type: str = "int8"
    stt_language: str | None = "de"

    # Optional Hippo embedding endpoint
    hippo_embedding_url: str | None = None
    hippo_embedding_key: str | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )


settings = Settings()
