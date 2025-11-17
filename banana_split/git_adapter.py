"""
Git integration for banana-split.

This module is responsible for interacting with the git CLI to obtain
diffs and to apply patches and create commits. At this scaffolding
stage, the functions are stubs that will be implemented in detail
later.
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from typing import Optional

from .errors import GitError

LOG = logging.getLogger(__name__)


@dataclass
class GitDiffResult:
    """
    Result of running a git diff command for banana-split.

    raw_diff contains the unified diff text; base_commit and
    target_commit identify the commits or trees being compared.
    """

    raw_diff: str
    base_commit: Optional[str]
    target_commit: Optional[str]


def _run_git(
    args: list[str],
    cwd: Optional[str] = None,
    input_text: Optional[str] = None,
) -> subprocess.CompletedProcess[str]:
    """
    Run a git command and return the completed process.

    This helper will be used for all future git invocations so that
    error handling and logging are centralized.
    """

    cmd = ["git", *args]
    LOG.debug("Running git command: %s", " ".join(cmd))
    try:
        completed = subprocess.run(
            cmd,
            cwd=cwd,
            check=False,
            text=True,
            capture_output=True,
            input=input_text,
        )
    except OSError as exc:  # noqa: BLE001
        raise GitError(f"failed to execute git: {exc}") from exc

    if completed.returncode != 0:
        LOG.debug("git stderr: %s", completed.stderr)
        raise GitError(f"git command failed: {' '.join(cmd)}")

    return completed


def get_diff_for_commit(commit: str) -> GitDiffResult:
    """
    Return the unified diff and metadata for a single commit.

    For normal commits, this returns the diff between the commit's
    first parent and the commit itself. For a root commit (with no
    parents), the diff is taken against the empty tree.
    """

    target = _run_git(["rev-parse", commit]).stdout.strip()

    try:
        base = _run_git(["rev-parse", f"{target}^"]).stdout.strip()
        diff_args = ["diff", "--find-renames", f"{base}..{target}"]
    except GitError:
        # The commit likely has no parents (root commit). Compare
        # against the empty tree.
        base = None
        diff_args = ["diff", "--root", "--find-renames", target]

    diff_output = _run_git(diff_args).stdout
    return GitDiffResult(raw_diff=diff_output, base_commit=base, target_commit=target)


def get_diff_for_staged() -> GitDiffResult:
    """
    Return the unified diff and metadata for staged changes.

    The base commit is HEAD; the target tree is the index.
    """

    base = _run_git(["rev-parse", "HEAD"]).stdout.strip()
    diff_output = _run_git(["diff", "--cached", "--find-renames"]).stdout
    return GitDiffResult(raw_diff=diff_output, base_commit=base, target_commit=None)


def apply_patch(patch: str, index_only: bool = False) -> None:
    """
    Apply a unified diff patch to the current repository.

    When index_only is True, the patch is applied to the index without
    touching the working tree.
    """

    args = ["apply"]
    if index_only:
        # Update the index only; leave the working tree unchanged.
        args.append("--cached")

    # Feed the patch via stdin. We rely on git to validate the patch and
    # will raise GitError if it fails.
    _run_git(args, cwd=None, input_text=patch)


def create_commit(message: str) -> None:
    """
    Create a git commit with the given commit message.
    """

    _run_git(["commit", "-m", message])


def create_branch(name: str, start_point: str) -> None:
    """
    Create a new branch pointing at start_point.
    """

    _run_git(["branch", name, start_point])


def checkout(ref: str) -> None:
    """
    Check out the given ref.
    """

    _run_git(["checkout", ref])


def trees_equal(a: str, b: str) -> bool:
    """
    Return True if the trees for commits a and b are identical.
    """

    cmd = ["git", "diff", "--quiet", f"{a}..{b}"]
    LOG.debug("Running git command (diff for equality): %s", " ".join(cmd))
    completed = subprocess.run(
        cmd,
        check=False,
        text=True,
        capture_output=True,
    )
    if completed.returncode == 0:
        return True
    if completed.returncode == 1:
        return False
    raise GitError(f"git diff failed: {' '.join(cmd)}")
