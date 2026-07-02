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
    typer.echo(f"chunk: {_NOT_YET} (Phase 1)")
    raise typer.Exit(code=1)


@app.command()
def build(
    repo_path: str = typer.Argument(..., help="Path to the repo to index."),
    alias: str = typer.Option(..., "--alias", help="Repo alias to store under."),
) -> None:
    """[Phase 2] discovery -> chunk -> embed -> store."""
    typer.echo(f"build: {_NOT_YET} (Phase 2)")
    raise typer.Exit(code=1)


@app.command()
def status() -> None:
    """[Phase 2] List indexed repos, chunk counts, last build time."""
    typer.echo(f"status: {_NOT_YET} (Phase 2)")
    raise typer.Exit(code=1)


@app.command()
def search(
    query: str = typer.Argument(..., help="Natural-language query."),
    repo: str | None = typer.Option(None, "--repo", help="Restrict to a repo alias."),
    k: int = typer.Option(10, "-k", help="Number of results."),
    show: str = typer.Option("fused", "--show", help="Channel to inspect: dense|bm25|fused."),
) -> None:
    """[Phase 3] Hybrid retrieval (dense + BM25 + RRF)."""
    typer.echo(f"search: {_NOT_YET} (Phase 3)")
    raise typer.Exit(code=1)


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
