# Decision log

Every deviation from `PLAN.md` gets a one-line rationale here. Newest first.

## Machine

All performance numbers in this log are measured on:

- **Machine:** Apple M1 Pro, 16 GB RAM, macOS (Darwin 23.3.0), aarch64.
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

- **2026-07-02 — Repo pins live in `bench/repos.toml`.** Single source of truth for
  which repos are mined and the snapshot commit the index is built at. Both `mine.py` (via `--pin`)
  and `checkout.py` consume it. `base_sha` in the dataset JSONL is the per-PR base (provenance);
  the repo-level `pin` is the eval snapshot. Rationale: one place to record chosen repos + pins.

- **2026-07-02 — Lockfiles/generated manifests excluded from `gold_files`.** After the first mine,
  the spot-check found vite queries whose gold was only `pnpm-lock.yaml` / `pnpm-workspace.yaml`
  (dependency-bump PRs). Lockfiles are generated, huge, and never a retrievable target. `mine.py`
  now drops a `NON_SOURCE_GOLD` set from gold; a query with no gold left is skipped. Re-mined both.
- **2026-07-02 — 3 vite queries manually excluded** (see `bench/dataset/EXCLUDED.md`): vite-22750,
  vite-22826 (import-analysis code bugs fixed by incidental dep bumps → gold = package.json only,
  un-localizable) and vite-22772 (docs/tsconfig-template issue, no source target). Kept vite-21921
  and vite-22684 (dependency-constraint issues where package.json genuinely *is* the fix target).

### Phase 0 — COMPLETE (2026-07-02)

- [x] Task 1 — scaffolding. `uv run cortex --help` passes; ruff clean; 6 tests pass.
- [x] Task 2 — repos chosen by measured linkage yield (see below); pins recorded in `bench/repos.toml`.
- [x] Task 3 — mined `bench/dataset/{pandas,vite}.jsonl`.
- [x] Task 4 — `bench/checkout.py` parses populated config for both repos (full clone deferred to Phase 1).
- [x] Acceptance — 10-query spot-check per repo done; noisy queries dropped.

**Linkage yield measured over ~400 recent closed PRs (fixes/closes/resolves #N), before filters:**

| Repo | closing-ref PRs | decision |
|---|---|---|
| pandas-dev/pandas | 137 (58%) | **chosen — Python primary** |
| scikit-learn | 88 (38%) | backup |
| sveltejs/svelte | 90 (30%) | backup |
| vitejs/vite | 79 (31%) | **chosen — TS** |
| pallets/flask | 16 (40%) | too small, control only |

**Mining results (pin = latest commit before 2025-01-01; only PRs merged after pin):**

- pandas: pin `8fbe6ac`, scanned 244 PRs, post-filter yield 24.6% → **60 queries**.
- vite: pin `a4922537`, scanned 701 PRs, post-filter yield 8.6% → 60, minus 3 manual drops → **57 queries**.
- Both exceed the >=40 acceptance bar.

### Open items / known limitations (revisit in Phase 3+)

- **Test files count as gold** (per PLAN's gold definition). A retrieval hit on a bug's mirror test
  file counts toward recall even if the source module is missed — may modestly inflate recall.
  Quantify / consider source-only scoring in Phase 3.
- Repos not yet cloned at their pins (Phase 1 prerequisite): `uv run python bench/checkout.py`.
- ~~GITHUB_TOKEN~~ — provided and used. **Token is in the session transcript; rotate/revoke it.**
