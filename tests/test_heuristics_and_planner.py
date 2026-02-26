from banana_split.analysis.heuristics import group_hunks
from banana_split.domain import (
    AtomicChange,
    Diff,
    DiffHunk,
    DiffLine,
    FileDiff,
    Plan,
    SuggestedCommit,
)
from banana_split.planner import _validate_and_order_plan
from banana_split.errors import PlanValidationError


def _make_simple_diff() -> Diff:
    lines = [
        DiffLine(line_type="+", content="a = 1", original_lineno=None, new_lineno=1),
        DiffLine(line_type="+", content="b = 2", original_lineno=None, new_lineno=2),
    ]
    hunk1 = DiffHunk(
        id="foo.py::h0",
        file_path="foo.py",
        header="@@ -0,0 +1,2 @@",
        lines=lines,
    )
    file_diff = FileDiff(
        path_old=None,
        path_new="foo.py",
        change_type="add",
        is_binary=False,
        hunks=[hunk1],
    )
    return Diff(base_commit="base", target_commit="target", files=[file_diff])


def _make_diff_with_two_symbols() -> Diff:
    lines1 = [
        DiffLine(line_type="+", content="a = 1", original_lineno=None, new_lineno=1),
    ]
    hunk1 = DiffHunk(
        id="foo.py::h0",
        file_path="foo.py",
        header="@@ -1,1 +1,1 @@ def foo",
        lines=lines1,
        meta={"language": "python", "symbol": "def foo"},
    )

    lines2 = [
        DiffLine(line_type="+", content="b = 2", original_lineno=None, new_lineno=10),
    ]
    hunk2 = DiffHunk(
        id="foo.py::h1",
        file_path="foo.py",
        header="@@ -10,1 +10,1 @@ def bar",
        lines=lines2,
        meta={"language": "python", "symbol": "def bar"},
    )

    file_diff = FileDiff(
        path_old="foo.py",
        path_new="foo.py",
        change_type="modify",
        is_binary=False,
        hunks=[hunk1, hunk2],
    )
    return Diff(base_commit="base", target_commit="target", files=[file_diff])


def test_group_hunks_groups_by_file_and_tags():
    diff = _make_simple_diff()
    atomic_changes = group_hunks(diff)

    assert len(atomic_changes) == 1
    change = atomic_changes[0]
    assert change.hunk_ids == ["foo.py::h0"]
    # Language detection should mark this as python.
    assert "python" in change.tags


def test_group_hunks_splits_by_symbol_within_file():
    diff = _make_diff_with_two_symbols()
    atomic_changes = group_hunks(diff)

    # Two different symbols in the same file should produce two atomic changes.
    assert len(atomic_changes) == 2
    # Flatten mapping from ac id to its hunk ids for easy assertions.
    mapping = {ac.id: set(ac.hunk_ids) for ac in atomic_changes}
    assert any({"foo.py::h0"} == hids for hids in mapping.values())
    assert any({"foo.py::h1"} == hids for hids in mapping.values())


def test_validate_and_order_plan_happy_path():
    diff = _make_simple_diff()
    atomic_changes = [
        AtomicChange(id="foo.py::ac0", hunk_ids=["foo.py::h0"]),
    ]
    suggested_commits = [
        SuggestedCommit(
            id="c1",
            title="Atomic change",
            body=None,
            atomic_change_ids=["foo.py::ac0"],
            hunk_ids=["foo.py::h0"],
            estimated_risk=None,
        )
    ]
    plan = Plan(
        diff=diff,
        atomic_changes=atomic_changes,
        suggested_commits=suggested_commits,
        invariants_checked=False,
    )

    _validate_and_order_plan(plan)
    # Should not raise and should preserve the single commit.
    assert len(plan.suggested_commits) == 1


def test_validate_and_order_plan_detects_missing_hunk():
    diff = _make_simple_diff()
    atomic_changes = [
        AtomicChange(id="foo.py::ac0", hunk_ids=["foo.py::h0"]),
    ]
    # Suggested commit does not reference any hunks.
    suggested_commits = [
        SuggestedCommit(
            id="c1",
            title="Atomic change",
            body=None,
            atomic_change_ids=["foo.py::ac0"],
            hunk_ids=[],
            estimated_risk=None,
        )
    ]
    plan = Plan(
        diff=diff,
        atomic_changes=atomic_changes,
        suggested_commits=suggested_commits,
        invariants_checked=False,
    )

    try:
        _validate_and_order_plan(plan)
    except PlanValidationError as exc:
        message = str(exc)
        assert "does not cover hunks exactly once" in message
    else:
        raise AssertionError("expected PlanValidationError to be raised")


def test_validate_and_order_plan_preserves_cross_file_commit_order():
    hunk_src = DiffHunk(
        id="service.py::h0",
        file_path="service.py",
        header="@@ -1 +1 @@ def compute",
        lines=[DiffLine(line_type="+", content="return 1", original_lineno=None, new_lineno=1)],
    )
    hunk_test = DiffHunk(
        id="tests/test_service.py::h0",
        file_path="tests/test_service.py",
        header="@@ -1 +1 @@ def test_compute",
        lines=[DiffLine(line_type="+", content="assert True", original_lineno=None, new_lineno=1)],
    )
    diff = Diff(
        base_commit="base",
        target_commit="target",
        files=[
            FileDiff(
                path_old="tests/test_service.py",
                path_new="tests/test_service.py",
                change_type="modify",
                is_binary=False,
                hunks=[hunk_test],
            ),
            FileDiff(
                path_old="service.py",
                path_new="service.py",
                change_type="modify",
                is_binary=False,
                hunks=[hunk_src],
            ),
        ],
    )
    atomic_changes = [
        AtomicChange(id="service.py::ac0", hunk_ids=["service.py::h0"]),
        AtomicChange(id="tests/test_service.py::ac0", hunk_ids=["tests/test_service.py::h0"]),
    ]
    # Intentionally source-first even though test file appears first in diff.
    suggested_commits = [
        SuggestedCommit(
            id="src",
            title="Source change",
            body=None,
            atomic_change_ids=["service.py::ac0"],
            hunk_ids=["service.py::h0"],
            estimated_risk=None,
        ),
        SuggestedCommit(
            id="test",
            title="Test change",
            body=None,
            atomic_change_ids=["tests/test_service.py::ac0"],
            hunk_ids=["tests/test_service.py::h0"],
            estimated_risk=None,
        ),
    ]
    plan = Plan(
        diff=diff,
        atomic_changes=atomic_changes,
        suggested_commits=suggested_commits,
        invariants_checked=False,
    )

    _validate_and_order_plan(plan)
    assert [commit.id for commit in plan.suggested_commits] == ["src", "test"]
