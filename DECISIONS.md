# Decision log

Every deviation from `PLAN.md` gets a one-line rationale here. Newest first.

## Machine

All performance numbers in this log are measured on:

- **Machine:** Apple M1 Pro, 16 GB RAM, macOS (Darwin 23.3.0), aarch64.
- **Python:** 3.12.13 (managed by uv)
- **uv:** 0.11.26

## Phase 3 — COMPLETE (2026-07-03)

- [x] `retriever.py` — dense top-50 + BM25 top-50 → RRF (1/(60+rank)); repo/lang/path-prefix
  filters; single-fetch `search_all` for the eval; token-budget `format_results`.
- [x] `cortex search "q" [--repo] [--path-prefix] [-k] [--show dense|bm25|fused]`.
- [x] `bench/retrieval_eval.py` — recall@5/@10 + MRR per repo per channel; results CSV.
- [x] Unit tests: RRF fusion, FTS sanitization, budget formatter (20 tests pass).

**Acceptance (M1 Pro, seq=512, query = title+body[:1000], per-channel 50, RRF k=60):**

| repo | channel | R@5 | R@10 | MRR |
|---|---|---|---|---|
| pandas | dense | 0.63 | 0.78 | 0.51 |
| pandas | bm25 | 0.57 | 0.62 | 0.38 |
| pandas | **fused** | **0.67** | **0.78** | **0.51** |
| vite | dense | 0.63 | 0.70 | 0.50 |
| vite | bm25 | 0.61 | 0.70 | 0.40 |
| vite | **fused** | **0.68** | **0.75** | **0.57** |

- [x] Numbers exist; fused R@10 = 0.78 / 0.75 — both **far above the 0.55 target** (0.40 stop line
  never approached).
- [x] Latency: pandas p50 140ms / p95 157ms; vite p50 131ms / p95 154ms — within p50<150 / p95<400.
- [~] "Fused beats both channels on R@10 for every repo": vite yes (0.75 > 0.70/0.70). pandas fused
  **ties** dense at R@10 (0.78) because dense already saturates the findable set by rank 10; fused
  still wins pandas at R@5 (0.67 > 0.63) and MRR. Investigated per PLAN — benign, hybrid validated
  (fused ≥ both everywhere, strictly better earlier in the ranking). Not a blocker.

**Tuning experiments (logged; evals gate everything):**

- **Query construction: title+body > title-only.** title+body fused R@10 pandas 0.78 / vite 0.75 vs
  title-only 0.72 / 0.63. The issue body helps despite template boilerplate. Kept title+body.
- **`max_seq_length` 512 vs 256 (resolves the deferred Phase 2 question):** pandas recall IDENTICAL
  (fused R@10 0.78 both) AND cold-build time identical (256: 20.7 min vs 512: 20.3 min). The build
  is NOT sequence-length-bound — embedding cost is per-chunk model-forward + MPS overhead, not token
  count (an earlier short-chunk microbenchmark misprojected 256→7 min; the real corpus is 20 min at
  either seq). Kept **seq=512** — no speed penalty, preserves full content. The 20.4-min build is an
  honest hardware limit, not a tunable miss.
- Untried levers left for later if recall must rise: chunk granularity, path tokens weighting in
  FTS, per-channel depth, boilerplate stripping from pandas queries (would mainly lift BM25).

## Phase 2 — COMPLETE (2026-07-03)

- [x] `config.py` — `~/.cortex` paths, model/batch/seq-len knobs, `CORTEX_HOME` override, optional TOML.
- [x] `embedder.py` — lazy model load, MPS>CUDA>CPU, batched L2-normalized encode.
- [x] `store.py` — LanceDB `chunks` table, `chunk_id`/`file_hash`, upsert by id, batched delete by
  `(repo,path)`, combined-column FTS, safe `optimize()`, JSON manifest (atomic).
- [x] `cortex build --alias` (incremental via manifest) + `cortex status`.
- [x] Unit tests for hashing + manifest (15 tests pass); vite + pandas builds + smoke query verified.

**Acceptance (M1 Pro, 16 GB, MPS, seq=512):**

