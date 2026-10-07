import json
import subprocess
from pathlib import Path

from banana_split.domain import (
    AtomicChange,
    Diff,
    DiffHunk,
    DiffLine,
    FileDiff,
    Plan,
    SuggestedCommit,
)
from banana_split.eval.harness import _plan_metrics, load_eval_corpus, run_evaluation


def _run_git(args, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        text=True,
        capture_output=True,
        check=True,
    )


def test_load_eval_corpus_from_list(tmp_path):
    corpus_path = tmp_path / "corpus.json"
    corpus_path.write_text(
        json.dumps(
            [
                {
                    "name": "sample",
                    "repo_url": "https://example.com/repo.git",
                    "target": "HEAD",
                    "branch": "main",
                    "clone_depth": 50,
                }
            ]
        )
    )

    cases = load_eval_corpus(str(corpus_path))
    assert len(cases) == 1
    assert cases[0].name == "sample"
    assert cases[0].repo_url == "https://example.com/repo.git"
    assert cases[0].target == "HEAD"
    assert cases[0].branch == "main"
    assert cases[0].clone_depth == 50


def test_plan_metrics_computes_size_and_cohesion():
    hunk0 = DiffHunk(
        id="foo.py::h0",
        file_path="foo.py",
        header="@@ -1 +1 @@ def foo",
        lines=[DiffLine(line_type="+", content="return 1")],
        meta={"symbol": "def foo"},
    )
    hunk1 = DiffHunk(
        id="bar.py::h0",
        file_path="bar.py",
        header="@@ -1 +1 @@ def bar",
        lines=[DiffLine(line_type="+", content="return 2")],
        meta={"symbol": "def bar"},
    )
    diff = Diff(
        base_commit="base",
        target_commit="target",
        files=[
            FileDiff(
                path_old="foo.py",
                path_new="foo.py",
                change_type="modify",
                is_binary=False,
                hunks=[hunk0],
            ),
            FileDiff(
                path_old="bar.py",
                path_new="bar.py",
                change_type="modify",
                is_binary=False,
                hunks=[hunk1],
            ),
        ],
    )
    plan = Plan(
        diff=diff,
        atomic_changes=[],
        suggested_commits=[
            SuggestedCommit(
                id="c1",
                title="foo",
                body=None,
                atomic_change_ids=[],
                hunk_ids=["foo.py::h0"],
                estimated_risk=None,
            ),
            SuggestedCommit(
                id="c2",
                title="mixed",
                body=None,
                atomic_change_ids=[],
                hunk_ids=["foo.py::h0", "bar.py::h0"],
                estimated_risk=None,
            ),
        ],
        invariants_checked=True,
    )

    metrics = _plan_metrics(plan)
    assert metrics["suggested_commit_count"] == 2
    assert metrics["total_hunks_in_suggested_commits"] == 3
    assert metrics["single_file_commit_count"] == 1
    assert metrics["single_symbol_commit_count"] == 1
    assert metrics["semantic_cohesion_score_sum"] == 1.0
    assert metrics["expected_dependency_pairs"] == 0
    assert metrics["satisfied_dependency_pairs"] == 0
    assert metrics["dependency_order_satisfaction"] == 0.0


def test_plan_metrics_dependency_order_satisfaction():
    src_hunk = DiffHunk(
        id="service.py::h0",
        file_path="service.py",
        header="@@ -1 +1 @@ def compute",
        lines=[DiffLine(line_type="+", content="return 2")],
        meta={"symbol": "def compute"},
    )
    test_hunk = DiffHunk(
        id="tests/test_service.py::h0",
        file_path="tests/test_service.py",
        header="@@ -1 +1 @@ def test_compute",
        lines=[DiffLine(line_type="+", content="assert compute() == 2")],
        meta={"symbol": "def compute"},
    )
    diff = Diff(
        base_commit="base",
        target_commit="target",
        files=[
            FileDiff(
                path_old="service.py",
                path_new="service.py",
                change_type="modify",
                is_binary=False,
                hunks=[src_hunk],
            ),
            FileDiff(
                path_old="tests/test_service.py",
                path_new="tests/test_service.py",
                change_type="modify",
                is_binary=False,
                hunks=[test_hunk],
            ),
        ],
    )
    atomic_changes = [
        AtomicChange(
            id="service.py::ac0",
            hunk_ids=["service.py::h0"],
            tags={"python", "module:service", "symbol:def compute", "path:service.py"},
            summary="src",
        ),
        AtomicChange(
            id="tests/test_service.py::ac0",
            hunk_ids=["tests/test_service.py::h0"],
            tags={
                "python",
                "test",
                "module:service",
                "symbol:def compute",
                "path:tests/test_service.py",
            },
            summary="test",
        ),
    ]
    plan = Plan(
        diff=diff,
        atomic_changes=atomic_changes,
        # Intentionally reversed to simulate semantic-order violation.
        suggested_commits=[
            SuggestedCommit(
                id="test",
                title="test first",
                body=None,
                atomic_change_ids=["tests/test_service.py::ac0"],
                hunk_ids=["tests/test_service.py::h0"],
                estimated_risk=None,
            ),
            SuggestedCommit(
                id="src",
                title="src second",
                body=None,
                atomic_change_ids=["service.py::ac0"],
                hunk_ids=["service.py::h0"],
                estimated_risk=None,
            ),
        ],
        invariants_checked=True,
    )

    metrics = _plan_metrics(plan)
    assert metrics["expected_dependency_pairs"] == 1
    assert metrics["satisfied_dependency_pairs"] == 0
    assert metrics["dependency_order_satisfaction"] == 0.0


