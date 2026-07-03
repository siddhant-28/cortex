"""FastMCP server exposing search_code and index_status over stdio.

Exactly two tools (tool schemas cost Claude context every session, so keep the surface minimal and
the descriptions short). A single Retriever is shared across calls so the embedding model loads
once; ``serve()`` warms it in a background thread so the first query isn't a cold-load stall.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from .config import load_config
from .retriever import Retriever, format_results
from .store import Store, list_manifests

_cfg = load_config()
_retriever = Retriever(_cfg)

mcp = FastMCP("cortex")


@mcp.tool()
def search_code(
    query: str, k: int = 10, repo: str | None = None, path_prefix: str | None = None
) -> str:
    """Find where code lives by meaning. Returns file path:line-range pointers + snippets.

    Call this BEFORE Grep/Glob when locating where something is implemented. Use natural language
    (e.g. "where are timezone-aware timestamps parsed"). Optionally filter by repo or path_prefix.
    """
    results = _retriever.search(query, k=k, repo=repo, path_prefix=path_prefix)
    return format_results(results)


@mcp.tool()
def index_status() -> str:
    """List indexed repos with chunk counts and last index time."""
    manifests = list_manifests(_cfg)
    if not manifests:
        return "no repos indexed"
    store = Store(_cfg)
    return "\n".join(
        f"{m.repo}: {store.count(m.repo)} chunks, {len(m.files)} files, indexed {m.indexed_at}"
        for m in manifests
    )


def serve() -> None:
    import threading

    # Warm the model without blocking the MCP initialize handshake.
    threading.Thread(target=lambda: _retriever.embedder.model, daemon=True).start()
    mcp.run(transport="stdio")
