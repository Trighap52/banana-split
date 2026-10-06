"""
Git integration for banana-split.

This module is responsible for interacting with the git CLI to obtain
diffs and to apply patches and create commits.
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
    parent_count: int = 1


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
            capture_output=True,
            input=input_text.encode("utf-8", "surrogateescape") if input_text is not None else None,
        )
    except OSError as exc:  # noqa: BLE001
        raise GitError(f"failed to execute git: {exc}") from exc

    # Decode explicitly: subprocess text mode normalizes CRLF and cannot carry
    # arbitrary non-UTF-8 source bytes. Surrogateescape is lossless on replay.
    for name in ("stdout", "stderr"):
        value = getattr(completed, name)
        if isinstance(value, bytes):
            setattr(completed, name, value.decode("utf-8", "surrogateescape"))

    if completed.returncode != 0:
        LOG.debug("git stderr: %s", completed.stderr)
        stderr = (completed.stderr or "").strip()
        stdout = (completed.stdout or "").strip()
        detail = stderr or stdout or "no command output"
        raise GitError(f"git command failed: {' '.join(cmd)}: {detail}")

    return completed


def get_diff_for_commit(commit: str) -> GitDiffResult:
    """
    Return the unified diff and metadata for a single commit.

    For normal commits, this returns the diff between the commit's
    first parent and the commit itself. For a root commit (with no
    parents), the diff is taken against the empty tree.
    """

    target = _run_git(["rev-parse", "--verify", "--end-of-options", f"{commit}^{{commit}}"]).stdout.strip()
    parents = _run_git(["rev-list", "--parents", "-n", "1", target]).stdout.split()[1:]
    base = parents[0] if parents else None
    if base:
        args = ["diff", *_diff_options(), base, target, "--"]
    else:
        args = ["diff-tree", "--root", "--no-commit-id", "-p", *_diff_options(), target, "--"]
    return GitDiffResult(_run_git(args).stdout, base, target, len(parents))


def _diff_options() -> list[str]:
    """Use a machine-readable patch regardless of local diff configuration."""
    return ["--no-ext-diff", "--no-textconv", "--no-color", "--no-relative",
            "--src-prefix=a/", "--dst-prefix=b/", "--find-renames",
            "--full-index", "--ignore-submodules=none", "--submodule=short", "--unified=3"]


def get_diff_for_staged() -> GitDiffResult:
    """
    Return the unified diff and metadata for staged changes.

    The base commit is HEAD; the target tree is the index.
    """

    base = _run_git(["rev-parse", "HEAD"]).stdout.strip()
    diff_output = _run_git(["diff", "--cached", *_diff_options(), "--"]).stdout
    return GitDiffResult(raw_diff=diff_output, base_commit=base, target_commit=None)


def get_file_content_at_commit(commit: str, path: str) -> Optional[str]:
    """
    Return file content for `path` at `commit`, or None if unavailable.
    """

    try:
        return _run_git(["show", f"{commit}:{path}"]).stdout
    except GitError:
        return None


def get_staged_file_content(path: str) -> Optional[str]:
    """
    Return staged content for `path` from the index, or None if unavailable.
    """

    try:
        return _run_git(["show", f":{path}"]).stdout
    except GitError:
        return None


def apply_patch(patch: str, index_only: bool = False, *, cwd: Optional[str] = None) -> None:
    """
    Apply a unified diff patch in the selected repository.

    By default, update both the index and working tree. When index_only
    is True, update only the index.
    """

    args = ["apply"]
    if index_only:
        # Update the index only; leave the working tree unchanged.
        args.append("--cached")
    else:
        args.append("--index")

    # Feed the patch via stdin. We rely on git to validate the patch and
    # will raise GitError if it fails.
    _run_git(args, cwd=cwd, input_text=patch)


def create_commit(message: str, *, cwd: Optional[str] = None) -> None:
    """
    Create a git commit with the given commit message.
    """

    _run_git(["commit", "-m", message], cwd=cwd)


def create_branch(name: str, start_point: str) -> None:
    """
    Create a new branch pointing at start_point.
    """

    _run_git(["branch", name, start_point])


def delete_branch(name: str, force: bool = False) -> None:
    """
    Delete a local branch.
    """

    mode = "-D" if force else "-d"
    _run_git(["branch", mode, name])


def checkout(ref: str) -> None:
    """
    Check out the given ref.
    """

    _run_git(["checkout", ref])


def get_current_ref() -> str:
    """
    Return the current branch name, or HEAD commit when detached.
    """

    cmd = ["git", "symbolic-ref", "--quiet", "--short", "HEAD"]
    LOG.debug("Running git command: %s", " ".join(cmd))
    completed = subprocess.run(
        cmd,
        check=False,
        text=True,
        capture_output=True,
    )
    if completed.returncode == 0:
        branch = completed.stdout.strip()
        if branch:
            return branch
    if completed.returncode not in (0, 1):
        detail = (completed.stderr or "").strip() or "no command output"
        raise GitError(f"git command failed: {' '.join(cmd)}: {detail}")

    # Detached HEAD: fall back to the current commit hash.
    return _run_git(["rev-parse", "HEAD"]).stdout.strip()


def ensure_repo_clean() -> None:
    """
    Ensure there are no uncommitted changes before rewriting history.
    """

    # Read status without refreshing/writing the caller's index.
    status = _run_git(["--no-optional-locks", "status", "--porcelain"]).stdout
    dirty = [line for line in status.splitlines() if line.strip()]
    if not dirty:
        return

    preview = "; ".join(dirty[:3])
    if len(dirty) > 3:
        preview += "; ..."
    raise GitError(
        "repository has uncommitted changes; please commit/stash/clean before running "
        f"banana-split ({preview})"
    )


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
    detail = (completed.stderr or "").strip() or (completed.stdout or "").strip() or "no command output"
    raise GitError(f"git diff failed: {' '.join(cmd)}: {detail}")
