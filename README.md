# cortex

A **local-only** hybrid semantic code index and benchmark harness for Claude Code, exposed as an
MCP server. Zero network egress, sub-second incremental freshness, multi-repo.

> Status: **Phase 4 (MCP server) complete.** Local index + hybrid search + Claude Code integration
> work; the agent A/B benchmark is Phase 6. See [PLAN.md](PLAN.md) for the full build plan and
> [DECISIONS.md](DECISIONS.md) for the running decision log. The full prior-art section and headline
> benchmark numbers are written in Phase 8.

## What it is

Claude Code discovers code with agentic search (Grep, Glob, Read) and no index. On large
multi-repo codebases this is slow and burns context. `cortex` provides a hybrid (dense + BM25 +
RRF) code search tool that returns **pointers, not blobs** — `path:start-end` plus a short
snippet under a strict token budget — so Claude reads full files itself. The headline deliverable
is an independent benchmark comparing stock Claude Code against Claude Code + cortex on real
fault-localization tasks mined from git history.

## Quickstart

```bash
# 1. Index a repo (discovery -> AST chunk -> embed -> LanceDB). Incremental on re-run.
uv run cortex build /path/to/repo --alias myrepo
uv run cortex status

# 2. Try a search from the CLI.
uv run cortex search "where are timezone-aware timestamps parsed" --repo myrepo

# 3. Register the MCP server with Claude Code.
claude mcp add cortex -- uv run --directory /path/to/cortex cortex serve
```

The server exposes exactly two tools: `search_code(query, k, repo?, path_prefix?)` and
`index_status()`.

### Steering snippet (add to your project's CLAUDE.md)

```
## Code search
Before using Grep or Glob to FIND where something lives, call
mcp cortex search_code with a natural-language query. Use Grep only
for exact-string confirmation after cortex has localized the area.
```

## Prior art

Named honestly in Phase 8: claude-context, CocoIndex, Serena, and Cursor's architecture. What
cortex does differently: local-only zero egress, multi-repo, sub-second freshness, benchmark-first.

## License

MIT (added in Phase 8).
