"""Batch embedding + model loading (sentence-transformers).

Loads the model once (lazily), picks MPS > CUDA > CPU, batch-encodes with L2-normalized vectors.
The model loads only when something needs encoding, so a no-op rebuild never pays for it.
"""

from __future__ import annotations

import threading
from collections.abc import Sequence

import numpy as np

from .config import Config


class Embedder:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self._model = None
        self._lock = threading.Lock()

    def _device(self) -> str:
        if self.cfg.device:
            return self.cfg.device
        import torch

        if torch.backends.mps.is_available():
            return "mps"
        if torch.cuda.is_available():
            return "cuda"
        return "cpu"

    @property
    def model(self):
        # Lock so a background warmup thread and a query thread can't both load concurrently.
        if self._model is None:
            with self._lock:
                if self._model is None:
                    from sentence_transformers import SentenceTransformer

                    m = SentenceTransformer(
                        self.cfg.model_name,
                        trust_remote_code=self.cfg.trust_remote_code,
                        device=self._device(),
                    )
                    m.max_seq_length = self.cfg.max_seq_length
                    self._model = m
        return self._model

    def encode(self, texts: Sequence[str], show_progress: bool = False) -> np.ndarray:
        return self.model.encode(
            list(texts),
            batch_size=self.cfg.batch_size,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=show_progress,
        ).astype("float32")

    def encode_query(self, text: str) -> np.ndarray:
        return self.encode([text])[0]
