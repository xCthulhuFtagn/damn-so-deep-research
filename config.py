"""
Configuration management with Pydantic validation.

This module provides a type-safe, validated configuration system for the research application.
All settings are loaded from environment variables with sensible defaults.
"""

import os
from pathlib import Path
from typing import Optional
from pydantic import BaseModel, Field, field_validator
from dotenv import load_dotenv

# Load .env file
env_path = Path('.') / '.env'
load_dotenv(dotenv_path=env_path)

# Fix for httpx proxy scheme validation (httpx doesn't support 'socks://', only 'socks5://')
for key in ['ALL_PROXY', 'all_proxy']:
    val = os.getenv(key)
    if val and val.startswith('socks://'):
        os.environ[key] = val.replace('socks://', 'socks5://', 1)


class LLMConfig(BaseModel):
    """LLM API configuration."""

    api_key: str
    base_url: str
    model: str = "gpt-oss-20b"

    @field_validator("api_key")
    @classmethod
    def validate_api_key(cls, v: str) -> str:
        # Allow "EMPTY" for local development with vLLM (doesn't validate API keys)
        if not v or (v.strip() == "" and v != "EMPTY"):
            raise ValueError("LLM API key is required (use 'EMPTY' for local vLLM)")
        return v

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, v: str) -> str:
        if not v or v.strip() == "":
            raise ValueError("LLM base URL is required")
        return v


class MLConfig(BaseModel):
    """Machine learning models configuration."""

    bi_encoder_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    cross_encoder_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    device: str = "cpu"

    @field_validator("device")
    @classmethod
    def validate_device(cls, v: str) -> str:
        if v not in ["cpu", "cuda", "mps"]:
            raise ValueError("device must be one of: cpu, cuda, mps")
        return v


class NetworkConfig(BaseModel):
    """Network and HTTP configuration."""

    default_timeout: int = Field(default=120, ge=1, le=600)
    max_retries: int = Field(default=3, ge=0, le=10)
    retry_backoff: float = Field(default=2.0, ge=0.1)
    connection_pool_size: int = Field(default=10, ge=1, le=100)


class SearchConfig(BaseModel):
    """Search and content processing configuration."""

    max_search_results: int = Field(default=6, ge=1, le=50)
    max_final_top_chunks: int = Field(default=3, ge=1, le=20)
    max_chunk_size: int = Field(default=500, ge=100, le=2000)
    min_chunk_len_to_merge: int = Field(default=100, ge=10, le=500)
    chunk_overlap: int = Field(default=150, ge=0, le=500)
    bi_encoder_threshold: float = Field(default=0.2, ge=0.0, le=1.0)
    cross_encoder_threshold: float = Field(default=-1.0, ge=-10.0, le=10.0)


class FirecrawlConfig(BaseModel):
    """Firecrawl API configuration."""

    base_url: str = "http://localhost:3002"
    api_key: str = "dummy_token"


class DatabaseConfig(BaseModel):
    """Database configuration."""

    db_name: str = "research_state.db"
    base_dir: Path = Path("db")

    @property
    def db_path(self) -> str:
        """Full path to the database file."""
        return str(self.base_dir / self.db_name)


class RunnerConfig(BaseModel):
    """Research runner configuration."""

    max_turns: int = Field(default=25, ge=1, le=200)
    max_retries: int = Field(default=3, ge=0, le=10)


class LoggingConfig(BaseModel):
    """Logging configuration."""

    log_level: str = "INFO"
    log_file: Optional[str] = None

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        v_upper = v.upper()
        if v_upper not in valid_levels:
            raise ValueError(f"log_level must be one of: {', '.join(valid_levels)}")
        return v_upper


class AppConfig(BaseModel):
    """Main application configuration."""

    llm: LLMConfig
    ml: MLConfig
    network: NetworkConfig
    search: SearchConfig
    firecrawl: FirecrawlConfig
    database: DatabaseConfig
    runner: RunnerConfig
    logging: LoggingConfig


