# cortex

A **local-only** hybrid semantic code index and benchmark harness for Claude Code, exposed as an
MCP server. Zero network egress, sub-second incremental freshness, multi-repo.

> Status: **Phase 0 (scaffolding + benchmark dataset).** See [PLAN.md](PLAN.md) for the full
> build plan and [DECISIONS.md](DECISIONS.md) for the running decision log. The README's full
> prior-art section, quickstart, and headline benchmark numbers are written in Phase 8.

## What it is

Claude Code discovers code with agentic search (Grep, Glob, Read) and no index. On large
multi-repo codebases this is slow and burns context. `cortex` provides a hybrid (dense + BM25 +
RRF) code search tool that returns **pointers, not blobs** — `path:start-end` plus a short
snippet under a strict token budget — so Claude reads full files itself. The headline deliverable
is an independent benchmark comparing stock Claude Code against Claude Code + cortex on real
fault-localization tasks mined from git history.

## Quickstart (once past Phase 0)

```bash
uv run cortex --help
```

## Prior art

Named honestly in Phase 8: claude-context, CocoIndex, Serena, and Cursor's architecture. What
cortex does differently: local-only zero egress, multi-repo, sub-second freshness, benchmark-first.

## License

MIT (added in Phase 8).
