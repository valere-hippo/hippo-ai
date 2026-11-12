from pydantic import AliasChoices, Field, field_validator
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

    # Hippo model hub
    hippo_api_url: str | None = Field(default=None, validation_alias=AliasChoices("HIPPO_AI_BASE_URL", "HIPPO_API_URL"))
    hippo_api_key: str | None = Field(default=None, validation_alias=AliasChoices("HIPPO_API_KEY",))
    hippo_model: str = Field(
        default="/root/autodl-tmp/hippo-ai-v2/models/Qwen3-Omni-30B-A3B-Instruct",
        validation_alias=AliasChoices("HIPPO_AI_MODEL", "HIPPO_MODEL"),
    )
    hippo_vision_url: str | None = None
    hippo_response_max_tokens: int = 4096
    hippo_response_max_tokens_long: int = 8192
    hippo_response_timeout_seconds: int = 900
    hippo_response_timeout_seconds_long: int = 1500
    # Deprecated: local attachment parsing now covers images/screenshots/documents.
    hippo_vision_model: str | None = None

    # Provider-specific model hubs for workflow routing
    claude_api_url: str | None = Field(default=None, validation_alias=AliasChoices("CLAUDE_API_BASE_URL", "ANTHROPIC_API_URL"))
    claude_api_key: str | None = Field(default=None, validation_alias=AliasChoices("CLAUDE_API_KEY", "ANTHROPIC_API_KEY"))
    claude_model: str | None = Field(default="claude-3-5-sonnet", validation_alias=AliasChoices("CLAUDE_MODEL", "ANTHROPIC_MODEL"))
    deepseek_api_url: str | None = Field(default=None, validation_alias=AliasChoices("DEEPSEEK_API_BASE_URL", "DEEPSEEK_API_URL"))
    deepseek_api_key: str | None = Field(default=None, validation_alias=AliasChoices("DEEPSEEK_API_KEY",))
    deepseek_model: str | None = Field(default="deepseek-chat", validation_alias=AliasChoices("DEEPSEEK_MODEL",))
    qwen_api_url: str | None = Field(default=None, validation_alias=AliasChoices("QWEN_API_BASE_URL", "QWEN_API_URL", "ALIBABA_API_URL"))
    qwen_api_key: str | None = Field(default=None, validation_alias=AliasChoices("QWEN_API_KEY", "ALIBABA_API_KEY"))
    qwen_model: str | None = Field(default="qwen-plus", validation_alias=AliasChoices("QWEN_MODEL", "ALIBABA_MODEL"))
    tencent_api_url: str | None = Field(default=None, validation_alias=AliasChoices("TENCENT_API_BASE_URL", "TENCENT_API_URL"))
    tencent_api_key: str | None = Field(default=None, validation_alias=AliasChoices("TENCENT_API_KEY",))
    tencent_model: str | None = Field(default="hunyuan-turbo", validation_alias=AliasChoices("TENCENT_MODEL", "HUNYUAN_MODEL"))

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

    @field_validator("hippo_model", mode="before")
    @classmethod
    def normalize_hippo_model(cls, value: str | None) -> str:
        raw = (value or "").strip()
        if not raw:
            return "gpt-4o-mini"
        if raw.lower() == "gpt-5o-mini":
            return "gpt-4o-mini"
        return raw

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )


settings = Settings()
