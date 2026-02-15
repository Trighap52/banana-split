from typing import Optional

from banana_split.analysis.semantic_atomizer import atomize_semantically
from banana_split.domain import Diff, DiffHunk, DiffLine, FileDiff


def _hunk(hid: str, file_path: str, symbol: Optional[str] = None) -> DiffHunk:
    meta = {}
    if symbol:
        meta["symbol"] = symbol
    return DiffHunk(
        id=hid,
        file_path=file_path,
        header="@@ -1 +1 @@",
        lines=[DiffLine(line_type="+", content="x = 1", original_lineno=None, new_lineno=1)],
        meta=meta,
    )


def test_atomizer_splits_by_symbol_in_single_file():
    diff = Diff(
        base_commit="base",
        target_commit="target",
        files=[
            FileDiff(
                path_old="foo.py",
                path_new="foo.py",
                change_type="modify",
                is_binary=False,
                hunks=[
                    _hunk("foo.py::h0", "foo.py", symbol="def foo"),
                    _hunk("foo.py::h1", "foo.py", symbol="def bar"),
                ],
            )
        ],
    )

    atomic_changes = atomize_semantically(diff)
    assert len(atomic_changes) == 2
    assert atomic_changes[0].hunk_ids == ["foo.py::h0"]
    assert atomic_changes[1].hunk_ids == ["foo.py::h1"]


def test_atomizer_orders_source_before_test_with_matching_symbol():
    diff = Diff(
        base_commit="base",
        target_commit="target",
        files=[
            FileDiff(
                path_old="tests/test_service.py",
                path_new="tests/test_service.py",
                change_type="modify",
                is_binary=False,
                hunks=[_hunk("tests/test_service.py::h0", "tests/test_service.py", symbol="def compute")],
            ),
            FileDiff(
                path_old="service.py",
                path_new="service.py",
                change_type="modify",
                is_binary=False,
                hunks=[_hunk("service.py::h0", "service.py", symbol="def compute")],
            ),
        ],
    )

    atomic_changes = atomize_semantically(diff)
    assert len(atomic_changes) == 2
    assert atomic_changes[0].id == "service.py::ac0"
    assert atomic_changes[1].id == "tests/test_service.py::ac0"
    assert "test" not in atomic_changes[0].tags
    assert "test" in atomic_changes[1].tags


def test_atomizer_module_fallback_orders_source_before_test():
    diff = Diff(
        base_commit="base",
        target_commit="target",
        files=[
            FileDiff(
                path_old="tests/test_math.py",
                path_new="tests/test_math.py",
                change_type="modify",
                is_binary=False,
                hunks=[_hunk("tests/test_math.py::h0", "tests/test_math.py", symbol=None)],
            ),
            FileDiff(
                path_old="math.py",
                path_new="math.py",
                change_type="modify",
                is_binary=False,
                hunks=[_hunk("math.py::h0", "math.py", symbol=None)],
            ),
        ],
    )

    atomic_changes = atomize_semantically(diff)
    assert len(atomic_changes) == 2
    assert atomic_changes[0].id == "math.py::ac0"
    assert atomic_changes[1].id == "tests/test_math.py::ac0"
