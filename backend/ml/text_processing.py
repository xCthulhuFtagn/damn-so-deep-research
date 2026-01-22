"""
ML model management with lazy loading.

Provides models for semantic search (bi-encoder) and reranking (cross-encoder).
Models are loaded on first access to minimize startup time.
"""

import logging
from typing import Optional

from langchain_text_splitters import RecursiveCharacterTextSplitter
from sentence_transformers import CrossEncoder, SentenceTransformer

from backend.core.config import config
from backend.core.exceptions import ModelError

logger = logging.getLogger(__name__)


class ModelManager:
    """
    Singleton manager for ML models with lazy loading.

    Models are loaded only when first accessed, improving startup time.
    """

    _instance: Optional["ModelManager"] = None
    _bi_encoder: Optional[SentenceTransformer] = None
    _cross_encoder: Optional[CrossEncoder] = None
    _text_splitter: Optional[RecursiveCharacterTextSplitter] = None

    def __new__(cls):
        """Ensure singleton pattern."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            logger.debug("ModelManager singleton created")
        return cls._instance

    def get_bi_encoder(self) -> SentenceTransformer:
        """
        Get bi-encoder model for semantic search (lazy loaded).

        Returns:
            SentenceTransformer model for encoding queries and documents

        Raises:
            ModelError: If model fails to load
        """
        if self._bi_encoder is None:
            model_name = config.ml.bi_encoder_model
            device = config.ml.device
            logger.info(f"Loading bi-encoder: {model_name} on {device}")

            try:
                self._bi_encoder = SentenceTransformer(model_name, device=device)
                logger.info("Bi-encoder loaded successfully")
            except Exception as e:
                raise ModelError(f"Failed to load bi-encoder '{model_name}': {e}") from e

        return self._bi_encoder

    def get_cross_encoder(self) -> CrossEncoder:
        """
        Get cross-encoder model for reranking (lazy loaded).

        Returns:
            CrossEncoder model for query-document pair scoring

        Raises:
            ModelError: If model fails to load
        """
        if self._cross_encoder is None:
            model_name = config.ml.cross_encoder_model
            device = config.ml.device
            logger.info(f"Loading cross-encoder: {model_name} on {device}")

            try:
                self._cross_encoder = CrossEncoder(model_name, device=device)
                logger.info("Cross-encoder loaded successfully")
            except Exception as e:
                raise ModelError(f"Failed to load cross-encoder '{model_name}': {e}") from e

        return self._cross_encoder

    def get_text_splitter(self) -> RecursiveCharacterTextSplitter:
        """
        Get text splitter for chunking documents (lazy loaded).

        Returns:
            RecursiveCharacterTextSplitter configured from settings
        """
        if self._text_splitter is None:
            logger.debug("Creating text splitter")
            self._text_splitter = RecursiveCharacterTextSplitter(
                chunk_size=config.search.max_chunk_size,
                chunk_overlap=config.search.chunk_overlap,
                separators=["\n\n", "\n", ". ", " ", ""],
                length_function=len,
            )
        return self._text_splitter

    def unload_models(self) -> None:
        """
        Unload all models from memory.

        Models will be reloaded on next access.
        """
        if self._bi_encoder is not None or self._cross_encoder is not None:
            logger.info("Unloading ML models")
            self._bi_encoder = None
            self._cross_encoder = None
            logger.info("Models unloaded")

    def is_loaded(self, model_type: str) -> bool:
        """
        Check if a specific model is currently loaded.

        Args:
            model_type: One of 'bi_encoder', 'cross_encoder', 'text_splitter'

        Returns:
            True if the model is loaded
        """
        if model_type == "bi_encoder":
            return self._bi_encoder is not None
        elif model_type == "cross_encoder":
            return self._cross_encoder is not None
        elif model_type == "text_splitter":
            return self._text_splitter is not None
        else:
            raise ValueError(f"Unknown model type: {model_type}")


# Global singleton
_model_manager: Optional[ModelManager] = None


def get_model_manager() -> ModelManager:
    """Get the global ModelManager instance."""
    global _model_manager
    if _model_manager is None:
        _model_manager = ModelManager()
    return _model_manager
