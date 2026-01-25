"""
Configuration management with Pydantic Settings.

Uses pydantic-settings for environment variable loading with type validation.
"""

import os
from pathlib import Path
from typing import Optional
from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# Fix for httpx proxy scheme validation
for key in ["ALL_PROXY", "all_proxy"]:
    val = os.getenv(key)
    if val and val.startswith("socks://"):
        os.environ[key] = val.replace("socks://", "socks5://", 1)


class LLMSettings(BaseSettings):
    """LLM API configuration."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    api_key: str = Field(default="EMPTY", validation_alias="OPENAI_API_KEY")
    base_url: str = Field(default="http://localhost:8000/v1", validation_alias="OPENAI_BASE_URL")
    model: str = Field(default="gpt-oss-20b", validation_alias="OPENAI_MODEL")

    @field_validator("api_key")
    @classmethod
    def validate_api_key(cls, v: str) -> str:
        if not v or (v.strip() == "" and v != "EMPTY"):
            raise ValueError("LLM API key is required (use 'EMPTY' for local vLLM)")
        return v


class MLSettings(BaseSettings):
    """Machine learning models configuration."""

    model_config = SettingsConfigDict(env_prefix="ML_")

    bi_encoder_model: str = Field(
        default="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        alias="BI_ENCODER_MODEL",
    )
    cross_encoder_model: str = Field(
        default="cross-encoder/ms-marco-MiniLM-L-6-v2",
        alias="CROSS_ENCODER_MODEL",
    )
    device: str = Field(default="cpu", alias="ML_DEVICE")

    @field_validator("device")
    @classmethod
    def validate_device(cls, v: str) -> str:
        if v not in ["cpu", "cuda", "mps"]:
            raise ValueError("device must be one of: cpu, cuda, mps")
        return v


class SearchSettings(BaseSettings):
    """Search and content processing configuration."""

    model_config = SettingsConfigDict(env_prefix="SEARCH_")

    max_search_results: int = Field(default=6, ge=1, le=50, alias="MAX_SEARCH_RESULTS")
    max_final_top_chunks: int = Field(default=3, ge=1, le=20, alias="MAX_FINAL_TOP_CHUNKS")
    max_chunk_size: int = Field(default=500, ge=100, le=2000, alias="MAX_CHUNK_SIZE")
    min_chunk_len_to_merge: int = Field(default=100, ge=10, le=500, alias="MIN_CHUNK_LEN_TO_MERGE")
    chunk_overlap: int = Field(default=150, ge=0, le=500, alias="CHUNK_OVERLAP")
    bi_encoder_threshold: float = Field(default=0.2, ge=0.0, le=1.0, alias="BI_ENCODER_THRESHOLD")
    cross_encoder_threshold: float = Field(default=-1.0, ge=-10.0, le=10.0, alias="CROSS_ENCODER_THRESHOLD")


class FirecrawlSettings(BaseSettings):
    """Firecrawl API configuration."""

    model_config = SettingsConfigDict(env_prefix="FIRECRAWL_")

    base_url: str = Field(default="http://localhost:3002", alias="FIRECRAWL_BASE_URL")
    api_key: str = Field(default="dummy_token", alias="FIRECRAWL_API_KEY")


class DatabaseSettings(BaseSettings):
    """Database configuration."""

    model_config = SettingsConfigDict(env_prefix="DB_")

    app_db_name: str = Field(default="app.db", alias="APP_DB_NAME")
    langgraph_db_name: str = Field(default="langgraph.db", alias="LANGGRAPH_DB_NAME")
    # Base dir relative to project root
    base_dir: Path = Field(
        default=Path(__file__).resolve().parent.parent.parent / "db",
        alias="DB_BASE_DIR"
    )

    @property
    def app_db_path(self) -> str:
        """Full path to the application database."""
        return str(self.base_dir / self.app_db_name)

    @property
    def langgraph_db_path(self) -> str:
        """Full path to the LangGraph checkpoint database."""
        # AsyncSqliteSaver.from_conn_string expects a URI or path
        # We use strict path to avoid CWD ambiguity
        return str(self.base_dir / self.langgraph_db_name)


class RunnerSettings(BaseSettings):
    """Research runner configuration."""

    model_config = SettingsConfigDict(env_prefix="RUNNER_")

    max_turns: int = Field(default=25, ge=1, le=200, alias="MAX_TURNS")
    max_retries: int = Field(default=3, ge=0, le=10, alias="MAX_RETRIES")


class ResearchSettings(BaseSettings):
    """Research agent configuration."""

    model_config = SettingsConfigDict(env_prefix="RESEARCH_")

    # Plan limits
    min_plan_steps: int = Field(default=3, ge=1, le=20, alias="RESEARCH_MIN_PLAN_STEPS")
    max_plan_steps: int = Field(default=10, ge=1, le=50, alias="RESEARCH_MAX_PLAN_STEPS")

    # Per-step recovery
    max_substeps: int = Field(default=3, ge=1, le=10, alias="RESEARCH_MAX_SUBSTEPS")
    max_searches_per_step: int = Field(default=3, ge=1, le=10, alias="RESEARCH_MAX_SEARCHES_PER_STEP")


class AuthSettings(BaseSettings):
    """Authentication configuration."""

    model_config = SettingsConfigDict(env_prefix="AUTH_")

    secret_key: str = Field(
        default="your-secret-key-change-in-production",
        alias="AUTH_SECRET_KEY",
    )
    algorithm: str = Field(default="HS256", alias="AUTH_ALGORITHM")
    access_token_expire_minutes: int = Field(default=1440, alias="AUTH_TOKEN_EXPIRE_MINUTES")  # 24 hours


class Settings(BaseSettings):
    """Main application settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # App info
    app_name: str = Field(default="Damn So Deep Research", alias="APP_NAME")
    debug: bool = Field(default=False, alias="DEBUG")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    # Nested settings
    llm: LLMSettings = Field(default_factory=LLMSettings)
    ml: MLSettings = Field(default_factory=MLSettings)
    search: SearchSettings = Field(default_factory=SearchSettings)
    firecrawl: FirecrawlSettings = Field(default_factory=FirecrawlSettings)
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    runner: RunnerSettings = Field(default_factory=RunnerSettings)
    auth: AuthSettings = Field(default_factory=AuthSettings)
    research: ResearchSettings = Field(default_factory=ResearchSettings)

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        v_upper = v.upper()
        if v_upper not in valid_levels:
            raise ValueError(f"log_level must be one of: {', '.join(valid_levels)}")
        return v_upper


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


# Global config instance
config = get_settings()
