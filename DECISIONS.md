# Decision log

Every deviation from `PLAN.md` gets a one-line rationale here. Newest first.

## Machine

All performance numbers in this log are measured on:

- **Machine:** Apple Silicon (aarch64) macOS (Darwin 23.3.0). _(Fill in exact chip/RAM before recording Phase 2+ perf numbers.)_
- **Python:** 3.12.13 (managed by uv)
- **uv:** 0.11.26

## Phase 0

- **2026-07-02 — Dependencies added per-phase, not all at once.** PLAN §4 pins the full stack, but
  installing torch / sentence-transformers / lancedb at Phase 0 pulls ~GBs before any code uses
  them. Phase 0 declares only `typer`, `httpx`, `pathspec`. Heavy deps (tree-sitter,
  sentence-transformers, lancedb, watchdog, mcp) are added in the phase that first imports them.
  Rationale: keeps the env lean and `uv sync` fast; respects "one phase at a time". End-state stack
  is unchanged.
- **2026-07-02 — `uv` installed via Homebrew (0.11.26); Python 3.12.13 via `uv python install`.**
  Rationale: user preference (Homebrew); uv-managed Python keeps the toolchain self-contained.
- **2026-07-02 — Build backend is `hatchling` with `src/` layout.** `uv init --package` default;
  no reason to deviate.

### Open items

- **GITHUB_TOKEN not yet available.** No token found in env / `~/.git-credentials` / `gh` (gh not
  installed). User uses SSH for clones, which does not cover REST API mining. Mining (Phase 0
  tasks 2–3) is blocked until a classic PAT with `public_repo` scope is exported as `GITHUB_TOKEN`.
- Benchmark target repos not yet chosen. Candidates per PLAN §Phase-0: pandas / scikit-learn /
  flask (Python), vite / svelte (TS). Linkage quality to be hand-verified before committing.
- Yield rate of the mining heuristic to be logged here once mining runs.
