"""tree-sitter AST chunking + line-window fallback splitter.

Chunk boundaries (PLAN §Phase-1):

* ``module_top``  — the contiguous prefix before the first top-level def/class: imports, module
  docstring, top-level constants.
* ``function``    — each top-level function (incl. decorated / exported / arrow-const forms).
* ``class_header``— class signature + docstring + leading attributes, WITHOUT method bodies
  (spans from the class start to the first method).
* ``method``      — each method inside a class, one chunk each, symbol ``Class.method``.
* ``fallback``    — a parse failure, a file with no extractable units, or any single unit longer
  than ``MAX_UNIT_LINES`` gets split by a line window (``WINDOW`` lines, ``OVERLAP`` overlap).

Each chunk carries an ``embed_text`` (the context-prefixed text that gets embedded in Phase 2); the
raw ``content`` is what is returned to the caller / stored for FTS.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from tree_sitter import Node, Parser
from tree_sitter_language_pack import get_language

WINDOW = 200
OVERLAP = 20
MAX_UNIT_LINES = 300
MAX_IMPORTS = 5

# tree-sitter node types per language family.
_PY_IMPORTS = {"import_statement", "import_from_statement"}
_TS_IMPORTS = {"import_statement"}
_TS_LANGS = {"typescript", "tsx", "javascript"}


@dataclass
class Chunk:
    repo: str
    path: str
    language: str
    symbol: str
    kind: str  # function | method | class_header | module_top | fallback
    start_line: int  # 1-based, inclusive
    end_line: int  # 1-based, inclusive
    content: str
    embed_text: str


# An extracted unit before content slicing: (kind, symbol, start_row, end_row) with 0-based rows.
_Unit = tuple[str, str, int, int]


@lru_cache(maxsize=8)
def _parser(language: str) -> Parser:
    return Parser(get_language(language))


def _name(node: Node) -> str:
    n = node.child_by_field_name("name")
    return n.text.decode("utf-8", "replace") if n is not None else ""


def _windows(s: int, e: int) -> list[tuple[int, int]]:
    """Line windows (0-based inclusive rows) over [s, e]: WINDOW lines, OVERLAP overlap."""
    step = WINDOW - OVERLAP
    out: list[tuple[int, int]] = []
    i = s
    while i <= e:
        j = min(i + WINDOW - 1, e)
        out.append((i, j))
        if j == e:
            break
        i += step
    return out


# --- Python ---------------------------------------------------------------------------------

def _py_class(wrapper: Node, cls: Node, cname: str) -> list[_Unit]:
    body = cls.child_by_field_name("body")
    methods: list[Node] = []
    if body is not None:
        for ch in body.named_children:
            eff = ch.child_by_field_name("definition") if ch.type == "decorated_definition" else ch
            if eff is not None and eff.type == "function_definition":
                methods.append(ch)  # keep wrapper (decorators included in span)
    hdr_end = (methods[0].start_point[0] - 1) if methods else wrapper.end_point[0]
    hdr_end = max(hdr_end, wrapper.start_point[0])
    units: list[_Unit] = [("class_header", cname, wrapper.start_point[0], hdr_end)]
    for mw in methods:
        m = mw.child_by_field_name("definition") if mw.type == "decorated_definition" else mw
        units.append(("method", f"{cname}.{_name(m)}", mw.start_point[0], mw.end_point[0]))
    return units


def _extract_python(root: Node) -> tuple[list[_Unit], list[Node]]:
    units: list[_Unit] = []
    imports: list[Node] = []
    first_def_row: int | None = None
    for node in root.named_children:
        eff = node
        if node.type == "decorated_definition":
            eff = node.child_by_field_name("definition")
        if eff is None:
            continue
        if eff.type == "function_definition":
            if first_def_row is None:
                first_def_row = node.start_point[0]
            units.append(("function", _name(eff), node.start_point[0], node.end_point[0]))
        elif eff.type == "class_definition":
            if first_def_row is None:
                first_def_row = node.start_point[0]
            units.extend(_py_class(node, eff, _name(eff)))
        elif node.type in _PY_IMPORTS:
            imports.append(node)
    _prepend_module_top(units, root, first_def_row)
    return units, imports


# --- TypeScript / JavaScript ----------------------------------------------------------------

def _ts_class(wrapper: Node, cls: Node, cname: str) -> list[_Unit]:
    body = cls.child_by_field_name("body")
    methods = [ch for ch in body.named_children if ch.type == "method_definition"] if body else []
    hdr_end = (methods[0].start_point[0] - 1) if methods else wrapper.end_point[0]
    hdr_end = max(hdr_end, wrapper.start_point[0])
    units: list[_Unit] = [("class_header", cname, wrapper.start_point[0], hdr_end)]
    for m in methods:
        units.append(("method", f"{cname}.{_name(m)}", m.start_point[0], m.end_point[0]))
    return units


def _ts_arrow_name(decl: Node) -> str | None:
    """If a lexical/variable declaration binds an arrow/function expression, return its name."""
    for d in decl.named_children:
        if d.type != "variable_declarator":
            continue
        val = d.child_by_field_name("value")
        if val is not None and val.type in ("arrow_function", "function_expression", "function"):
            n = d.child_by_field_name("name")
            return n.text.decode("utf-8", "replace") if n is not None else ""
    return None


def _extract_ts(root: Node) -> tuple[list[_Unit], list[Node]]:
    units: list[_Unit] = []
    imports: list[Node] = []
    first_def_row: int | None = None
    for node in root.named_children:
        eff = node.child_by_field_name("declaration") if node.type == "export_statement" else node
        if eff is None:
            eff = node
        if eff.type == "function_declaration":
            if first_def_row is None:
                first_def_row = node.start_point[0]
            units.append(("function", _name(eff), node.start_point[0], node.end_point[0]))
        elif eff.type == "class_declaration":
            if first_def_row is None:
                first_def_row = node.start_point[0]
            units.extend(_ts_class(node, eff, _name(eff)))
        elif eff.type in ("lexical_declaration", "variable_declaration"):
            name = _ts_arrow_name(eff)
            if name is not None:
                if first_def_row is None:
                    first_def_row = node.start_point[0]
                units.append(("function", name, node.start_point[0], node.end_point[0]))
        elif node.type in _TS_IMPORTS:
            imports.append(node)
    _prepend_module_top(units, root, first_def_row)
    return units, imports


# --- shared ---------------------------------------------------------------------------------

def _prepend_module_top(units: list[_Unit], root: Node, first_def_row: int | None) -> None:
    last_row = root.end_point[0]
    end = (first_def_row - 1) if first_def_row is not None else last_row
    if end >= 0:
        units.insert(0, ("module_top", "", 0, end))


def _imports_csv(imports: list[Node]) -> str:
    parts = []
    for node in imports[:MAX_IMPORTS]:
        parts.append(" ".join(node.text.decode("utf-8", "replace").split()))
    return ", ".join(parts)


def _prefix(repo: str, path: str, kind: str, symbol: str, imports_csv: str) -> str:
    label = f"{kind}: {symbol}" if symbol else kind
    return f"# repo: {repo} | file: {path} | {label} | imports: {imports_csv}"


def chunk_file(repo: str, path: str, language: str, source: bytes) -> list[Chunk]:
    text = source.decode("utf-8", "replace")
    if not text.strip():
        return []  # whitespace-only file: nothing to index
    text_lines = text.split("\n")
    try:
        root = _parser(language).parse(source).root_node
        if language == "python":
            units, imports = _extract_python(root)
        elif language in _TS_LANGS:
            units, imports = _extract_ts(root)
        else:
            units, imports = [], []
    except Exception:
        units, imports = [], []

    # Drop an empty module_top (e.g. a def on line 1) but keep real content.
    units = [u for u in units if not (u[0] == "module_top" and _blank(text_lines, u[2], u[3]))]
    if not units:
        units = [("fallback", "", 0, len(text_lines) - 1)]

    imports_csv = _imports_csv(imports)
    chunks: list[Chunk] = []
    for kind, symbol, s, e in units:
        if e - s + 1 > MAX_UNIT_LINES:
            for ws, we in _windows(s, e):
                chunks.append(_mk(repo, path, language, symbol, "fallback", ws, we, text_lines,
                                  imports_csv))
        else:
            chunks.append(_mk(repo, path, language, symbol, kind, s, e, text_lines, imports_csv))
    return chunks


def _blank(text_lines: list[str], s: int, e: int) -> bool:
    return not any(text_lines[i].strip() for i in range(s, min(e, len(text_lines) - 1) + 1))


def _mk(repo: str, path: str, language: str, symbol: str, kind: str, s: int, e: int,
        text_lines: list[str], imports_csv: str) -> Chunk:
    content = "\n".join(text_lines[s : e + 1])
    prefix = _prefix(repo, path, kind, symbol, imports_csv)
    return Chunk(
        repo=repo,
        path=path,
        language=language,
        symbol=symbol,
        kind=kind,
        start_line=s + 1,
        end_line=e + 1,
        content=content,
        embed_text=f"{prefix}\n{content}",
    )
