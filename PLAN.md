# Local Code Index for Claude Code: Build Plan

Working name: `cortex` (rename freely). A local-only semantic code index and benchmark harness for Claude Code, exposed as an MCP server.

This document is the source of truth for the project. Work through it phase by phase. Do not start a phase until the previous phase's acceptance criteria pass. Record every deviation from this plan in `DECISIONS.md` with a one-line rationale.

---

## 1. Problem statement

Claude Code uses agentic search (Grep, Glob, Read) with no index. On large multi-repo codebases (100K+ LOC), code discovery consumes:

- Wall-clock time: sequential tool calls at 1-2s each, often 10-20 rounds per question.
- Context window: grep haystacks and full-file reads fill the 1M window in under 2 hours of active work, forcing compaction or lossy handoff docs.

Cursor's published A/B data shows semantic search improves agent accuracy by ~12.5% on average, and more on large repos. Anthropic's published position is that indexes go stale and grep is more precise. The debate is unresolved and the public evidence is vendor self-reported. This project builds the tool AND the independent benchmark.

## 2. Goals and non-goals

Goals, in priority order:

1. A reproducible benchmark comparing stock Claude Code vs Claude Code + this index on real fault-localization tasks mined from git history. This is the headline deliverable.
2. A local-only hybrid code search MCP server: zero network egress, sub-second incremental freshness, multi-repo.
3. Measurable improvement for the author's daily workflow: fewer tokens to reach the right file, less time waiting.

Non-goals (do not build these, even when tempted):

