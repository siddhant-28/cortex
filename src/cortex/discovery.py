"""File walking, .gitignore handling (pathspec), language detection.

Walks a repo root, honors the root ``.gitignore`` (plus an always-on ``.git/`` prune), keeps only
files whose extension maps to a launch language (Python + TS/JS), and skips files over 1 MB or that
look binary. Yields one :class:`SourceFile` per indexable file.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pathspec

# Launch languages only (PLAN non-goals). tree-sitter grammar name per extension.
EXT_LANG: dict[str, str] = {
    ".py": "python",
    ".pyi": "python",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
}

MAX_BYTES = 1_000_000  # skip files larger than 1 MB
_BINARY_SNIFF = 8192


@dataclass(frozen=True)
class SourceFile:
    path: str  # repo-relative, posix
    abspath: Path
    language: str


def load_gitignore(root: Path) -> pathspec.PathSpec:
    lines: list[str] = []
    gi = root / ".gitignore"
    if gi.exists():
        lines = gi.read_text(errors="ignore").splitlines()
    lines.append(".git/")
    return pathspec.PathSpec.from_lines("gitwildmatch", lines)


def _is_binary(p: Path) -> bool:
    try:
        with p.open("rb") as f:
            return b"\x00" in f.read(_BINARY_SNIFF)
    except OSError:
        return True


def classify(
    root: Path, abspath: Path, spec: pathspec.PathSpec | None = None
) -> SourceFile | None:
    """Single-file version of the walk filters (for the watcher). None if not indexable."""
    root = Path(root).resolve()
    lang = EXT_LANG.get(abspath.suffix)
    if lang is None:
        return None
    try:
        relf = abspath.resolve().relative_to(root).as_posix()
    except ValueError:
        return None
    if spec is None:
        spec = load_gitignore(root)
    if spec.match_file(relf) or relf.startswith(".git/"):
        return None
    try:
        size = abspath.stat().st_size
    except OSError:
        return None
    if size == 0 or size > MAX_BYTES:
        return None
    if _is_binary(abspath):
        return None
    return SourceFile(path=relf, abspath=abspath, language=lang)


def walk(root: str | Path) -> Iterator[SourceFile]:
    """Yield indexable source files under ``root``."""
    root = Path(root).resolve()
    spec = load_gitignore(root)

    for dirpath, dirnames, filenames in os.walk(root):
        d = Path(dirpath)
        rel_dir = d.relative_to(root)
        # Prune ignored directories in-place so os.walk does not descend into them.
        kept = []
        for name in dirnames:
            reld = (rel_dir / name).as_posix() + "/"
            if name == ".git" or spec.match_file(reld):
                continue
            kept.append(name)
        dirnames[:] = kept

        for fn in filenames:
            lang = EXT_LANG.get(Path(fn).suffix)
            if lang is None:
                continue
            fp = d / fn
            relf = fp.relative_to(root).as_posix()
            if spec.match_file(relf):
                continue
            try:
                size = fp.stat().st_size
            except OSError:
                continue
            if size == 0 or size > MAX_BYTES:
                # Empty files (e.g. package __init__.py) have nothing to index; skip.
                continue
            if _is_binary(fp):
                continue
            yield SourceFile(path=relf, abspath=fp, language=lang)
