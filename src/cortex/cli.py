"""Typer CLI for cortex.

Every component gets a CLI before it gets an integration (PLAN §4). Subcommands are stubbed here
and filled in as their phases land:

    chunk   Phase 1   discovery + AST chunking
    build   Phase 2   discovery -> chunk -> embed -> store
    status  Phase 2   list indexed repos
    search  Phase 3   dense + BM25 + RRF retrieval
    serve   Phase 4   FastMCP server over stdio
    watch   Phase 5   incremental filesystem watcher
"""

from __future__ import annotations

import typer

app = typer.Typer(
    name="cortex",
    help="Local-only hybrid semantic code index for Claude Code.",
    no_args_is_help=True,
    add_completion=False,
)

_NOT_YET = "not implemented yet"


@app.command()
def chunk(
    repo_path: str = typer.Argument(..., help="Path to the repo to chunk."),
    stats: bool = typer.Option(False, "--stats", help="Print chunk counts by kind/language."),
    dump: str | None = typer.Option(None, "--dump", help="Dump chunks as JSONL to this path."),
) -> None:
    """[Phase 1] Discover + AST-chunk a repo."""
    import dataclasses
    import json
    import time
    from collections import Counter
    from pathlib import Path

    from .chunker import chunk_file
    from .discovery import walk

    root = Path(repo_path)
    if not root.is_dir():
        typer.echo(f"not a directory: {repo_path}", err=True)
        raise typer.Exit(code=1)
    repo = root.name

    by_kind: Counter[str] = Counter()
    by_lang: Counter[str] = Counter()
    files_total = 0
    files_chunked = 0
    files_with_ast = 0
    total_chunks = 0
    dump_fh = open(dump, "w") if dump else None
    t0 = time.perf_counter()

    try:
        for sf in walk(root):
            files_total += 1
            chunks = chunk_file(repo=repo, path=sf.path, language=sf.language,
                                source=sf.abspath.read_bytes())
            if not chunks:
                continue
            files_chunked += 1
            if any(c.kind != "fallback" for c in chunks):
                files_with_ast += 1
            for c in chunks:
                by_kind[c.kind] += 1
                by_lang[c.language] += 1
                total_chunks += 1
                if dump_fh:
                    dump_fh.write(json.dumps(dataclasses.asdict(c)) + "\n")
    finally:
        if dump_fh:
            dump_fh.close()

    elapsed = time.perf_counter() - t0
    ast_pct = (100 * files_with_ast / files_chunked) if files_chunked else 0.0
    fpm = (files_total / elapsed * 60) if elapsed else 0.0

    typer.echo(f"repo={repo}  files={files_total}  chunked={files_chunked}  "
               f"chunks={total_chunks}  ast_files={files_with_ast} ({ast_pct:.1f}% of chunked)  "
               f"{elapsed:.1f}s ({fpm:,.0f} files/min)")
    if dump:
        typer.echo(f"dumped chunks -> {dump}")
    if stats:
        typer.echo("by kind:  " + "  ".join(f"{k}={n}" for k, n in by_kind.most_common()))
        typer.echo("by lang:  " + "  ".join(f"{k}={n}" for k, n in by_lang.most_common()))


