"""
ML model management with lazy loading and async batching.

Provides models for semantic search (bi-encoder) and reranking (cross-encoder).
Models are loaded on first access to minimize startup time.
Supports FP16 inference on GPU and async batching for concurrent requests.
"""

import asyncio
import logging
from typing import Optional

import numpy as np
import torch
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
            use_fp16 = config.ml.use_fp16 and device != "cpu"
            logger.info(f"Loading bi-encoder: {model_name} on {device} (fp16={use_fp16})")

            try:
                model_kwargs = {}
                if use_fp16:
                    model_kwargs["torch_dtype"] = torch.float16

                self._bi_encoder = SentenceTransformer(
                    model_name,
                    device=device,
                    model_kwargs=model_kwargs,
                )

                # Convert to FP16 if on GPU
                if use_fp16:
                    self._bi_encoder.half()

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
            use_fp16 = config.ml.use_fp16 and device != "cpu"
            logger.info(f"Loading cross-encoder: {model_name} on {device} (fp16={use_fp16})")

            try:
                self._cross_encoder = CrossEncoder(model_name, device=device)

                # Convert to FP16 if on GPU
                if use_fp16:
                    self._cross_encoder.model.half()

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


class AsyncEmbeddingBatcher:
    """
    Async batcher for bi-encoder inference.

    Collects encoding requests and batches them together for efficient GPU utilization.
    Uses a background task to process batches with configurable max wait time.
    """

    def __init__(self, model_manager: ModelManager):
        self._model_manager = model_manager
        self._queue: asyncio.Queue = asyncio.Queue()
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()

    async def start(self):
        """Start the background batch processing task."""
        async with self._lock:
            if not self._running:
                self._running = True
                self._task = asyncio.create_task(self._process_loop())
                logger.debug("AsyncEmbeddingBatcher started")

    async def stop(self):
        """Stop the background batch processing task."""
        async with self._lock:
            if self._running:
                self._running = False
                if self._task:
                    self._task.cancel()
                    try:
                        await self._task
                    except asyncio.CancelledError:
                        pass
                logger.debug("AsyncEmbeddingBatcher stopped")

    async def encode(self, texts: list[str]) -> np.ndarray:
        """
        Encode texts using batched inference.

        Args:
            texts: List of texts to encode

        Returns:
            numpy array of embeddings
        """
        if not self._running:
            await self.start()

        future: asyncio.Future = asyncio.Future()
        await self._queue.put((texts, future))
        return await future

    async def _process_loop(self):
        """Background loop that collects and processes batches."""
        max_wait = config.ml.batch_max_wait_ms / 1000.0
        max_size = config.ml.batch_max_size

        while self._running:
            try:
                batch_items: list[tuple[list[str], asyncio.Future]] = []

                # Wait for first item
                try:
                    item = await asyncio.wait_for(self._queue.get(), timeout=1.0)
                    batch_items.append(item)
                except asyncio.TimeoutError:
                    continue

                # Collect more items within max_wait window
                deadline = asyncio.get_event_loop().time() + max_wait
                total_texts = len(batch_items[0][0])

                while total_texts < max_size:
                    remaining = deadline - asyncio.get_event_loop().time()
                    if remaining <= 0:
                        break
                    try:
                        item = await asyncio.wait_for(self._queue.get(), timeout=remaining)
                        batch_items.append(item)
                        total_texts += len(item[0])
                    except asyncio.TimeoutError:
                        break

                # Process batch
                await self._process_batch(batch_items)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception(f"Error in embedding batch loop: {e}")

    async def _process_batch(self, batch_items: list[tuple[list[str], asyncio.Future]]):
        """Process a batch of encoding requests."""
        # Flatten all texts
        all_texts = []
        boundaries = [0]
        for texts, _ in batch_items:
            all_texts.extend(texts)
            boundaries.append(len(all_texts))

        try:
            # Run encoding in thread pool to not block event loop
            bi_encoder = self._model_manager.get_bi_encoder()
            embeddings = await asyncio.to_thread(
                bi_encoder.encode,
                all_texts,
                convert_to_tensor=False,
                show_progress_bar=False,
            )

            # Distribute results back to futures
            for i, (_, future) in enumerate(batch_items):
                start, end = boundaries[i], boundaries[i + 1]
                if not future.done():
                    future.set_result(embeddings[start:end])

        except Exception as e:
            # Propagate error to all futures
            for _, future in batch_items:
                if not future.done():
                    future.set_exception(e)