def test_run_evaluation_on_local_repo(tmp_path):
    source_repo = tmp_path / "source-repo"
    source_repo.mkdir()

    _run_git(["init"], cwd=source_repo)
    _run_git(["config", "user.name", "banana-split"], cwd=source_repo)
    _run_git(["config", "user.email", "banana-split@example.com"], cwd=source_repo)

    (source_repo / "foo.py").write_text(
        "def foo():\n"
        "    return 1\n"
        "\n"
        "def bar():\n"
        "    return 1\n"
    )
    _run_git(["add", "foo.py"], cwd=source_repo)
    _run_git(["commit", "-m", "base"], cwd=source_repo)

    (source_repo / "foo.py").write_text(
        "def foo():\n"
        "    return 2\n"
        "\n"
        "def bar():\n"
        "    return 3\n"
    )
    _run_git(["commit", "-am", "big"], cwd=source_repo)

    head = _run_git(["rev-parse", "HEAD"], cwd=source_repo).stdout.strip()

    corpus_path = tmp_path / "corpus.json"
    corpus_path.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "name": "local-python-commit",
                        "repo_url": source_repo.as_uri(),
                        "target": head,
                        "clone_depth": 20,
                    }
                ]
            }
        )
    )

    report = run_evaluation(
        corpus_path=str(corpus_path),
        use_ai=False,
        verbosity=0,
    )

    summary = report["summary"]
    assert summary["total_cases"] == 1
    assert summary["successful_cases"] == 1
    assert summary["tree_equal_success_rate"] == 1.0
    assert summary["apply_failure_rate"] == 0.0


def test_pinned_old_commit_is_fetched_outside_initial_clone_depth(tmp_path):
    from banana_split.eval.harness import EvalCase, _clone_repo
    source = tmp_path / 'source'
    source.mkdir()
    _run_git(['init'], cwd=source)
    _run_git(['config', 'user.name', 'Eval'], cwd=source)
    _run_git(['config', 'user.email', 'eval@example.com'], cwd=source)
    targets = []
    for value in range(5):
        (source / 'value.py').write_text(f'value = {value}\n')
        _run_git(['add', '.'], cwd=source)
        _run_git(['commit', '-m', f'value {value}'], cwd=source)
        targets.append(_run_git(['rev-parse', 'HEAD'], cwd=source).stdout.strip())
    clone = tmp_path / 'clone'
    resolved = _clone_repo(EvalCase('old', source.as_uri(), targets[1], clone_depth=1), clone)
    assert resolved == targets[1]
    assert _run_git(['rev-parse', resolved + '^'], cwd=clone).stdout.strip() == targets[0]
    corpus = tmp_path / 'corpus.json'
    corpus.write_text(json.dumps({'cases': [
        {'name': 'valid-old', 'repo_url': source.as_uri(), 'target': targets[1], 'clone_depth': 1},
        {'name': 'missing-target', 'repo_url': source.as_uri(), 'target': '0' * 40, 'clone_depth': 1},
    ]}))
    report = run_evaluation(corpus_path=str(corpus), use_ai=False, verbosity=0)
    assert report['summary']['total_cases'] == 2
    assert report['summary']['successful_cases'] == 1
    assert report['summary']['plan_build_failures'] == 1
    assert report['summary']['tree_equal_success_rate'] == 0.5
    assert report['summary']['apply_tree_equal_success_rate'] == 1.0
    assert report['cases'][0]['resolved_target'] == targets[1]
