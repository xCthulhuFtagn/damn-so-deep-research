"""
ML package for text processing and semantic search.

Provides lazy-loaded models for bi-encoder and cross-encoder operations.
"""

from backend.ml.text_processing import ModelManager, get_model_manager

__all__ = ["ModelManager", "get_model_manager"]