def load_config() -> AppConfig:
    """Load configuration from environment variables."""
    try:
        return AppConfig(
            llm=LLMConfig(
                api_key=os.getenv("OPENAI_API_KEY", ""),
                base_url=os.getenv("OPENAI_BASE_URL", ""),
                model=os.getenv("OPENAI_MODEL", "gpt-oss-20b")
            ),
            ml=MLConfig(
                bi_encoder_model=os.getenv("BI_ENCODER_MODEL", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"),
                cross_encoder_model=os.getenv("CROSS_ENCODER_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2"),
                device=os.getenv("ML_DEVICE", "cpu")
            ),
            network=NetworkConfig(
                default_timeout=int(os.getenv("DEFAULT_TIMEOUT", "120")),
                max_retries=int(os.getenv("MAX_RETRIES", "3")),
                retry_backoff=float(os.getenv("RETRY_BACKOFF", "2.0")),
                connection_pool_size=int(os.getenv("CONNECTION_POOL_SIZE", "10"))
            ),
            search=SearchConfig(
                max_search_results=int(os.getenv("MAX_SEARCH_RESULTS", "6")),
                max_final_top_chunks=int(os.getenv("MAX_FINAL_TOP_CHUNKS", "3")),
                max_chunk_size=int(os.getenv("MAX_CHUNK_SIZE", "500")),
                min_chunk_len_to_merge=int(os.getenv("MIN_CHUNK_LEN_TO_MERGE", "100")),
                chunk_overlap=int(os.getenv("CHUNK_OVERLAP", "150")),
                bi_encoder_threshold=float(os.getenv("BI_ENCODER_THRESHOLD", "0.2")),
                cross_encoder_threshold=float(os.getenv("CROSS_ENCODER_THRESHOLD", "-1.0"))
            ),
            firecrawl=FirecrawlConfig(
                base_url=os.getenv("FIRECRAWL_BASE_URL", "http://localhost:3002"),
                api_key=os.getenv("FIRECRAWL_API_KEY", "dummy_token")
            ),
            database=DatabaseConfig(
                db_name=os.getenv("DB_NAME", "research_state.db"),
                base_dir=Path("db")
            ),
            runner=RunnerConfig(
                max_turns=int(os.getenv("MAX_TURNS", "25")),
                max_retries=int(os.getenv("MAX_RETRIES", "3"))
            ),
            logging=LoggingConfig(
                log_level=os.getenv("LOG_LEVEL", "INFO"),
                log_file=os.getenv("LOG_FILE")
            )
        )
    except ValueError as e:
        print(f"❌ Configuration validation failed: {e}")
        print("Please check your .env file and ensure all required variables are set.")
        raise


# Global configuration singleton
config = load_config()

# Backward compatibility - expose commonly used values at module level
# These will be deprecated in future versions
OPENAI_API_KEY = config.llm.api_key
OPENAI_BASE_URL = config.llm.base_url
MODEL = config.llm.model
MAX_TURNS = config.runner.max_turns
MAX_RETRIES = config.runner.max_retries
MAX_SEARCH_RESULTS = config.search.max_search_results
MAX_FINAL_TOP_CHUNKS = config.search.max_final_top_chunks
MAX_CHUNK_SIZE = config.search.max_chunk_size
MIN_CHUNK_LEN_TO_MERGE = config.search.min_chunk_len_to_merge
CHUNK_OVERLAP = config.search.chunk_overlap
DEFAULT_TIMEOUT = config.network.default_timeout
FIRECRAWL_BASE_URL = config.firecrawl.base_url
FIRECRAWL_API_KEY = config.firecrawl.api_key
LOG_LEVEL = config.logging.log_level
LOG_FILE = config.logging.log_file
DB_NAME = config.database.db_name
BASE_DIR = config.database.base_dir
DB_PATH = config.database.db_path
