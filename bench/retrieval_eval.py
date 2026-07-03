"""Retrieval-only eval: recall@5, recall@10, MRR against the mined dataset (no agent).

For each dataset query, run cortex retrieval and score file-level hits against gold_files, per
channel (dense / bm25 / fused). A hit = any gold file appears among the files of the top-k chunks.
MRR uses the rank of the first top-k chunk whose file is a gold file.

    uv run python bench/retrieval_eval.py                 # all datasets, title+body
    uv run python bench/retrieval_eval.py --repo pandas --query title
"""

from __future__ import annotations

import argparse
import csv
import json
import time
from pathlib import Path
from statistics import median

from cortex.config import load_config
from cortex.retriever import Retriever

DATASET_DIR = Path(__file__).parent / "dataset"
RESULTS_DIR = Path(__file__).parent / "results"
CHANNELS = ("dense", "bm25", "fused")


def build_query(q: dict, mode: str) -> str:
    if mode == "title":
        return q["issue_title"][:1000]
    return f"{q['issue_title']}\n{q['issue_body'] or ''}"[:1000]


def score(results, gold: set[str]) -> tuple[int, int, float]:
    files = [r.path for r in results]
    r5 = int(any(f in gold for f in files[:5]))
    r10 = int(any(f in gold for f in files[:10]))
    mrr = 0.0
    for i, f in enumerate(files[:10], start=1):
        if f in gold:
            mrr = 1.0 / i
            break
    return r5, r10, mrr


def eval_repo(retr: Retriever, alias: str, queries: list[dict], mode: str):
    # warmup (model load + first inference) so it doesn't skew latency
    retr.search_all(build_query(queries[0], mode), k=10, repo=alias)
    agg = {ch: {"r5": 0, "r10": 0, "mrr": 0.0} for ch in CHANNELS}
    latencies = []
    for q in queries:
        query = build_query(q, mode)
        gold = set(q["gold_files"])
        t = time.perf_counter()
        allres = retr.search_all(query, k=10, repo=alias)
        latencies.append((time.perf_counter() - t) * 1000)
        for ch in CHANNELS:
            r5, r10, mrr = score(allres[ch], gold)
            agg[ch]["r5"] += r5
            agg[ch]["r10"] += r10
            agg[ch]["mrr"] += mrr
    n = len(queries)
    rows = []
    for ch in CHANNELS:
        rows.append({
            "repo": alias, "channel": ch, "n": n,
            "recall@5": agg[ch]["r5"] / n,
            "recall@10": agg[ch]["r10"] / n,
            "mrr": agg[ch]["mrr"] / n,
        })
    p50 = median(latencies)
    p95 = sorted(latencies)[int(0.95 * (len(latencies) - 1))]
    return rows, p50, p95


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", help="only this alias (default: all datasets)")
    ap.add_argument("--query", choices=["title_body", "title"], default="title_body")
    args = ap.parse_args()

    datasets = sorted(DATASET_DIR.glob("*.jsonl"))
    if args.repo:
        datasets = [p for p in datasets if p.stem == args.repo]
    retr = Retriever(load_config())

    all_rows = []
    print(f"\nquery mode: {args.query}\n")
    print(f"{'repo':10s} {'channel':7s} {'R@5':>6} {'R@10':>6} {'MRR':>6} {'n':>4}")
    print("-" * 46)
    for ds in datasets:
        queries = [json.loads(line) for line in ds.open()]
        rows, p50, p95 = eval_repo(retr, ds.stem, queries, args.query)
        for row in rows:
            marker = " *" if row["channel"] == "fused" else ""
            print(f"{row['repo']:10s} {row['channel']:7s} {row['recall@5']:6.2f} "
                  f"{row['recall@10']:6.2f} {row['mrr']:6.2f} {row['n']:>4}{marker}")
        print(f"{'':10s} latency p50={p50:.0f}ms p95={p95:.0f}ms")
        print("-" * 46)
        all_rows.extend(rows)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / f"retrieval_{args.query}.csv"
    with out.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["repo", "channel", "n", "recall@5", "recall@10", "mrr"])
        w.writeheader()
        w.writerows(all_rows)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
