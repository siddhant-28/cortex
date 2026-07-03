"""Integration tests for IncrementalIndexer + RepoWatcher using a fake embedder (no model load).

Exercises the real LanceDB store and manifest, so it validates reconcile/reindex/remove and that a
freshly reindexed file is immediately FTS-searchable (the freshness guarantee).
"""

from __future__ import annotations

import time

import numpy as np
import pytest

from cortex.config import Config
from cortex.indexer import IncrementalIndexer


class FakeEmbedder:
    """Deterministic vectors so tests never load the real model."""

    def __init__(self, dim: int) -> None:
        self.dim = dim

    def encode(self, texts, show_progress: bool = False) -> np.ndarray:
        return np.zeros((len(texts), self.dim), dtype="float32")


@pytest.fixture
def repo(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "alpha.py").write_text("def alpha_one():\n    return 'zebra_token'\n")
    (src / "beta.py").write_text("def beta_two():\n    return 2\n")
    return tmp_path / "src"


def make_indexer(home, alias, root):
    cfg = Config(home=home)
    return IncrementalIndexer(cfg, alias, root, embedder=FakeEmbedder(cfg.embed_dim))


def _fts(idx, token):
    return [r["path"] for r in
            idx.store.table().search(token, query_type="fts").limit(5).to_list()]


def test_reconcile_indexes_all_files(tmp_path, repo):
    idx = make_indexer(tmp_path / "home", "demo", repo)
    stats = idx.reconcile()
    assert stats["changed"] == 2 and stats["removed"] == 0
    assert idx.store.count("demo") >= 2
    assert set(idx.manifest.files) == {"alpha.py", "beta.py"}
    assert idx.manifest.root == str(repo.resolve())


def test_reconcile_second_run_is_noop(tmp_path, repo):
    idx = make_indexer(tmp_path / "home", "demo", repo)
    idx.reconcile()
    stats = make_indexer(tmp_path / "home", "demo", repo).reconcile()
    assert stats["changed"] == 0 and stats["removed"] == 0


def test_reindex_path_picks_up_edit(tmp_path, repo):
    idx = make_indexer(tmp_path / "home", "demo", repo)
    idx.reconcile()
    (repo / "alpha.py").write_text("def alpha_one():\n    return 'giraffe_token'\n")
    assert idx.reindex_path("alpha.py") is True
    assert "alpha.py" in _fts(idx, "giraffe_token")  # new content immediately searchable
    assert idx.reindex_path("alpha.py") is False  # unchanged second time


def test_reindex_path_handles_new_and_deleted(tmp_path, repo):
    idx = make_indexer(tmp_path / "home", "demo", repo)
    idx.reconcile()
    (repo / "gamma.py").write_text("def gamma_three():\n    return 3\n")
    assert idx.reindex_path("gamma.py") is True
    assert "gamma.py" in idx.manifest.files
    (repo / "gamma.py").unlink()
    assert idx.reindex_path("gamma.py") is True  # routed to removal
    assert "gamma.py" not in idx.manifest.files


def test_watcher_reindexes_on_save(tmp_path, repo):
    from cortex.watcher import RepoWatcher

    idx = make_indexer(tmp_path / "home", "demo", repo)
    idx.reconcile()
    watcher = RepoWatcher(idx, debounce=0.2)
    watcher.start()
    try:
        (repo / "alpha.py").write_text("def alpha_one():\n    return 'okapi_token'\n")
        deadline = time.time() + 5
        while time.time() < deadline and "alpha.py" not in _fts(idx, "okapi_token"):
            time.sleep(0.1)
        assert "alpha.py" in _fts(idx, "okapi_token")
    finally:
        watcher.stop()
