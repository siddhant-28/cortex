"""Unit tests for retriever pure logic: RRF fusion, FTS sanitization, budget formatter."""

from cortex.retriever import Result, Retriever, _fts_query, format_results


def test_fts_query_strips_punctuation_and_caps():
    assert _fts_query("df.loc[x] = `foo`! (bar)") == "df loc x foo bar"
    assert _fts_query("a b c d", max_tokens=2) == "a b"


def test_rrf_rewards_agreement_across_channels():
    # 'b' appears in both channels -> should outrank items in only one.
    scores = Retriever._rrf([["a", "b", "c"], ["b", "d", "e"]])
    ranked = sorted(scores, key=lambda c: scores[c], reverse=True)
    assert ranked[0] == "b"
    # 'a' (rank1 in ch0) beats 'd' (rank2 in ch1)
    assert scores["a"] > scores["d"]


def _mk(path, kind="function", symbol="f", snippet="line1\nline2\nline3"):
    return Result("repo", path, 1, 3, symbol, kind, "python", 0.1, snippet)


def test_format_results_stays_within_budget():
    results = [_mk(f"pkg/mod{i}.py", snippet="x" * 400) for i in range(20)]
    out = format_results(results, token_budget=200)
    assert len(out) // 4 <= 200


def test_format_results_keeps_pointer_lines():
    out = format_results([_mk("pkg/a.py")], token_budget=2500)
    assert "repo/pkg/a.py:1-3" in out


def test_format_results_empty():
    assert format_results([]) == "(no results)"
