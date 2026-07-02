# Manually excluded queries

Per PLAN §Phase-0 acceptance ("if a human could never localize it, drop it"), these queries were
dropped from the eval datasets after the manual spot-check. `mine.py` still produces them (the
mining step is deterministic); the curated dataset is the mined output **minus** the ids below.
Removed directly from the `.jsonl` so the eval reads only clean queries.

## vite

- **vite-22750** — "Dev server corrupts a method named `import`" — a real `importAnalysis` code
  bug, but the merged fix was an incidental dependency bump, so gold = `packages/vite/package.json`
  only. A human would localize to `importAnalysis.ts`, never `package.json`. Un-localizable.
- **vite-22826** — "vite:import-analysis fails on large files" — same pattern: import-analysis
  crash fixed by a dep bump; gold = `packages/vite/package.json` only. Un-localizable.
- **vite-22772** — "type errors in WebAssembly ESM docs" — documentation/tsconfig-template issue;
  gold is a docs page + 8 `create-vite` template `tsconfig.json` files, no source target.

## pandas

_(none)_
