"""Mine (issue -> fixing PR -> changed files) ground truth from a GitHub repo.

Emits one JSONL row per usable query to ``bench/dataset/{alias}.jsonl``:

    {query_id, repo, issue_number, issue_title, issue_body,
     pr_number, merged_at, base_sha, gold_files: [paths]}

Design (see PLAN §Phase-0 and DECISIONS.md):

* **Linkage heuristic (v1, simple only):** a merged PR whose *title or body* contains
  ``fixes #N`` / ``closes #N`` / ``resolves #N`` (and inflections) is treated as the fixing PR for
  issue N. Lower yield, higher precision — 40 clean queries beat 80 noisy ones.
* **Lookahead safety:** the index is built at a single pinned commit ``--pin`` per repo. We only
  keep PRs **merged after** that commit's date, so the fix is never already in the index. Each
  query's ``gold_files`` are the PR's changed files that **already existed at the pin commit**
  (created files are excluded — you cannot retrieve a file that does not exist yet).
* **Filters:** issue body >= 20 words; PR touches <= 20 files; skip pure-docs / test-only PRs.

Usage:

    GITHUB_TOKEN=ghp_... uv run python bench/mine.py \
        --repo pallets/flask --alias flask --pin <sha> [--target 80]

A classic PAT with ``public_repo`` scope is required in ``GITHUB_TOKEN``; unauthenticated requests
are capped at 60/hour and will not complete.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from pathlib import Path

import httpx

API = "https://api.github.com"

# fixes/fix/fixed/close/closes/closed/resolve/resolves/resolved  #N
CLOSES_RE = re.compile(
    r"\b(?:fix(?:e[sd])?|close[sd]?|resolve[sd]?)\b[\s:]+#(\d+)",
    re.IGNORECASE,
)

DOCS_TEST_RE = re.compile(
    r"(^|/)(docs?|test|tests|__tests__|examples?|benchmarks?)(/|$)"
    r"|\.(md|rst|txt)$"
    r"|(^|/)conftest\.py$"
    r"|test_.*\.py$|.*_test\.py$|.*\.(spec|test)\.(t|j)sx?$",
    re.IGNORECASE,
)

DATASET_DIR = Path(__file__).parent / "dataset"


@dataclass
class Query:
    query_id: str
    repo: str
    issue_number: int
    issue_title: str
    issue_body: str
    pr_number: int
    merged_at: str
    base_sha: str
    gold_files: list[str]


class GitHub:
    """Thin GitHub REST client: auth, pagination, rate-limit backoff."""

    def __init__(self, token: str, repo: str) -> None:
        self.repo = repo
        self.http = httpx.Client(
            base_url=API,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=30.0,
        )

    def get(self, path: str, **params) -> httpx.Response:
        while True:
            r = self.http.get(path, params=params or None)
            if r.status_code == 403 and "rate limit" in r.text.lower():
                reset = int(r.headers.get("X-RateLimit-Reset", "0"))
                wait = max(reset - int(time.time()), 1) + 1
                print(f"  rate-limited; sleeping {wait}s", file=sys.stderr)
                time.sleep(wait)
                continue
            r.raise_for_status()
            return r

    def paginate(self, path: str, **params) -> Iterator[dict]:
        params.setdefault("per_page", 100)
        page = 1
        while True:
            r = self.get(path, page=page, **params)
            batch = r.json()
            if not batch:
                return
            yield from batch
            if len(batch) < params["per_page"]:
                return
            page += 1

    # --- typed helpers ---

    def commit_date(self, sha: str) -> str:
        c = self.get(f"/repos/{self.repo}/commits/{sha}").json()
        return c["commit"]["committer"]["date"]

    def merged_prs(self) -> Iterator[dict]:
        """Closed PRs, newest first. Caller filters to merged + date window."""
        yield from self.paginate(
            f"/repos/{self.repo}/pulls",
            state="closed",
            sort="updated",
            direction="desc",
        )

    def pr_files(self, number: int) -> list[dict]:
        return list(self.paginate(f"/repos/{self.repo}/pulls/{number}/files"))

    def issue(self, number: int) -> dict | None:
        r = self.http.get(
            f"/repos/{self.repo}/issues/{number}",
            headers=self.http.headers,
        )
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()

    def file_exists_at(self, path: str, sha: str) -> bool:
        r = self.http.get(f"/repos/{self.repo}/contents/{path}", params={"ref": sha})
        return r.status_code == 200


def closing_issue_numbers(pr: dict) -> set[int]:
    text = f"{pr.get('title', '')}\n{pr.get('body') or ''}"
    return {int(n) for n in CLOSES_RE.findall(text)}


def word_count(text: str) -> int:
    return len(text.split())


def is_docs_or_test_only(paths: list[str]) -> bool:
    return bool(paths) and all(DOCS_TEST_RE.search(p) for p in paths)


def mine(repo: str, alias: str, pin: str, target: int, max_files: int, min_words: int) -> None:
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        sys.exit("GITHUB_TOKEN is not set. Export a classic PAT with public_repo scope.")

    gh = GitHub(token, repo)
    pin_date = gh.commit_date(pin)
    print(f"repo={repo} pin={pin[:12]} pin_date={pin_date} target={target}", file=sys.stderr)

    queries: list[Query] = []
    seen_issues: set[int] = set()
    scanned = 0

    for pr in gh.merged_prs():
        if len(queries) >= target:
            break
        scanned += 1
        merged_at = pr.get("merged_at")
        if not merged_at or merged_at <= pin_date:
            # Not merged, or merged at/before the index snapshot -> lookahead risk. Skip.
            # PRs are sorted by updated desc, so this is not a hard stop.
            continue

        issue_nums = closing_issue_numbers(pr)
        if not issue_nums:
            continue

        files = gh.pr_files(pr["number"])
        if len(files) > max_files:
            continue
        changed_paths = [f["filename"] for f in files]
        if is_docs_or_test_only(changed_paths):
            continue

        # gold = files that already existed at the pin commit (exclude PR-created files).
        gold = [
            f["filename"]
            for f in files
            if f["status"] != "added" and gh.file_exists_at(f["filename"], pin)
        ]
        if not gold:
            continue

        for n in sorted(issue_nums):
            if n in seen_issues:
                continue
            iss = gh.issue(n)
            if iss is None or "pull_request" in iss:
                continue  # not a real issue (or a PR reference)
            body = iss.get("body") or ""
            if word_count(body) < min_words:
                continue
            seen_issues.add(n)
            queries.append(
                Query(
                    query_id=f"{alias}-{n}",
                    repo=repo,
                    issue_number=n,
                    issue_title=iss["title"],
                    issue_body=body,
                    pr_number=pr["number"],
                    merged_at=merged_at,
                    base_sha=pr["base"]["sha"],
                    gold_files=gold,
                )
            )
            print(f"  [{len(queries):>3}] issue #{n} <- PR #{pr['number']} ({len(gold)} gold)",
                  file=sys.stderr)
            break  # one query per PR

    DATASET_DIR.mkdir(parents=True, exist_ok=True)
    out = DATASET_DIR / f"{alias}.jsonl"
    with out.open("w") as fh:
        for q in queries:
            fh.write(json.dumps(asdict(q)) + "\n")

    yield_rate = len(queries) / scanned if scanned else 0.0
    print(
        f"\nwrote {len(queries)} queries to {out}\n"
        f"scanned {scanned} closed PRs; yield {yield_rate:.1%}",
        file=sys.stderr,
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", required=True, help="owner/name, e.g. pallets/flask")
    ap.add_argument("--alias", required=True, help="dataset alias, e.g. flask")
    ap.add_argument("--pin", required=True, help="commit SHA the index is built at (lookahead pin)")
    ap.add_argument("--target", type=int, default=80, help="max usable queries to collect")
    ap.add_argument("--max-files", type=int, default=20, help="skip PRs touching more files")
    ap.add_argument("--min-words", type=int, default=20, help="skip issues with shorter bodies")
    args = ap.parse_args()
    mine(args.repo, args.alias, args.pin, args.target, args.max_files, args.min_words)


if __name__ == "__main__":
    main()