- No UI, no VS Code extension, no web dashboard.
- No cloud anything: no cloud embeddings, no cloud vector DB, no telemetry.
- No session memory / conversation persistence (different product).
- No custom-trained embedding model (Cursor's moat, unreachable without their trace data).
- Language support at launch: Python + TypeScript/JavaScript only. Others come after the benchmark ships.

## 3. Design principles

1. Pointers, not blobs. The MCP tool returns `path:start_line-end_line` + short snippet, capped at a strict token budget. Claude reads full files itself. We replace the discovery loop, not the Read tool.
2. Deterministic where possible. Hashing, chunk boundaries, BM25, and fusion are all deterministic. The only learned component is the embedding model. No LLM calls anywhere in the index or query path.
3. Freshness is a feature, not a footnote. The index must never lag the filesystem by more than ~1 second. This directly answers the strongest published objection to code indexes.
4. Evals gate everything. No retrieval change ships without before/after recall@k numbers on the benchmark dataset.
5. Honest prior art. README names claude-context, CocoIndex, Serena, and Cursor's architecture explicitly, and states what this project does differently (local-only, multi-repo, benchmark-first).

## 4. Tech stack (pinned)

| Concern | Choice | Rationale |
|---|---|---|
| Language | Python 3.12, `uv` for env/deps | Fastest iteration; all libs first-class |
| Parsing | `tree-sitter` + `tree-sitter-language-pack` | AST chunking, defs/refs extraction |
| Embeddings | `sentence-transformers`, default model `jinaai/jina-embeddings-v2-base-code`, configurable | Code-trained, runs local on CPU/MPS |
| Vector + FTS store | LanceDB (embedded) | One dependency gives ANN + tantivy-based full-text; no server, no Docker |
| Keyword scoring | LanceDB FTS (BM25) | Exact-identifier precision |
| Fusion | Reciprocal Rank Fusion, k=60 | No score normalization, no tuning to start |
| File watching | `watchdog` | Cross-platform FS events |
| MCP server | `mcp` Python SDK (FastMCP), stdio transport | Standard Claude Code integration |
| CLI | `typer` | Every component gets a CLI before it gets an integration |
| Bench mining | GitHub REST API via `httpx` | Issue -> fixing PR -> changed files |
| Bench runner | `claude -p` headless, `--output-format stream-json` | Token counts and tool calls per run |
| Config | TOML at `~/.cortex/config.toml`; index data at `~/.cortex/index/` | Per-machine, outside repos |

If any pinned choice fails in practice, record the replacement and reason in `DECISIONS.md`.

## 5. Repository layout

```
cortex/
  pyproject.toml
  README.md
  PLAN.md            (this file)
  DECISIONS.md       (running decision log)
  BENCHMARKS.md      (methodology + results, written in Phase 6)
  src/cortex/
    config.py        (config load/validate)
    discovery.py     (file walking, gitignore, language detection)
    chunker.py       (tree-sitter AST chunking + fallback splitter)
    embedder.py      (batch embedding, model loading)
    store.py         (LanceDB schema, upsert/delete, manifest)
    retriever.py     (dense + BM25 + RRF, filters, formatting)
    watcher.py       (FS events, debounce, incremental reindex)
    graph.py         (Phase 7: defs/refs symbol graph, PageRank)
    mcp_server.py    (FastMCP tools)
    cli.py           (typer app: chunk, build, search, watch, serve, status)
  bench/
    mine.py          (dataset extraction from GitHub)
    dataset/         (JSONL ground truth per repo)
    retrieval_eval.py (recall@k, MRR against dataset, no agent)
    agent_eval.py    (headless Claude Code A/B runner)
    results/         (raw run logs, aggregated CSVs)
  tests/
```

## 6. Data model

Chunk record (one row in LanceDB):

```
chunk_id        str   sha256(repo + path + start_line + content_hash)
repo            str   repo alias from config
path            str   relative path within repo
language        str
symbol          str   function/class/method name, or "" for fallback chunks
kind            str   function | method | class_header | module_top | fallback
start_line      int
end_line        int
content         str   raw chunk text (stored for snippet + FTS)
embed_text      str   context-prefixed text that was embedded (not returned)
vector          vec   embedding of embed_text
file_hash       str   sha256 of whole file at index time
indexed_at      ts
```

Context prefix format for `embed_text` (prepended before embedding, cheap contextual retrieval):

```
# repo: {repo} | file: {path} | {kind}: {symbol} | imports: {top_imports_csv}
{chunk content}
```

Manifest (SQLite or JSON at `~/.cortex/index/{repo}/manifest`): `path -> file_hash`, used for incremental diffing and delete detection.

---

## Phase 0: Scaffolding + benchmark dataset

The dataset comes first because it defines success for every later phase.

Build:

1. Repo scaffolding: `uv init`, pyproject, ruff + pytest, `typer` CLI skeleton, empty module files, `DECISIONS.md`.
2. Pick 2-3 target OSS repos: 100K+ LOC, active issue tracker, issues reliably linked to fixing PRs, languages within Python/TS. Candidates to evaluate: `pandas-dev/pandas`, `scikit-learn/scikit-learn` (Python), `vitejs/vite`, `sveltejs/svelte` (TS), `pallets/flask` (small control). Do NOT use `django/django`: it tracks tickets in Trac, not GitHub Issues, so issue->PR mining will not work there. Before committing to a repo, verify linkage quality by hand on ~10 recent closed issues (does the fixing PR reference the issue with fixes/closes #N?). Clone locally, pin to a fixed commit per repo.
3. `bench/mine.py`: for each repo, walk closed issues that have a merged linked PR. Emit JSONL:

```
{query_id, repo, issue_number, issue_title, issue_body,
 pr_number, merged_at, base_sha, gold_files: [paths]}
```

   Rules: `gold_files` = files the PR modified that already existed at `base_sha` (files the PR created are excluded: you cannot retrieve a file that does not exist yet). Skip issues with < 20 words of body, PRs touching > 20 files (mega-PRs are noise), and pure-docs/test-only PRs. Target 40-80 usable queries per repo.

   Mining requirements: a GitHub personal access token (classic, `public_repo` read scope) must be set via env var `GITHUB_TOKEN` before any mining run; unauthenticated requests are capped at 60/hour and will not complete. For v1 linkage, use the simple heuristic only: PR body or title contains `fixes #N` / `closes #N` / `resolves #N`. Accept the lower yield; 40 clean queries beat 80 noisy ones. Log the yield rate in DECISIONS.md.
4. Checkout script: for evaluation, each repo is checked out at the dataset's pinned commit. All retrieval evals run against that snapshot. This prevents lookahead contamination (the index must never contain the fix).

Acceptance criteria:

- `uv run cortex --help` works.
- `bench/dataset/{repo}.jsonl` exists for at least 2 repos with >= 40 queries each.
- Manual spot-check of 10 random queries per repo: gold files are plausibly findable from the issue text (if a human could never localize it, drop it).

## Phase 1: Ingestion + chunking

Build:

1. `discovery.py`: walk a repo root, respect `.gitignore` (use `pathspec`), filter to configured extensions, detect language by extension, skip files > 1 MB and binary files.
2. `chunker.py`: tree-sitter parse per file. Extract chunks at these boundaries: top-level functions, class methods (one chunk each), class headers (class def + docstring + attributes, without method bodies), module top (imports + module docstring + top-level constants). Fallback: any file/region that fails parsing or any single unit > 300 lines gets split by a line-window splitter (200 lines, 20 overlap) with `kind=fallback`.
3. Context prefixing per the data model. Top imports = first 5 import statements of the file.
4. CLI: `cortex chunk <repo_path> [--stats] [--dump path]` prints chunk counts by kind/language and can dump chunks as JSONL for inspection.

Acceptance criteria:

- Chunking the primary Python target repo and one TS repo completes without crashes; > 95% of source files produce AST chunks (rest fallback).
- Hand-inspect 20 dumped chunks: boundaries are whole functions/methods, metadata correct.
- Unit tests: known Python and TS fixture files produce exact expected chunk boundaries.
- Throughput: >= 5K files/minute on the dev machine (chunking only).

## Phase 2: Embedding + storage

Build:

1. `embedder.py`: load model once, batch encode (batch size configurable, default 64), normalize vectors. Support MPS/CUDA if present, CPU otherwise.
2. `store.py`: LanceDB table per the data model, FTS index on `content` + `symbol` + `path`, vector index (start with brute force; add IVF/HNSW only if query latency > 200ms). Upsert by `chunk_id`; delete by `path` (for changed/removed files). Write manifest.
3. CLI: `cortex build <repo_path> --alias <name>` runs discovery -> chunk -> embed -> store, with a progress bar and end-of-run stats (files, chunks, minutes, index size on disk).
4. `cortex status` lists indexed repos, chunk counts, last build time.

Acceptance criteria:

- Full cold build of the primary Python target repo (300K+ LOC) completes in under 20 minutes on the dev machine; record the actual number in DECISIONS.md.
- Rebuilding without changes is a near-no-op (manifest hash short-circuit), < 30 seconds.
- Index size on disk < 1 GB per repo.

## Phase 3: Retrieval (the quality checkpoint)

This is where the project succeeds or dies. Budget the most iteration time here.

Build:

1. `retriever.py`: given a query string: embed query -> vector top-50; BM25 top-50; RRF fuse (score = sum of 1/(60+rank)); apply optional filters (repo, language, path prefix); return top-k with `repo/path:start-end`, symbol, kind, score, and a snippet (first 12 lines of chunk).
2. Result formatter with a hard token budget: default max 2,500 tokens total output, truncate snippets before dropping results.
3. CLI: `cortex search "query" [--repo X] [-k 10] [--show dense|bm25|fused]` so each retrieval channel can be inspected separately.
4. `bench/retrieval_eval.py`: for every dataset query, run retrieval (issue title + body as the query, truncated to 1,000 chars) and score file-level recall@5, recall@10, MRR (a hit = any gold file appears among the files of top-k chunks). Output a results table per repo per channel (dense-only, bm25-only, fused).

Acceptance criteria:

- Numbers exist. Baseline target before tuning: fused recall@10 >= 0.55 on at least one repo. If below 0.40, stop and iterate on chunking/prefixing/query construction before proceeding (log experiments in DECISIONS.md).
- Fused beats both single channels on recall@10 for every repo (this validates hybrid; if it does not, investigate before continuing).
- Query latency (embed + search + fuse): p50 < 150ms, p95 < 400ms.

Tuning levers, in the order to try them: chunk granularity (method vs function-level), context prefix contents, query construction (title only vs title+body), RRF k, k per channel, adding `path` tokens into FTS.

## Phase 4: MCP server

Build:

1. `mcp_server.py` with FastMCP over stdio. Tools:
   - `search_code(query: str, k: int = 10, repo: str | None, path_prefix: str | None)` -> formatted pointer list.
   - `index_status()` -> repos, freshness timestamps, chunk counts.
   Keep the tool surface to exactly these two. Tool descriptions must be short (MCP tool schemas consume Claude's context on every session).
2. `cortex serve` CLI entry; document `claude mcp add cortex -- uv run cortex serve`.
3. A `CLAUDE.md` steering snippet shipped in the README:

```
## Code search
Before using Grep or Glob to FIND where something lives, call
mcp cortex search_code with a natural-language query. Use Grep only
for exact-string confirmation after cortex has localized the area.
```

4. Manual end-to-end test protocol: 10 real discovery questions against django in Claude Code, with and without the MCP server, eyeballing tool-call sequences.

Acceptance criteria:

- Claude Code actually calls the tool unprompted for discovery-style questions (if it does not, iterate on tool name/description and CLAUDE.md wording; log what worked).
- Round-trip from prompt to results inside Claude Code < 1s perceived.
- Output always within token budget.

## Phase 5: Freshness (incremental watcher)

Build:

1. `watcher.py`: watchdog observer per indexed repo. Debounce 750ms per path. On change: re-hash file; if hash differs: delete old chunks for path, re-chunk, re-embed, upsert, update manifest. On delete: remove chunks + manifest entry. On create: index if it passes discovery filters.
2. Wire into `cortex serve` (watcher runs in-process with the MCP server) and standalone `cortex watch`.
3. Crash safety: manifest written atomically; on startup, a fast hash sweep reconciles anything missed while not running.

Acceptance criteria:

- Save a file -> updated chunks retrievable in < 1.5s end to end.
- Startup reconciliation of the primary Python target repo after 50 offline file changes < 30s.
- Stress test: run Claude Code making multi-file edits while querying the index; no stale results for edited files after the debounce window, no crashes.

## Phase 6: Agent benchmark (the headline)

Build:

1. `bench/agent_eval.py`: for a sampled subset of dataset queries (30-50 total across repos; headless runs cost real API tokens, keep it disciplined):
   - Prompt template: "In this repository, identify the files that would need to change to fix the following issue. Reply with a list of file paths only.\n\n{issue_title}\n\n{issue_body}"
   - Arm A: stock Claude Code, headless (`claude -p`), repo at pinned commit, MCP disabled.
   - Arm B: identical, with cortex MCP registered and CLAUDE.md steering in place.
   - 2 runs per query per arm (variance). Parse `stream-json` output for: input/output tokens, number of tool calls by tool name, wall-clock, final answer.
   - Score: file-level recall and precision of the answered paths vs gold_files.
2. Aggregation: per-repo and overall tables: localization recall, tokens per task (median), tool calls per task, wall-clock per task, cortex tool-call rate in Arm B (did Claude actually use it).
3. `BENCHMARKS.md`: methodology (dataset construction, pinned commits, prompt, arms, runs), full results, honest limitations section (single machine, one model version, localization-only tasks, sample size).

Acceptance criteria:

- Full A/B completes reproducibly from one command per arm.
- BENCHMARKS.md written with real numbers, whatever they are. A null or negative result is a valid, publishable outcome and does not block release.

## Phase 7: Multi-repo + symbol graph (the differentiators)

Build only after Phase 6 ships.

1. Multi-repo: `cortex build` multiple aliases into one store; `search_code` defaults to all repos, results carry repo prefix; add a cross-repo dataset slice if a good candidate exists (e.g. an org with 2 related repos).
2. `graph.py`: tree-sitter def/ref extraction per file -> symbol graph (nodes: files and symbols; edges: references/imports). PageRank over the graph. Two uses:
   - Retrieval boost: final_score = rrf_score * (1 + alpha * normalized_pagerank), alpha tuned on the Phase 3 eval (start 0.25).
   - New MCP tool `who_references(symbol)` returning definition + top referencing sites.
3. Re-run retrieval eval with the boost; keep it only if recall@10 improves.

Acceptance criteria:

- Graph build for the primary Python target repo < 5 minutes; boost either measurably improves recall@10 or is reverted (decision logged).
- Cross-repo query returns correctly namespaced results.

## Phase 8: Release + content

1. README: what it is, honest prior-art section (claude-context, CocoIndex, Serena, Cursor's architecture), what is different (local-only zero egress, multi-repo, sub-second freshness, benchmark-first), quickstart, benchmark headline numbers.
2. Packaging: installable via `uvx cortex` / `pipx install`; MIT license.
3. Content mapping (write as you go, publish after release): (a) benchmark methodology + results, (b) grep vs embeddings with independent data, (c) the freshness architecture, (d) what tuning retrieval actually took. Each phase's DECISIONS.md entries are the raw material.

---

## Risks and mitigations

- Retrieval quality plateaus low: Phase 3 has an explicit stop-and-tune gate before any integration work.
- Claude ignores the MCP tool: measured explicitly (tool-call rate metric); mitigation is tool naming, description, and CLAUDE.md iteration, tested in Phase 4.
- Benchmark cost: sample capped at 30-50 queries, 2 runs per arm; estimate token spend before running the full sweep with a 3-query pilot.
- Embedding model weak on exact identifiers: BM25 channel exists for exactly this; per-channel eval in Phase 3 quantifies it.
- Scope creep: non-goals list is binding; anything new goes to a `LATER.md`, not into the current phase.
- Abandonment risk: Phases 0-6 form the minimum publishable unit. Phase 7 is strictly optional for release.

## Working agreement for Claude Code

- One phase at a time; propose a short task breakdown at the start of each phase before writing code.
- Every phase ends with: tests passing, acceptance criteria checked off explicitly, DECISIONS.md updated.
- Git policy: the remote is `git@github.com:siddhant-28/cortex.git`. One-time setup (run once, at project start):

```
git remote add origin git@github.com:siddhant-28/cortex.git
git branch -M main
git push -u origin main
```

  Commit locally as work progresses, but PUSH ONLY AT THE END OF A COMPLETED PHASE, and ONLY after explicitly asking Sid for permission and receiving a yes in that conversation. Never push autonomously, never push mid-phase, never force-push. If permission is not granted, leave the commits local and continue.
- Prefer boring code: no premature abstractions, no plugin systems, no async unless a measured bottleneck demands it.
- All performance numbers get recorded with the machine specs they were measured on.
