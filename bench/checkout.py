"""Checkout each benchmark target repo at its pinned commit.

All retrieval/agent evals run against the pinned snapshot so the index never contains the fix
(lookahead safety, PLAN §Phase-0 task 4). Reads `bench/repos.toml`; clones over SSH into
`bench/repos/{alias}` (gitignored) and checks out the recorded `pin` in detached HEAD.

Usage:

    uv run python bench/checkout.py            # all repos in repos.toml
    uv run python bench/checkout.py --alias flask
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tomllib
from pathlib import Path

REPOS_TOML = Path(__file__).parent / "repos.toml"
REPOS_DIR = Path(__file__).parent / "repos"


def load_repos() -> dict[str, dict]:
    if not REPOS_TOML.exists():
        sys.exit(f"{REPOS_TOML} not found.")
    with REPOS_TOML.open("rb") as fh:
        return tomllib.load(fh)


def run(cmd: list[str], cwd: Path | None = None) -> str:
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"command failed: {' '.join(cmd)}\n{r.stderr.strip()}")
    return r.stdout.strip()


def checkout_one(alias: str, spec: dict) -> None:
    url, pin = spec.get("url"), spec.get("pin")
    if not url or not pin:
        sys.exit(f"[{alias}] repos.toml needs both 'url' and a non-empty 'pin' (got url={url!r} "
                 f"pin={pin!r}). Choose the snapshot commit first.")

    dest = REPOS_DIR / alias
    if not (dest / ".git").exists():
        print(f"[{alias}] cloning {url} ...")
        REPOS_DIR.mkdir(parents=True, exist_ok=True)
        # Blobless partial clone: fetch commits + trees but defer file blobs until checkout
        # materializes the pinned tree. Much faster than a full history clone for large repos.
        run(["git", "clone", "--filter=blob:none", "--no-checkout", url, str(dest)])

    # Ensure the pinned commit is present, then detach onto it.
    run(["git", "fetch", "--quiet", "origin", pin], cwd=dest)
    run(["git", "checkout", "--quiet", "--detach", pin], cwd=dest)
    head = run(["git", "rev-parse", "HEAD"], cwd=dest)
    if not head.startswith(pin) and pin not in head:
        sys.exit(f"[{alias}] HEAD {head[:12]} != pin {pin[:12]}")
    print(f"[{alias}] at {head[:12]} ({dest})")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--alias", help="only this alias (default: all in repos.toml)")
    args = ap.parse_args()

    repos = load_repos()
    if args.alias:
        if args.alias not in repos:
            sys.exit(f"alias {args.alias!r} not in repos.toml (have: {', '.join(repos)})")
        repos = {args.alias: repos[args.alias]}
    if not repos:
        sys.exit("repos.toml has no repos yet (all entries commented out).")

    for alias, spec in repos.items():
        checkout_one(alias, spec)


if __name__ == "__main__":
    main()