@app.command()
def build(
    repo_path: str = typer.Argument(..., help="Path to the repo to index."),
    alias: str = typer.Option(..., "--alias", help="Repo alias to store under."),
) -> None:
    """[Phase 2] discovery -> chunk -> embed -> store (incremental via manifest)."""
    import time
    from pathlib import Path

    from .chunker import chunk_file
    from .config import load_config
    from .discovery import walk
    from .embedder import Embedder
    from .store import (
        Manifest,
        Store,
        file_hash,
        load_manifest,
        now_iso,
        row_for,
        save_manifest,
    )

    root = Path(repo_path)
    if not root.is_dir():
        typer.echo(f"not a directory: {repo_path}", err=True)
        raise typer.Exit(code=1)

    cfg = load_config()
    store = Store(cfg)
    manifest = load_manifest(cfg, alias)
    t0 = time.perf_counter()

    # 1. Walk + hash; diff against manifest to find changed/new and removed files.
    seen: dict[str, str] = {}
    changed: list[tuple[str, str, str, bytes]] = []  # (path, language, hash, data)
    files_total = 0
    for sf in walk(root):
        files_total += 1
        data = sf.abspath.read_bytes()
        fh = file_hash(data)
        seen[sf.path] = fh
        if manifest.files.get(sf.path) != fh:
            changed.append((sf.path, sf.language, fh, data))
    removed = [p for p in manifest.files if p not in seen]

    if not changed and not removed:
        typer.echo(f"{alias}: up to date ({files_total} files, {store.count(alias)} chunks, "
                   f"{time.perf_counter() - t0:.1f}s)")
        return

    # 2. Chunk changed files.
    chunks = []
    for path, language, fh, data in changed:
        for c in chunk_file(repo=alias, path=path, language=language, source=data):
            chunks.append((c, fh))

    # 3. Embed (loads the model only now).
    typer.echo(f"{alias}: {len(changed)} changed, {len(removed)} removed, "
               f"{len(chunks)} chunks to embed ...")
    indexed_at = now_iso()
    rows = []
    t_embed = t_store = 0.0
    if chunks:
        te = time.perf_counter()
        vectors = Embedder(cfg).encode([c.embed_text for c, _ in chunks], show_progress=True)
        t_embed = time.perf_counter() - te
        rows = [row_for(c, fh, vectors[i], indexed_at) for i, (c, fh) in enumerate(chunks)]

    # 4. Replace changed/removed paths, then upsert new rows.
    ts = time.perf_counter()
    store.delete_paths(alias, [p for p, _, _, _ in changed] + removed)
    store.upsert(rows)
    if rows:
        store.ensure_fts()
    store.optimize()
    t_store = time.perf_counter() - ts
    typer.echo(f"  (embed {t_embed / 60:.1f} min, store+fts+optimize {t_store / 60:.1f} min)")

    # 5. Persist manifest + report.
    save_manifest(cfg, Manifest(repo=alias, indexed_at=indexed_at, files=seen))
    mins = (time.perf_counter() - t0) / 60
    size_mb = _dir_size_mb(cfg.db_dir)
    typer.echo(f"{alias}: {files_total} files, {store.count(alias)} chunks, "
               f"{mins:.1f} min, index {size_mb:.0f} MB on disk")


@app.command()
def status() -> None:
    """[Phase 2] List indexed repos, chunk counts, last build time."""
    from .config import load_config
    from .store import Store, list_manifests

    cfg = load_config()
    manifests = list_manifests(cfg)
    if not manifests:
        typer.echo("no repos indexed yet")
        return
    store = Store(cfg)
    typer.echo(f"{'repo':16s} {'files':>7} {'chunks':>8}  last build")
    for m in manifests:
        typer.echo(f"{m.repo:16s} {len(m.files):>7} {store.count(m.repo):>8}  {m.indexed_at}")
    typer.echo(f"index: {_dir_size_mb(cfg.db_dir):.0f} MB at {cfg.db_dir}")


def _dir_size_mb(path) -> float:
    import os

    total = 0
    for dirpath, _, filenames in os.walk(path):
        for fn in filenames:
            try:
                total += os.path.getsize(os.path.join(dirpath, fn))
            except OSError:
                pass
    return total / 1_048_576


@app.command()
def search(
    query: str = typer.Argument(..., help="Natural-language query."),
    repo: str | None = typer.Option(None, "--repo", help="Restrict to a repo alias."),
    path_prefix: str | None = typer.Option(None, "--path-prefix", help="Restrict to a path prefix."),
    k: int = typer.Option(10, "-k", help="Number of results."),
    show: str = typer.Option("fused", "--show", help="Channel to inspect: dense|bm25|fused."),
) -> None:
    """[Phase 3] Hybrid retrieval (dense + BM25 + RRF)."""
    from .config import load_config
    from .retriever import Retriever, format_results

    if show not in ("dense", "bm25", "fused"):
        typer.echo("--show must be one of: dense, bm25, fused", err=True)
        raise typer.Exit(code=2)

    results = Retriever(load_config()).search(
        query, k=k, repo=repo, path_prefix=path_prefix, channel=show
    )
    typer.echo(format_results(results))


@app.command()
def serve() -> None:
    """[Phase 4] Run the FastMCP server over stdio."""
    typer.echo(f"serve: {_NOT_YET} (Phase 4)")
    raise typer.Exit(code=1)


@app.command()
def watch(
    repo_path: str = typer.Argument(..., help="Path to the repo to watch."),
    alias: str = typer.Option(..., "--alias", help="Repo alias to update."),
) -> None:
    """[Phase 5] Incremental filesystem watcher."""
    typer.echo(f"watch: {_NOT_YET} (Phase 5)")
    raise typer.Exit(code=1)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
