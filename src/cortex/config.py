"""Config load/validate.

Per-machine config at ``~/.cortex/config.toml`` (optional); index data under ``~/.cortex/index/``.
Override the home dir with ``CORTEX_HOME`` (useful for tests). Only a small, boring set of knobs.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path


def _default_home() -> Path:
    return Path(os.environ.get("CORTEX_HOME", Path.home() / ".cortex"))


@dataclass
class Config:
    home: Path
    model_name: str = "jinaai/jina-embeddings-v2-base-code"
    embed_dim: int = 768
    batch_size: int = 64
    max_seq_length: int = 512
    device: str | None = None  # None = auto (mps > cuda > cpu)
    trust_remote_code: bool = True

    @property
    def index_dir(self) -> Path:
        return self.home / "index"

    @property
    def db_dir(self) -> Path:
        return self.index_dir / "lancedb"

    @property
    def manifest_dir(self) -> Path:
        return self.index_dir / "manifests"


def load_config() -> Config:
    home = _default_home()
    cfg = Config(home=home)
    toml = home / "config.toml"
    if toml.exists():
        data = tomllib.loads(toml.read_text())
        for k, v in data.items():
            if hasattr(cfg, k) and k != "home":
                setattr(cfg, k, v)
    return cfg
