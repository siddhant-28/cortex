"""Unit tests for store hashing + manifest (no model / no LanceDB needed)."""

from cortex.config import Config
from cortex.store import Manifest, chunk_id, file_hash, load_manifest, save_manifest


def test_chunk_id_deterministic_and_content_sensitive():
    a = chunk_id("repo", "a.py", 10, "def f(): pass")
    b = chunk_id("repo", "a.py", 10, "def f(): pass")
    c = chunk_id("repo", "a.py", 10, "def f(): return 1")  # content differs
    d = chunk_id("repo", "a.py", 11, "def f(): pass")  # line differs
    assert a == b
    assert a != c
    assert a != d
    assert len(a) == 64  # sha256 hex


def test_file_hash_changes_with_bytes():
    assert file_hash(b"x") == file_hash(b"x")
    assert file_hash(b"x") != file_hash(b"y")


def test_manifest_roundtrip(tmp_path):
    cfg = Config(home=tmp_path)
    m = Manifest(repo="demo", indexed_at="2026-07-02T00:00:00+00:00",
                 files={"a.py": "h1", "b/c.ts": "h2"})
    save_manifest(cfg, m)
    got = load_manifest(cfg, "demo")
    assert got == m


def test_manifest_missing_is_empty(tmp_path):
    cfg = Config(home=tmp_path)
    got = load_manifest(cfg, "nope")
    assert got.files == {} and got.indexed_at == ""
