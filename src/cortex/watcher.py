"""Filesystem events (watchdog), per-path debounce, incremental reindex.

A watchdog observer per repo. Each changed path is debounced (a burst of saves collapses to one
reindex ~DEBOUNCE seconds after the last event), then handed to the IncrementalIndexer, which
decides create/update/delete by whether the file still exists and is indexable.
"""

from __future__ import annotations

import threading
from pathlib import Path

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from .indexer import IncrementalIndexer

DEBOUNCE = 0.75  # seconds
COMPACT_EVERY = 50  # compact the index after this many single-file reindexes (bounds version bloat)


class _Handler(FileSystemEventHandler):
    def __init__(self, watcher: RepoWatcher) -> None:
        self.watcher = watcher

    def on_any_event(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        # A move affects both the old and new path.
        self.watcher.schedule(event.src_path)
        dest = getattr(event, "dest_path", None)
        if dest:
            self.watcher.schedule(dest)


class RepoWatcher:
    def __init__(self, indexer: IncrementalIndexer, debounce: float = DEBOUNCE) -> None:
        self.indexer = indexer
        self.debounce = debounce
        self._timers: dict[str, threading.Timer] = {}
        self._lock = threading.Lock()
        self._observer = Observer()
        self._reindex_count = 0
        self._compacting = False

    def schedule(self, abspath: str) -> None:
        try:
            rel = Path(abspath).resolve().relative_to(self.indexer.root).as_posix()
        except ValueError:
            return  # outside the repo root
        with self._lock:
            existing = self._timers.pop(rel, None)
            if existing:
                existing.cancel()
            timer = threading.Timer(self.debounce, self._fire, args=(rel,))
            self._timers[rel] = timer
            timer.start()

    def _fire(self, rel: str) -> None:
        with self._lock:
            self._timers.pop(rel, None)
        try:
            if self.indexer.reindex_path(rel):
                self._maybe_compact()
        except Exception as e:  # never let a watcher thread die on one bad file
            print(f"[cortex watch] reindex failed for {rel}: {e}")

    def _maybe_compact(self) -> None:
        # Single-file reindex skips FTS rebuild/compaction for speed; compact periodically off-thread
        # so version bloat stays bounded without adding latency to any individual save.
        with self._lock:
            self._reindex_count += 1
            if self._reindex_count % COMPACT_EVERY or self._compacting:
                return
            self._compacting = True
        threading.Thread(target=self._compact, daemon=True).start()

    def _compact(self) -> None:
        try:
            self.indexer.store.optimize()
        except Exception as e:
            print(f"[cortex watch] compaction failed: {e}")
        finally:
            self._compacting = False

    def start(self) -> None:
        self._observer.schedule(_Handler(self), str(self.indexer.root), recursive=True)
        self._observer.start()

    def stop(self) -> None:
        self._observer.stop()
        self._observer.join()
        with self._lock:
            for t in self._timers.values():
                t.cancel()
            self._timers.clear()