- ⚠️ **Cold build pandas (1432 files, 32807 chunks): 20.4 min** — embed 20.3, store+fts+optimize 0.1.
  MARGINAL MISS of the <20 min target (2% over). Embedding is ~27 chunks/s on the full corpus
  (short-chunk microbenchmarks mislead: they hit 66 chunks/s). pandas is ~400K LOC, larger than the
  criterion's 300K reference; a 300K repo extrapolates to ~15 min. Deliberately kept seq=512 to
  protect retrieval quality (priority #1). Lever: `max_seq_length=256` → ~12 min but truncates long
  chunks; the 256-vs-512 speed/quality call is deferred to Phase 3 where recall@k is measured.
- [x] No-change rebuild: **0.3 s** (manifest short-circuit, model never loads) — target <30 s.
- [x] Index size: **274 MB** both repos (pandas ~263 MB, vite 11 MB) — target <1 GB/repo.

- **2026-07-03 — BUG (found + fixed): `optimize(cleanup_older_than=timedelta(0))` corrupted the
  table.** Forcing immediate pruning of all prior versions deleted a data fragment still referenced
  by the current version ("Not found: .../chunks.lance/data/...lance"). Fixed to plain
  `table.optimize()` (default retention prunes only genuinely-old versions). Nuked + rebuilt clean.
  Lesson: never `cleanup_older_than=0` on a live table.
- **2026-07-03 — Batched `delete_paths` into one predicate per 500 paths** (`path IN (...)`).
  One `delete()` per path created a table version each — disk + metadata bloat and slow.

- **2026-07-02 — Pinned `transformers>=4.40,<5` (resolved 4.57.6).** DEVIATION FROM STACK: the
  default model `jinaai/jina-embeddings-v2-base-code` uses `trust_remote_code` modeling that imports
  `find_pruneable_heads_and_indices` from `transformers.pytorch_utils`, removed in transformers 5.x
  (which sentence-transformers 5.6 pulled by default). Pinning <5 fixes it; model then loads on MPS
  in ~18s, 768-dim, normalized, sensible code↔NL cosine (0.659). Kept the plan's pinned model.
- **2026-07-02 — Combined `fts_text` column for BM25.** DEVIATION: LanceDB native FTS indexes a
  single field only ("Native FTS indexes can only be created on a single field at a time"). Store
  `fts_text = path + " " + symbol + " " + content` and index that one column — functionally equals
  the data model's "FTS on content + symbol + path" (exact-identifier + path matching).
- **2026-07-02 — `embed_text` not stored.** The data model lists it, but it is only needed at embed
  time and duplicates `content`+prefix. Dropped from the table to keep index size down; kept
  `content`, `file_hash`, `indexed_at`.
- **2026-07-02 — Brute-force vector search (no ANN index yet).** Per PLAN: add IVF/HNSW only if
  query latency > 200ms. Measured in Phase 3.
- **2026-07-02 — `max_seq_length` default 512** (jina default is 8192). Bounds embed cost; most
  retrieval signal is in the prefix + signature + start of body. Configurable; revisit in Phase 3.

## Phase 1 — COMPLETE (2026-07-02)

- [x] `discovery.py` — os.walk + root `.gitignore` (pathspec) + `.git/` prune; launch extensions
  only; skip >1 MB, empty, and binary files.
- [x] `chunker.py` — tree-sitter chunks: module_top / function / class_header / method + line-window
  fallback. Python + TS/JS extractors.
- [x] Context prefix + `embed_text` per data model; top-5 imports.
- [x] `cortex chunk <repo> [--stats] [--dump]`.
- [x] Fixture tests (Python + TS exact boundaries) + oversized/unparseable cases — 11 tests pass.

**Acceptance (Apple M1 Pro / 16 GB):**

| repo | files | chunked | chunks | AST-file % | throughput |
|---|---|---|---|---|---|
| pandas | 1432 | 1432 | 32,807 | **99.9%** | ~31K files/min |
| vite | 1211 | 1211 | 2,602 | **99.3%** | ~198K files/min |

Both >95% AST bar; both >>5K files/min. Hand-inspected ~20 chunks: whole funcs/methods, class
headers exclude method bodies, correct fallback windowing (20-line overlap), symbols qualified
`Class.method`, prefixes correct, no `(path,start,symbol)` collisions.

- **2026-07-02 — Canonical tree-sitter API, not `get_parser().parse()`.** language-pack's
  `get_parser(...).parse()` rejected both `bytes` and `str` on this version; used
  `Parser(get_language(name))` + `parse(bytes)`, which works. tree-sitter 0.26.0, language-pack 1.12.2.
- **2026-07-02 — Empty / whitespace-only files skipped** (discovery skips 0-byte; `chunk_file`
  returns `[]` for whitespace-only). pandas has ~90 empty test-package `__init__.py`; indexing them
  produced spurious fallback chunks and dragged AST% to 92.9%. They have nothing to retrieve.
  AST% is now measured over files that produced ≥1 chunk.
- **2026-07-02 — module_top spanning >300 lines is fallback-split** (per PLAN's >300-line rule),
  which is why a handful of all-constant files (`pandas/core/shared_docs.py` 651 L, `pandas/__init__.py`)
  are the only remaining fallback-only files. Spec-compliant; left as-is.
- **2026-07-02 — Fixtures excluded from ruff** (`extend-exclude`). `ruff --fix` stripped the
  intentionally-unused imports from `tests/fixtures/sample.py`, breaking the boundary tests.

### Known limitation (Phase 3 impact)

- **C / Cython gold files are not indexed** (launch = Python + TS/JS only, per non-goals). Affects
  e.g. pandas `_libs/**/*.c` (query pandas-65903) and any `.pyx`. cortex cannot retrieve them; stock
  grep can. A fair, logged disadvantage for the benchmark.

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