class AsyncCrossEncoderBatcher:
    """
    Async batcher for cross-encoder inference.

    Collects reranking requests and batches them together for efficient GPU utilization.
    """

    def __init__(self, model_manager: ModelManager):
        self._model_manager = model_manager
        self._queue: asyncio.Queue = asyncio.Queue()
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()

    async def start(self):
        """Start the background batch processing task."""
        async with self._lock:
            if not self._running:
                self._running = True
                self._task = asyncio.create_task(self._process_loop())
                logger.debug("AsyncCrossEncoderBatcher started")

    async def stop(self):
        """Stop the background batch processing task."""
        async with self._lock:
            if self._running:
                self._running = False
                if self._task:
                    self._task.cancel()
                    try:
                        await self._task
                    except asyncio.CancelledError:
                        pass
                logger.debug("AsyncCrossEncoderBatcher stopped")

    async def predict(self, pairs: list[list[str]]) -> np.ndarray:
        """
        Score query-document pairs using batched inference.

        Args:
            pairs: List of [query, document] pairs

        Returns:
            numpy array of scores
        """
        if not self._running:
            await self.start()

        future: asyncio.Future = asyncio.Future()
        await self._queue.put((pairs, future))
        return await future

    async def _process_loop(self):
        """Background loop that collects and processes batches."""
        max_wait = config.ml.batch_max_wait_ms / 1000.0
        max_size = config.ml.batch_max_size

        while self._running:
            try:
                batch_items: list[tuple[list[list[str]], asyncio.Future]] = []

                # Wait for first item
                try:
                    item = await asyncio.wait_for(self._queue.get(), timeout=1.0)
                    batch_items.append(item)
                except asyncio.TimeoutError:
                    continue

                # Collect more items within max_wait window
                deadline = asyncio.get_event_loop().time() + max_wait
                total_pairs = len(batch_items[0][0])

                while total_pairs < max_size:
                    remaining = deadline - asyncio.get_event_loop().time()
                    if remaining <= 0:
                        break
                    try:
                        item = await asyncio.wait_for(self._queue.get(), timeout=remaining)
                        batch_items.append(item)
                        total_pairs += len(item[0])
                    except asyncio.TimeoutError:
                        break

                # Process batch
                await self._process_batch(batch_items)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception(f"Error in cross-encoder batch loop: {e}")

    async def _process_batch(self, batch_items: list[tuple[list[list[str]], asyncio.Future]]):
        """Process a batch of reranking requests."""
        # Flatten all pairs
        all_pairs = []
        boundaries = [0]
        for pairs, _ in batch_items:
            all_pairs.extend(pairs)
            boundaries.append(len(all_pairs))

        try:
            # Run prediction in thread pool to not block event loop
            cross_encoder = self._model_manager.get_cross_encoder()
            scores = await asyncio.to_thread(cross_encoder.predict, all_pairs)

            # Distribute results back to futures
            for i, (_, future) in enumerate(batch_items):
                start, end = boundaries[i], boundaries[i + 1]
                if not future.done():
                    future.set_result(scores[start:end])

        except Exception as e:
            # Propagate error to all futures
            for _, future in batch_items:
                if not future.done():
                    future.set_exception(e)


# Global batchers (lazy initialized)
_embedding_batcher: Optional[AsyncEmbeddingBatcher] = None
_cross_encoder_batcher: Optional[AsyncCrossEncoderBatcher] = None


def get_embedding_batcher() -> AsyncEmbeddingBatcher:
    """Get the global AsyncEmbeddingBatcher instance."""
    global _embedding_batcher
    if _embedding_batcher is None:
        _embedding_batcher = AsyncEmbeddingBatcher(get_model_manager())
    return _embedding_batcher


def get_cross_encoder_batcher() -> AsyncCrossEncoderBatcher:
    """Get the global AsyncCrossEncoderBatcher instance."""
    global _cross_encoder_batcher
    if _cross_encoder_batcher is None:
        _cross_encoder_batcher = AsyncCrossEncoderBatcher(get_model_manager())
    return _cross_encoder_batcher
