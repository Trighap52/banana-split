"""Real-Git regressions for transactional split execution."""

import subprocess
from pathlib import Path

import pytest

from banana_split.apply import apply_plan
from banana_split.config import Config
from banana_split.domain import Diff, Plan
from banana_split.errors import GitError, PlanValidationError
from banana_split.planner import build_plan


def git(repo, *args):
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path, monkeypatch):
    path = tmp_path / "repo"
    path.mkdir()
    git(path, "init")
    git(path, "config", "user.name", "banana-split-test")
    git(path, "config", "user.email", "test@example.com")
    for name in ("foo.py", "bar.py"):
        (path / name).write_text("value = 1\n")
    git(path, "add", ".")
    git(path, "commit", "-m", "base")
    for name in ("foo.py", "bar.py"):
        (path / name).write_text("value = 2\n")
    git(path, "commit", "-am", "target")
    monkeypatch.chdir(path)
    return path


def snapshot(repo):
    index = Path(git(repo, "rev-parse", "--git-path", "index"))
    if not index.is_absolute():
        index = repo / index
    return (
        git(repo, "rev-parse", "HEAD"),
        git(repo, "rev-parse", "--abbrev-ref", "HEAD"),
        index.read_bytes(),
        {str(p.relative_to(repo)): p.read_bytes() for p in repo.rglob("*")
         if p.is_file() and ".git" not in p.relative_to(repo).parts},
        git(repo, "worktree", "list", "--porcelain"),
    )


def branch(plan):
    return f"banana-split/split-{plan.diff.target_commit[:7]}"


def assert_no_output(repo):
    assert git(repo, "for-each-ref", "--format=%(refname)", "refs/heads/banana-split/") == ""


def test_apply_plan_requires_base_and_target_commits():
    plan = Plan(diff=Diff(base_commit=None, target_commit="target"))
    with pytest.raises(GitError, match="cannot apply plan without both"):
        apply_plan(plan, Config())


@pytest.mark.parametrize("detached", [False, True])
def test_success_preserves_checkout_index_and_files(repo, detached):
    plan = build_plan(Config())
    assert len(plan.suggested_commits) == 2
    if detached:
        git(repo, "checkout", "--detach")
    before = snapshot(repo)
    apply_plan(plan, Config())
    assert snapshot(repo) == before
    assert git(repo, "rev-parse", branch(plan) + "^{tree}") == git(repo, "rev-parse", "HEAD^{tree}")
    assert len(git(repo, "rev-list", f"{plan.diff.base_commit}..{branch(plan)}").splitlines()) == 2
    assert git(repo, "status", "--porcelain") == ""


@pytest.mark.parametrize("exception", [GitError("commit failed"), KeyboardInterrupt()])
def test_mid_apply_failure_or_cancellation_leaves_no_branch(repo, monkeypatch, exception):
    import banana_split.apply as module
    plan = build_plan(Config())
    before = snapshot(repo)
    real_commit = module.create_commit
    count = 0

    def fail_second_commit(message, *, cwd=None):
        nonlocal count
        count += 1
        if count == 2:
            raise exception
        real_commit(message, cwd=cwd)

    monkeypatch.setattr(module, "create_commit", fail_second_commit)
    with pytest.raises(type(exception)):
        apply_plan(plan, Config())
    assert count == 2
    assert snapshot(repo) == before
    assert_no_output(repo)


def test_tree_mismatch_leaves_caller_untouched(repo, monkeypatch):
    import banana_split.apply as module
    plan = build_plan(Config())
    before = snapshot(repo)
    real_commit = module.create_commit

    def alter_commit(message, *, cwd=None):
        (Path(cwd) / "extra.txt").write_text("unexpected\n")
        git(cwd, "add", "extra.txt")
        real_commit(message, cwd=cwd)

    monkeypatch.setattr(module, "create_commit", alter_commit)
    with pytest.raises(GitError, match="final tree does not match"):
        apply_plan(plan, Config())
    assert snapshot(repo) == before
    assert_no_output(repo)


def test_failed_commit_hook_cleans_worktree(repo):
    plan = build_plan(Config())
    hook = repo / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\nexit 1\n")
    hook.chmod(0o755)
    before = snapshot(repo)
    with pytest.raises(GitError):
        apply_plan(plan, Config())
    assert snapshot(repo) == before
    assert_no_output(repo)


def test_existing_branch_is_never_overwritten(repo):
    plan = build_plan(Config())
    git(repo, "branch", branch(plan), plan.diff.base_commit)
    before = snapshot(repo)
    with pytest.raises(GitError, match="already exists"):
        apply_plan(plan, Config())
    assert snapshot(repo) == before
    assert git(repo, "rev-parse", branch(plan)) == plan.diff.base_commit


def test_dirty_repo_is_rejected_without_mutation(repo):
    plan = build_plan(Config())
    (repo / "untracked.txt").write_text("keep me\n")
    (repo / "foo.py").write_text("staged = True\n")
    git(repo, "add", "foo.py")
    (repo / "foo.py").write_text("unstaged = True\n")
    before = snapshot(repo)
    with pytest.raises(GitError, match="uncommitted changes"):
        apply_plan(plan, Config())
    assert snapshot(repo) == before
    assert_no_output(repo)


def test_apply_from_subdirectory_uses_explicit_repo_root(repo, monkeypatch):
    plan = build_plan(Config())
    subdir = repo / "nested"
    subdir.mkdir()
    before = snapshot(repo)
    monkeypatch.chdir(subdir)
    apply_plan(plan, Config())
    assert snapshot(repo) == before


def test_edited_invalid_plan_is_rejected_before_mutation(repo):
    plan = build_plan(Config())
    plan.suggested_commits[0].hunk_ids = []
    before = snapshot(repo)
    with pytest.raises(PlanValidationError):
        apply_plan(plan, Config())
    assert snapshot(repo) == before
    assert_no_output(repo)


def test_dry_run_is_visible_and_never_mutates(repo, capsys):
    plan = build_plan(Config(dry_run=True))
    before = snapshot(repo)
    apply_plan(plan, Config(dry_run=True))
    assert "Dry run:" in capsys.readouterr().out
    assert snapshot(repo) == before
    assert_no_output(repo)


def test_commit_hook_sees_current_partial_worktree(repo):
    plan = build_plan(Config())
    hook = repo / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\ngit diff --exit-code --quiet || exit 1\n")
    hook.chmod(0o755)
    before = snapshot(repo)
    apply_plan(plan, Config())
    assert snapshot(repo) == before
