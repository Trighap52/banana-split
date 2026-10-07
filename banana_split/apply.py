"""Build split history in isolation and publish only verified results."""

from __future__ import annotations

import logging
import shutil
import sys
import tempfile
from pathlib import Path

from .config import Config
from .diff_parser import render_partial_diff
from .domain import Plan
from .errors import GitError
from .git_adapter import _run_git, apply_patch, create_commit, ensure_repo_clean
from .validation import validate_plan

LOG = logging.getLogger(__name__)


def apply_plan(plan: Plan, config: Config) -> None:
    """Replay in a detached worktree without changing the caller's checkout."""
    if config.dry_run:
        print(f"Dry run: would create {len(plan.suggested_commits)} commits; no Git changes.")
        return

    base, target = plan.diff.base_commit, plan.diff.target_commit
    if not base or not target:
        raise GitError(
            "cannot apply plan without both base and target commits; "
            "this mode currently supports only splitting real commits"
        )

    # Validate again at the mutation boundary, including after review edits.
    validate_plan(plan)
    if not plan.suggested_commits:
        raise GitError("target has no replayable changes to split")
    ensure_repo_clean()
    repo = _run_git(["rev-parse", "--show-toplevel"]).stdout.strip()
    branch_name = f"banana-split/split-{target[:7]}"
    existing = _run_git(
        ["for-each-ref", "--format=%(refname)", f"refs/heads/{branch_name}"], cwd=repo
    ).stdout.strip()
    if existing:
        raise GitError(f"output branch {branch_name} already exists; choose another target or rename it")

    scratch = Path(tempfile.mkdtemp(prefix="banana-split-apply-"))
    worktree = scratch / "worktree"
    worktree_cwd = str(worktree)
    try:
        _run_git(["worktree", "add", "--detach", worktree_cwd, base], cwd=repo)
        applied_hunks = set()
        for suggested in plan.suggested_commits:
            if not suggested.hunk_ids:
                raise GitError(f"suggested commit {suggested.id} has no hunks")
            patch = render_partial_diff(plan.diff, suggested.hunk_ids, applied_hunk_ids=applied_hunks)
            if not patch.strip():
                raise GitError(f"suggested commit {suggested.id} produced an empty patch")
            # Update both index and worktree so hooks see the current partial tree.
            apply_patch(patch, index_only=False, cwd=worktree_cwd)
            message = suggested.title
            if suggested.body:
                message += f"\n\n{suggested.body}"
            create_commit(message, cwd=worktree_cwd)
            applied_hunks.update(suggested.hunk_ids)

        expected_tree = _run_git(["rev-parse", f"{target}^{{tree}}"], cwd=repo).stdout.strip()
        actual_tree = _run_git(["rev-parse", "HEAD^{tree}"], cwd=worktree_cwd).stdout.strip()
        if actual_tree != expected_tree:
            raise GitError("final tree does not match original commit after applying plan")
        result = _run_git(["rev-parse", "HEAD"], cwd=worktree_cwd).stdout.strip()
    finally:
        # finally also runs for KeyboardInterrupt. Retain recovery files if Git
        # cleanup fails, instead of silently deleting a registered worktree.
        unwinding = sys.exc_info()[0] is not None
        try:
            if worktree.exists():
                _run_git(["worktree", "remove", "--force", worktree_cwd], cwd=repo)
            shutil.rmtree(scratch)
        except (GitError, OSError) as exc:
            if not unwinding:
                raise
            LOG.error("Temporary worktree cleanup failed; recovery path %s: %s", scratch, exc)

    # Creating a branch never overwrites an existing ref, including one created
    # concurrently while replay was running. No output branch exists on failure.
    _run_git(["branch", branch_name, result], cwd=repo)
    print(f"Created {branch_name}; final tree matches {target}. Current checkout unchanged.")
