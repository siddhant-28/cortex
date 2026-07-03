"""Fixture tests: known Python and TS files produce exact expected chunk boundaries."""

from pathlib import Path

from cortex.chunker import chunk_file

FIXTURES = Path(__file__).parent / "fixtures"


def _boundaries(path: str, language: str):
    src = (FIXTURES / path).read_bytes()
    return [(c.kind, c.symbol, c.start_line, c.end_line)
            for c in chunk_file("fix", path, language, src)]


def test_python_boundaries():
    assert _boundaries("sample.py", "python") == [
        ("module_top", "", 1, 8),
        ("function", "top_level", 9, 11),
        ("function", "decorated", 14, 16),  # decorator included in span
        ("class_header", "Widget", 19, 23),  # class def + docstring + attr, no method bodies
        ("method", "Widget.__init__", 24, 25),
        ("method", "Widget.render", 27, 28),
    ]


def test_typescript_boundaries():
    assert _boundaries("sample.ts", "typescript") == [
        ("module_top", "", 1, 5),
        ("function", "parse", 6, 8),  # export wrapper included
        ("function", "double", 10, 10),  # arrow-const treated as a function
        ("class_header", "Store", 12, 14),
        ("method", "Store.constructor", 15, 17),
        ("method", "Store.add", 19, 21),
    ]


def test_context_prefix_shape():
    src = (FIXTURES / "sample.py").read_bytes()
    chunks = chunk_file("myrepo", "sample.py", "python", src)
    fn = next(c for c in chunks if c.symbol == "top_level")
    first_line = fn.embed_text.splitlines()[0]
    assert first_line.startswith(
        "# repo: myrepo | file: sample.py | function: top_level | imports:"
    )
    assert "import os" in first_line
    # body follows the prefix and contains the real code
    assert "return x + CONST" in fn.embed_text


def test_oversized_unit_falls_back_to_windows():
    # A single function longer than MAX_UNIT_LINES is split into fallback windows.
    body = "\n".join(f"    x{i} = {i}" for i in range(400))
    src = f"def big():\n{body}\n".encode()
    chunks = chunk_file("fix", "big.py", "python", src)
    assert len(chunks) > 1
    assert all(c.kind == "fallback" for c in chunks)


def test_unparseable_file_falls_back_not_crash():
    src = b"def (((( this is not valid python @@@@\n"
    chunks = chunk_file("fix", "bad.py", "python", src)
    assert chunks  # never empty
    assert all(c.kind in ("fallback", "module_top") for c in chunks)
