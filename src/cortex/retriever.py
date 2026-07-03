"""Dense + BM25 + RRF fusion, filters, result formatting under a token budget.

Given a query string: embed -> vector top-N; BM25 top-N; fuse with Reciprocal Rank Fusion
(score = sum of 1/(RRF_K + rank), rank 1-based). Optional filters (repo, language, path prefix).
Returns top-k pointers (repo/path:start-end, symbol, kind, score, snippet).
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass

from .config import Config
from .embedder import Embedder
from .store import Store

RRF_K = 60
PER_CHANNEL = 50
SNIPPET_LINES = 12
DEFAULT_TOKEN_BUDGET = 2500

_WORD = re.compile(r"[A-Za-z0-9_]+")


@dataclass
class Result:
    repo: str
    path: str
    start_line: int
    end_line: int
    symbol: str
    kind: str
    language: str
    score: float
    snippet: str

    @property
    def pointer(self) -> str:
        return f"{self.repo}/{self.path}:{self.start_line}-{self.end_line}"


def _fts_query(text: str, max_tokens: int = 200) -> str:
    """Reduce free text to word tokens so the FTS parser can't choke on punctuation/operators."""
    return " ".join(_WORD.findall(text)[:max_tokens])


class Retriever:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.store = Store(cfg)
        self.embedder = Embedder(cfg)

    def _filter(self, repo: str | None, path_prefix: str | None, language: str | None) -> str:
        clauses = []
        if repo:
            clauses.append(f"repo = '{repo}'")
        if language:
            clauses.append(f"language = '{language}'")
        if path_prefix:
            clauses.append(f"path LIKE '{path_prefix}%'")
        return " AND ".join(clauses)

    def _fetch(self, query, filt, per_channel):
        t = self.store.table()

        def run(base):
            return (base.where(filt) if filt else base).limit(per_channel).to_list()

        dense_rows = run(t.search(self.embedder.encode_query(query)))
        bm_rows = run(t.search(_fts_query(query), query_type="fts"))
        by_id = {r["chunk_id"]: r for r in dense_rows}
        by_id.update({r["chunk_id"]: r for r in bm_rows})
        return [r["chunk_id"] for r in dense_rows], [r["chunk_id"] for r in bm_rows], by_id

    def _channel_scores(self, dense_ids, bm_ids, channel):
        if channel == "dense":
            return {c: 1.0 / (RRF_K + i) for i, c in enumerate(dense_ids, 1)}
        if channel == "bm25":
            return {c: 1.0 / (RRF_K + i) for i, c in enumerate(bm_ids, 1)}
        return self._rrf([dense_ids, bm_ids])

    def search(
        self,
        query: str,
        k: int = 10,
        repo: str | None = None,
        path_prefix: str | None = None,
        language: str | None = None,
        channel: str = "fused",
        per_channel: int = PER_CHANNEL,
    ) -> list[Result]:
        filt = self._filter(repo, path_prefix, language)
        dense_ids, bm_ids, by_id = self._fetch(query, filt, per_channel)
        scores = self._channel_scores(dense_ids, bm_ids, channel)
        order = sorted(scores, key=lambda c: scores[c], reverse=True)[:k]
        return [self._result(by_id[c], scores[c]) for c in order]

    def search_all(
        self, query: str, k: int = 10, repo: str | None = None, per_channel: int = PER_CHANNEL
    ) -> dict[str, list[Result]]:
        """All three channels from a single dense+BM25 fetch (no re-embedding). For the eval."""
        filt = self._filter(repo, None, None)
        dense_ids, bm_ids, by_id = self._fetch(query, filt, per_channel)
        out = {}
        for channel in ("dense", "bm25", "fused"):
            scores = self._channel_scores(dense_ids, bm_ids, channel)
            order = sorted(scores, key=lambda c: scores[c], reverse=True)[:k]
            out[channel] = [self._result(by_id[c], scores[c]) for c in order]
        return out

    @staticmethod
    def _rrf(channels: list[list[str]]) -> dict[str, float]:
        scores: dict[str, float] = defaultdict(float)
        for ranked in channels:
            for rank, cid in enumerate(ranked, start=1):
                scores[cid] += 1.0 / (RRF_K + rank)
        return scores

    @staticmethod
    def _result(row: dict, score: float) -> Result:
        snippet = "\n".join(row["content"].split("\n")[:SNIPPET_LINES])
        return Result(
            repo=row["repo"],
            path=row["path"],
            start_line=row["start_line"],
            end_line=row["end_line"],
            symbol=row["symbol"],
            kind=row["kind"],
            language=row["language"],
            score=score,
            snippet=snippet,
        )


def format_results(results: list[Result], token_budget: int = DEFAULT_TOKEN_BUDGET) -> str:
    """Format as pointer + snippet blocks within a hard token budget (~4 chars/token).

    Trim snippet lines before dropping whole results, so every retained result keeps its pointer.
    """
    if not results:
        return "(no results)"
    char_budget = token_budget * 4
    blocks: list[str] = []
    used = 0
    for r in results:
        header = f"{r.pointer}  [{r.kind}: {r.symbol}]" if r.symbol else f"{r.pointer}  [{r.kind}]"
        lines = r.snippet.split("\n")
        # Shrink this snippet until the block fits in the remaining budget (min 0 lines).
        while True:
            block = header + ("\n" + "\n".join(lines) if lines else "")
            if used + len(block) <= char_budget or not lines:
                break
            lines = lines[:-1]
        if used + len(header) > char_budget:
            break  # no room even for the pointer; stop
        blocks.append(block)
        used += len(block) + 2
    return "\n\n".join(blocks)
