from banana_split.apply import apply_plan
from banana_split.config import Config
from banana_split.domain import Diff, Plan
from banana_split.errors import GitError


def _make_plan(base_commit, target_commit):
    diff = Diff(base_commit=base_commit, target_commit=target_commit, files=[])
    atomic_changes = []
    suggested_commits = []
    return Plan(
        diff=diff,
        atomic_changes=atomic_changes,
        suggested_commits=suggested_commits,
        invariants_checked=True,
    )


def test_apply_plan_requires_base_and_target_commits(monkeypatch):
    config = Config(target=None, use_staged=False, dry_run=False, use_ai=False, verbosity=0)
    plan = _make_plan(base_commit=None, target_commit="target")

    try:
        apply_plan(plan, config)
    except GitError as exc:
        assert "cannot apply plan without both base and target commits" in str(exc)
    else:
        raise AssertionError("expected GitError to be raised")


def test_apply_plan_uses_expected_branch_name(monkeypatch):
    base_commit = "a" * 40
    target_commit = "b" * 40
    config = Config(target=None, use_staged=False, dry_run=False, use_ai=False, verbosity=0)

    # Plan with no hunks/commits; enough to test branching behavior.
    plan = _make_plan(base_commit=base_commit, target_commit=target_commit)

    created_branches = []
    checked_out = []
    applied_patches = []
    created_commits = []

    def fake_create_branch(name, start_point):
        created_branches.append((name, start_point))

    def fake_checkout(ref):
        checked_out.append(ref)

    def fake_apply_patch(patch, index_only=False):
        applied_patches.append((patch, index_only))

    def fake_create_commit(message):
        created_commits.append(message)

    def fake_trees_equal(a, b):
        # For this test, pretend trees are always equal.
        return True

    monkeypatch.setattr("banana_split.apply.ensure_repo_clean", lambda: None)
    monkeypatch.setattr("banana_split.apply.get_current_ref", lambda: "main")
    monkeypatch.setattr("banana_split.apply.create_branch", fake_create_branch)
    monkeypatch.setattr("banana_split.apply.checkout", fake_checkout)
    monkeypatch.setattr("banana_split.apply.apply_patch", fake_apply_patch)
    monkeypatch.setattr("banana_split.apply.create_commit", fake_create_commit)
    monkeypatch.setattr("banana_split.apply.trees_equal", fake_trees_equal)

    apply_plan(plan, config)

    assert created_branches, "expected a branch to be created"
    branch_name, start_point = created_branches[0]
    assert branch_name == f"banana-split/split-{target_commit[:7]}"
    assert start_point == base_commit
    assert checked_out == [branch_name]


def test_apply_plan_requires_clean_repo(monkeypatch):
    base_commit = "a" * 40
    target_commit = "b" * 40
    config = Config(target=None, use_staged=False, dry_run=False, use_ai=False, verbosity=0)
    plan = _make_plan(base_commit=base_commit, target_commit=target_commit)

    monkeypatch.setattr(
        "banana_split.apply.ensure_repo_clean",
        lambda: (_ for _ in ()).throw(GitError("dirty repo")),
    )

    try:
        apply_plan(plan, config)
    except GitError as exc:
        assert "dirty repo" in str(exc)
    else:
        raise AssertionError("expected GitError to be raised")


def test_apply_plan_rolls_back_branch_on_failure(monkeypatch):
    base_commit = "a" * 40
    target_commit = "b" * 40
    config = Config(target=None, use_staged=False, dry_run=False, use_ai=False, verbosity=0)
    plan = _make_plan(base_commit=base_commit, target_commit=target_commit)

    checkouts = []
    deleted_branches = []

    monkeypatch.setattr("banana_split.apply.ensure_repo_clean", lambda: None)
    monkeypatch.setattr("banana_split.apply.get_current_ref", lambda: "feature/start")
    monkeypatch.setattr("banana_split.apply.create_branch", lambda name, start: None)

    def fake_checkout(ref):
        checkouts.append(ref)

    def fake_trees_equal(a, b):
        return False

    def fake_delete_branch(name, force=False):
        deleted_branches.append((name, force))

    monkeypatch.setattr("banana_split.apply.checkout", fake_checkout)
    monkeypatch.setattr("banana_split.apply.trees_equal", fake_trees_equal)
    monkeypatch.setattr("banana_split.apply.delete_branch", fake_delete_branch)

    try:
        apply_plan(plan, config)
    except GitError as exc:
        assert "final tree does not match original commit" in str(exc)
    else:
        raise AssertionError("expected GitError to be raised")

    assert checkouts == [f"banana-split/split-{target_commit[:7]}", "feature/start"]
    assert deleted_branches == [(f"banana-split/split-{target_commit[:7]}", True)]
