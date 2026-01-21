"""
ML model management with lazy loading and singleton pattern.

This module provides a singleton manager for ML models that loads them only when first needed,
significantly improving application startup time and memory efficiency.
"""

from typing import Optional
import logging
from sentence_transformers import SentenceTransformer, CrossEncoder
from langchain_text_splitters import RecursiveCharacterTextSplitter

from config import config
from exceptions import ModelError

logger = logging.getLogger(__name__)


class ModelManager:
    """
    Singleton manager for ML models with lazy loading.

    Models are loaded only when first accessed, improving startup time.
    All models can be unloaded to free memory if needed.
    """

    _instance: Optional['ModelManager'] = None
    _bi_encoder: Optional[SentenceTransformer] = None
    _cross_encoder: Optional[CrossEncoder] = None
    _text_splitter: Optional[RecursiveCharacterTextSplitter] = None

    def __new__(cls):
        """Ensure only one instance exists (singleton pattern)."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            logger.debug("ModelManager singleton instance created")
        return cls._instance

    def get_bi_encoder(self) -> SentenceTransformer:
        """
        Get bi-encoder model for semantic search (lazy loaded).

        Returns:
            SentenceTransformer: Bi-encoder model instance

        Raises:
            ModelError: If model fails to load
        """
        if self._bi_encoder is None:
            model_name = config.ml.bi_encoder_model
            device = config.ml.device
            logger.info(f"Loading bi-encoder model: {model_name} on device: {device}")

            try:
                self._bi_encoder = SentenceTransformer(model_name, device=device)
                logger.info("Bi-encoder loaded successfully")
            except Exception as e:
                error_msg = f"Failed to load bi-encoder model '{model_name}': {e}"
                logger.error(error_msg)
                raise ModelError(error_msg) from e

        return self._bi_encoder

    def get_cross_encoder(self) -> CrossEncoder:
        """
        Get cross-encoder model for reranking (lazy loaded).

        Returns:
            CrossEncoder: Cross-encoder model instance

        Raises:
            ModelError: If model fails to load
        """
        if self._cross_encoder is None:
            model_name = config.ml.cross_encoder_model
            device = config.ml.device
            logger.info(f"Loading cross-encoder model: {model_name} on device: {device}")

            try:
                self._cross_encoder = CrossEncoder(model_name, device=device)
                logger.info("Cross-encoder loaded successfully")
            except Exception as e:
                error_msg = f"Failed to load cross-encoder model '{model_name}': {e}"
                logger.error(error_msg)
                raise ModelError(error_msg) from e

        return self._cross_encoder

    def get_text_splitter(self) -> RecursiveCharacterTextSplitter:
        """
        Get text splitter for chunking documents (lazy loaded).

        Returns:
            RecursiveCharacterTextSplitter: Text splitter instance
        """
        if self._text_splitter is None:
            logger.debug("Creating text splitter")
            self._text_splitter = RecursiveCharacterTextSplitter(
                chunk_size=config.search.max_chunk_size,
                chunk_overlap=config.search.chunk_overlap,
                separators=["\n\n", "\n", ". ", " ", ""],
                length_function=len
            )
        return self._text_splitter

    def unload_models(self):
        """
        Unload all models from memory.

        Useful for freeing memory when models are no longer needed.
        Models will be reloaded on next access.
        """
        if self._bi_encoder is not None or self._cross_encoder is not None:
            logger.info("Unloading ML models from memory")
            self._bi_encoder = None
            self._cross_encoder = None
            logger.info("Models unloaded successfully")
        else:
            logger.debug("No models to unload")

    def is_loaded(self, model_type: str) -> bool:
        """
        Check if a specific model is currently loaded.

        Args:
            model_type: One of 'bi_encoder', 'cross_encoder', 'text_splitter'

        Returns:
            bool: True if the model is loaded, False otherwise
        """
        if model_type == 'bi_encoder':
            return self._bi_encoder is not None
        elif model_type == 'cross_encoder':
            return self._cross_encoder is not None
        elif model_type == 'text_splitter':
            return self._text_splitter is not None
        else:
            raise ValueError(f"Unknown model type: {model_type}")


# Global singleton instance
model_manager = ModelManager()

# Backward compatibility - expose models directly (will be lazy loaded)
# These will be deprecated in future versions in favor of model_manager.get_*()
def _get_bi_encoder():
    """Backward compatibility wrapper."""
    return model_manager.get_bi_encoder()

def _get_cross_encoder():
    """Backward compatibility wrapper."""
    return model_manager.get_cross_encoder()

def _get_text_splitter():
    """Backward compatibility wrapper."""
    return model_manager.get_text_splitter()

# Note: These will trigger lazy loading on first access
# For explicit control, use model_manager.get_bi_encoder() etc.
