"""LanceDB schema, upsert/delete, manifest.

One shared ``chunks`` table across repos (multi-repo ready; filter by ``repo``). Rows are upserted
by ``chunk_id`` and deleted by ``(repo, path)`` when a file changes or is removed.

FTS note: LanceDB native FTS indexes a single field, so we store a combined ``fts_text``
(``path + symbol + content``) and index that — this gives BM25 exact-identifier *and* path matching,
which is the intent of "FTS on content + symbol + path" in the data model.

The manifest (``~/.cortex/index/manifests/{repo}.json``) maps ``path -> file_hash`` for incremental
diffing and delete detection, and records the last build time.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import lancedb
import pyarrow as pa

from .chunker import Chunk
from .config import Config

TABLE = "chunks"


def file_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def chunk_id(repo: str, path: str, start_line: int, content: str) -> str:
    content_hash = hashlib.sha256(content.encode("utf-8", "replace")).hexdigest()
    key = f"{repo}\0{path}\0{start_line}\0{content_hash}"
    return hashlib.sha256(key.encode()).hexdigest()


def _sql_quote(s: str) -> str:
    return s.replace("'", "''")


def row_for(chunk: Chunk, fh: str, vector, indexed_at: str) -> dict:
    return {
        "chunk_id": chunk_id(chunk.repo, chunk.path, chunk.start_line, chunk.content),
        "repo": chunk.repo,
        "path": chunk.path,
        "language": chunk.language,
        "symbol": chunk.symbol,
        "kind": chunk.kind,
        "start_line": chunk.start_line,
        "end_line": chunk.end_line,
        "content": chunk.content,
        "fts_text": f"{chunk.path} {chunk.symbol} {chunk.content}",
        "file_hash": fh,
        "indexed_at": indexed_at,
        "vector": list(vector),
    }


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


class Store:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        cfg.db_dir.mkdir(parents=True, exist_ok=True)
        self.db = lancedb.connect(str(cfg.db_dir))

    def _schema(self) -> pa.Schema:
        return pa.schema([
            ("chunk_id", pa.string()),
            ("repo", pa.string()),
            ("path", pa.string()),
            ("language", pa.string()),
            ("symbol", pa.string()),
            ("kind", pa.string()),
            ("start_line", pa.int32()),
            ("end_line", pa.int32()),
            ("content", pa.string()),
            ("fts_text", pa.string()),
            ("file_hash", pa.string()),
            ("indexed_at", pa.string()),
            ("vector", pa.list_(pa.float32(), self.cfg.embed_dim)),
        ])

    def table(self):
        # table_names() returns plain name strings; list_tables() (the non-deprecated name) returns
        # a different shape in this version and breaks the membership check, so keep table_names().
        if TABLE not in self.db.table_names():
            return self.db.create_table(TABLE, schema=self._schema())
        return self.db.open_table(TABLE)

    def delete_paths(self, repo: str, paths: list[str]) -> None:
        # Batch into a single predicate per group of paths. One delete() per path would create one
        # LanceDB table version each (disk + metadata bloat) and be far slower.
        if not paths:
            return
        t = self.table()
        rq = _sql_quote(repo)
        batch = 500
        for i in range(0, len(paths), batch):
            in_list = ", ".join(f"'{_sql_quote(p)}'" for p in paths[i : i + batch])
            t.delete(f"repo = '{rq}' AND path IN ({in_list})")

    def upsert(self, rows: list[dict]) -> None:
        if not rows:
            return
        t = self.table()
        (
            t.merge_insert("chunk_id")
            .when_matched_update_all()
            .when_not_matched_insert_all()
            .execute(rows)
        )

    def ensure_fts(self) -> None:
        t = self.table()
        t.create_fts_index("fts_text", replace=True)

    def optimize(self, buffer_seconds: int = 60) -> None:
        # Compact fragments and prune old versions so the index stays small under churn. Keep a
        # safety buffer (default 60s): NEVER cleanup_older_than=0 — that can delete data files the
        # current version still references and corrupt the table (learned the hard way, DECISIONS).
        # A 60s buffer is far longer than any read, so no active query holds a pruned version.
        from datetime import timedelta

        self.table().optimize(cleanup_older_than=timedelta(seconds=buffer_seconds))

    def count(self, repo: str | None = None) -> int:
        t = self.table()
        if repo is None:
            return t.count_rows()
        return t.count_rows(filter=f"repo = '{_sql_quote(repo)}'")


# --- manifest -------------------------------------------------------------------------------

@dataclass
class Manifest:
    repo: str
    root: str  # absolute repo path, so `serve` can auto-watch indexed repos
    indexed_at: str
    files: dict[str, str]  # path -> file_hash


def _manifest_path(cfg: Config, repo: str) -> Path:
    return cfg.manifest_dir / f"{repo}.json"


def load_manifest(cfg: Config, repo: str) -> Manifest:
    p = _manifest_path(cfg, repo)
    if not p.exists():
        return Manifest(repo=repo, root="", indexed_at="", files={})
    data = json.loads(p.read_text())
    return Manifest(
        repo=repo,
        root=data.get("root", ""),
        indexed_at=data.get("indexed_at", ""),
        files=data.get("files", {}),
    )


def save_manifest(cfg: Config, manifest: Manifest) -> None:
    cfg.manifest_dir.mkdir(parents=True, exist_ok=True)
    p = _manifest_path(cfg, manifest.repo)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({
        "repo": manifest.repo,
        "root": manifest.root,
        "indexed_at": manifest.indexed_at,
        "files": manifest.files,
    }, indent=0))
    os.replace(tmp, p)  # atomic


def list_manifests(cfg: Config) -> list[Manifest]:
    if not cfg.manifest_dir.exists():
        return []
    out = []
    for p in sorted(cfg.manifest_dir.glob("*.json")):
        out.append(load_manifest(cfg, p.stem))
    return out
