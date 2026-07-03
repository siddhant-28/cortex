"""Incremental indexing shared by `build`, the watcher, and startup reconciliation.

`reconcile()` is a full hash-sweep diff+apply (used by `cortex build` and at watcher startup to
catch offline changes). `reindex_path()` / `remove_path()` handle a single file (used by the
watcher on FS events). All mutations are lock-guarded so watcher timer threads can't race.

New rows are searchable immediately after upsert (LanceDB flat-scans the unindexed tail), so
single-file reindex does NOT rebuild the FTS index — only `reconcile()` (re)builds it and compacts.
"""

from __future__ import annotations

import threading
from pathlib import Path

from .chunker import chunk_file
from .config import Config
from .discovery import classify, load_gitignore, walk
from .embedder import Embedder
from .store import (
    Store,
    file_hash,
    load_manifest,
    now_iso,
    row_for,
    save_manifest,
)


class IncrementalIndexer:
    def __init__(self, cfg: Config, alias: str, root: str | Path,
                 store: Store | None = None, embedder: Embedder | None = None) -> None:
        self.cfg = cfg
        self.alias = alias
        self.root = Path(root).resolve()
        self.store = store or Store(cfg)
        self.embedder = embedder or Embedder(cfg)
        self.manifest = load_manifest(cfg, alias)
        self.manifest.root = str(self.root)
        self._spec = load_gitignore(self.root)
        self._lock = threading.RLock()

    # --- persistence + embed helpers ---

    def _persist(self) -> None:
        self.manifest.indexed_at = now_iso()
        save_manifest(self.cfg, self.manifest)

    def _embed(self, chunks_with_hash: list[tuple], show_progress: bool) -> list[dict]:
        if not chunks_with_hash:
            return []
        vectors = self.embedder.encode(
            [c.embed_text for c, _ in chunks_with_hash], show_progress=show_progress
        )
        at = now_iso()
        return [row_for(c, fh, vectors[i], at) for i, (c, fh) in enumerate(chunks_with_hash)]

    # --- full reconcile (build / startup) ---

    def reconcile(self, show_progress: bool = False) -> dict:
        with self._lock:
            seen: dict[str, str] = {}
            changed: list[tuple[str, str, str, bytes]] = []
            files_total = 0
            for sf in walk(self.root):
                files_total += 1
                data = sf.abspath.read_bytes()
                fh = file_hash(data)
                seen[sf.path] = fh
                if self.manifest.files.get(sf.path) != fh:
                    changed.append((sf.path, sf.language, fh, data))
            removed = [p for p in self.manifest.files if p not in seen]

            if not changed and not removed:
                self.manifest.files = seen
                self._persist()
                return {"files": files_total, "changed": 0, "removed": 0, "chunks": 0}

            chunks = []
            for path, language, fh, data in changed:
                for c in chunk_file(self.alias, path, language, data):
                    chunks.append((c, fh))
            rows = self._embed(chunks, show_progress)

            self.store.delete_paths(self.alias, [p for p, _, _, _ in changed] + removed)
            self.store.upsert(rows)
            if rows:
                self.store.ensure_fts()
            self.store.optimize()

            self.manifest.files = seen
            self._persist()
            return {"files": files_total, "changed": len(changed),
                    "removed": len(removed), "chunks": len(chunks)}

    # --- single-file (watcher) ---

    def reindex_path(self, relpath: str) -> bool:
        """(Re)index one file. If it is gone or no longer indexable, remove it. Returns True on
        any index change."""
        with self._lock:
            abspath = self.root / relpath
            sf = classify(self.root, abspath, self._spec) if abspath.exists() else None
            if sf is None:
                return self._remove_locked(relpath)
            data = abspath.read_bytes()
            fh = file_hash(data)
            if self.manifest.files.get(relpath) == fh:
                return False  # unchanged
            chunks = [(c, fh) for c in chunk_file(self.alias, relpath, sf.language, data)]
            rows = self._embed(chunks, False)
            self.store.delete_paths(self.alias, [relpath])
            self.store.upsert(rows)  # searchable immediately; FTS folded in on next reconcile
            self.manifest.files[relpath] = fh
            self._persist()
            return True

    def remove_path(self, relpath: str) -> bool:
        with self._lock:
            return self._remove_locked(relpath)

    def _remove_locked(self, relpath: str) -> bool:
        if relpath not in self.manifest.files:
            return False
        self.store.delete_paths(self.alias, [relpath])
        del self.manifest.files[relpath]
        self._persist()
        return True
