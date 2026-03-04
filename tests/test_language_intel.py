from banana_split.analysis.language_intel import (
    extract_python_symbol_for_hunk,
    extract_python_symbol_for_lines,
)
from banana_split.domain import DiffHunk, DiffLine


def test_extract_python_symbol_for_lines_function():
    source = (
        "def compute(x):\n"
        "    return x + 1\n"
    )

    symbol = extract_python_symbol_for_lines(source, [2])
    assert symbol == "def compute"


def test_extract_python_symbol_for_lines_method():
    source = (
        "class Service:\n"
        "    def handle(self):\n"
        "        return 1\n"
    )

    symbol = extract_python_symbol_for_lines(source, [3])
    assert symbol == "def Service.handle"


def test_extract_python_symbol_for_lines_nested_scope():
    source = (
        "def outer():\n"
        "    x = 1\n"
        "    def inner():\n"
        "        return x\n"
        "    return inner()\n"
    )

    inner_symbol = extract_python_symbol_for_lines(source, [4])
    outer_symbol = extract_python_symbol_for_lines(source, [2])

    assert inner_symbol == "def outer.inner"
    assert outer_symbol == "def outer"


def test_extract_python_symbol_for_lines_decorated_function():
    source = (
        "@cached\n"
        "@trace(\"x\")\n"
        "def work():\n"
        "    return 1\n"
    )

    symbol = extract_python_symbol_for_lines(source, [1])
    assert symbol == "def work"


def test_extract_python_symbol_for_lines_returns_none_when_ast_parse_fails():
    source = (
        "def broken(:\n"
        "    return 1\n"
    )
    assert extract_python_symbol_for_lines(source, [1, 2]) is None


def test_extract_python_symbol_for_hunk_supports_new_and_old_sides():
    source_old = (
        "def old_name():\n"
        "    return 1\n"
    )
    source_new = (
        "def new_name():\n"
        "    return 2\n"
    )
    hunk = DiffHunk(
        id="foo.py::h0",
        file_path="foo.py",
        header="@@ -1,2 +1,2 @@",
        lines=[
            DiffLine(line_type="-", content="def old_name():", original_lineno=1, new_lineno=None),
            DiffLine(line_type="+", content="def new_name():", original_lineno=None, new_lineno=1),
            DiffLine(line_type="-", content="    return 1", original_lineno=2, new_lineno=None),
            DiffLine(line_type="+", content="    return 2", original_lineno=None, new_lineno=2),
        ],
    )

    symbol_new = extract_python_symbol_for_hunk(hunk, source_new, side="new")
    symbol_old = extract_python_symbol_for_hunk(hunk, source_old, side="old")

    assert symbol_new == "def new_name"
    assert symbol_old == "def old_name"
