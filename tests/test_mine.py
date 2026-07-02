"""Unit tests for the pure helpers in bench/mine.py (no network / token needed)."""

from bench.mine import closing_issue_numbers, is_docs_or_test_only, word_count


def test_closing_keywords_and_inflections():
    assert closing_issue_numbers({"title": "Fix crash", "body": "fixes #123"}) == {123}
    assert closing_issue_numbers({"title": "closes #7", "body": ""}) == {7}
    both = {"title": "", "body": "This resolves #9 and closed #10"}
    assert closing_issue_numbers(both) == {9, 10}


def test_non_closing_references_ignored():
    # A bare "#123" or "see #123" is not a closing keyword and must not count.
    assert closing_issue_numbers({"title": "see #123", "body": "related to #99"}) == set()
    assert closing_issue_numbers({"title": "", "body": ""}) == set()


def test_docs_or_test_only_detection():
    assert is_docs_or_test_only(["docs/guide.rst", "README.md"]) is True
    assert is_docs_or_test_only(["tests/test_app.py", "conftest.py"]) is True
    assert is_docs_or_test_only(["src/flask/app.py"]) is False
    # mixed source + docs is NOT docs-only -> keep it
    assert is_docs_or_test_only(["src/flask/app.py", "docs/api.rst"]) is False
    # empty -> not docs-only (nothing to judge)
    assert is_docs_or_test_only([]) is False


def test_word_count():
    assert word_count("one two three") == 3
    assert word_count("") == 0
