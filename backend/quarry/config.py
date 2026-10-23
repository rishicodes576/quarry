from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="QUARRY_", extra="ignore")
    env: Literal["development", "production", "test"] = "development"
    database_url: str = "postgresql+psycopg://quarry:quarry@postgres:5432/quarry"
    qdrant_url: str = "http://qdrant:6333"
    searxng_url: str = "http://searxng:8080"
    s3_endpoint: str = "http://objectstore:8334"
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_bucket: str = "quarry"
    data_dir: Path = Path("data")
    model_cache: str = "data/models"
    parser_socket: str = ""
    embedding_mode: str = "onnx"
    demo_seed: bool = False
    cookie_secure: bool = False
    session_secret: str = Field(min_length=48)
    proxy_secret: str = ""
    app_origin: str = "http://localhost:3000"
    signup_mode: str = "public"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_starttls: bool = True
    smtp_user: str = ""
    smtp_password: str = ""
    mail_from: str = "accounts@quarry.local"
    session_idle_seconds: int = Field(default=43_200, ge=300, le=604_800)
    groq_free_plan_confirmed: bool = False
    groq_api_key: str = Field(default="", validation_alias="GROQ_API_KEY")
    groq_model: str = "openai/gpt-oss-120b"
    allow_paid_providers: bool = False
    openai_api_key: str = Field(default="", validation_alias="OPENAI_API_KEY")
    openai_model: str = "gpt-4.1-mini"
    lease_seconds: int = 90
    max_attempts: int = 3
    max_upload_bytes: int = 10 * 1024 * 1024
    max_document_chars: int = 500_000
    max_run_seconds: int = 180
    max_model_calls: int = 3
    max_tool_calls: int = 6
    max_daily_tokens: int = 30_000
    max_pending_jobs: int = 50
    max_concurrent_runs: int = 4
    max_global_runs: int = Field(default=8, ge=1, le=1000)
    max_global_pending_jobs: int = Field(default=1000, ge=1, le=100000)
    max_global_daily_tokens: int = Field(default=100_000, ge=1)
    max_evaluation_daily_tokens: int = Field(default=100_000, ge=1)
    evaluation_pace_seconds: int = Field(default=60, ge=15, le=300)
    max_workspace_storage_bytes: int = Field(default=100 * 1024 * 1024, ge=1)
    max_global_storage_bytes: int = Field(default=5 * 1024 * 1024 * 1024, ge=1)
    max_workspaces: int = Field(default=1000, ge=1)
    max_workspace_conversations: int = Field(default=1000, ge=1)
    max_workspace_documents: int = Field(default=1000, ge=1)
    max_workspace_runs: int = Field(default=10_000, ge=1)
    max_workspace_members: int = Field(default=100, ge=1)
    qdrant_api_key: str = ""

    @model_validator(mode="after")
    def safe_configuration(self):
        if self.signup_mode not in {"invite", "public", "disabled"}:
            raise ValueError("Signup mode must be invite, public, or disabled")
        if self.embedding_mode != "onnx":
            raise ValueError("Quarry requires real ONNX embeddings")
        if not self.database_url.startswith("postgresql+psycopg://"):
            raise ValueError("Quarry requires PostgreSQL with psycopg; no SQLite fallback")
        if self.env == "production":
            if not self.parser_socket:
                raise ValueError("Production requires the credentialless parser service")
            if len(self.proxy_secret) < 32:
                raise ValueError("Production requires a private gateway signature secret")
            if self.signup_mode == "public" and not self.smtp_host:
                raise ValueError("Public signup requires configured verification email delivery")
            if self.smtp_host and not self.smtp_starttls:
                raise ValueError("Production email requires STARTTLS")
            if self.demo_seed or not self.cookie_secure:
                raise ValueError("Production requires secure cookies and no demo seed")
            if len(self.session_secret) < 48 or "development" in self.session_secret:
                raise ValueError("Production requires a random session secret of at least 48 chars")
            if not self.qdrant_url or len(self.qdrant_api_key) < 32 or len(self.s3_secret_key) < 32:
                raise ValueError("Production requires private Qdrant and S3 credentials")
            parsed = urlsplit(self.app_origin)
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username
                or parsed.query
                or parsed.fragment
                or parsed.path not in {"", "/"}
            ):
                raise ValueError("Production requires an HTTPS application origin")
        return self


@lru_cache
def settings() -> Settings:
    result = Settings()
    result.data_dir.mkdir(parents=True, exist_ok=True)
    return result
