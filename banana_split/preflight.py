"""
Runtime compatibility checks for banana-split workflows.

These checks run after diff parsing and before plan application so
unsupported cases fail fast with actionable errors.
"""

from __future__ import annotations

from typing import List

from .config import Config
from .domain import Diff, FileDiff
from .errors import UnsupportedOperationError
from .git_adapter import GitDiffResult


def validate_runtime_support(config: Config, git_diff: GitDiffResult, diff: Diff) -> None:
    """
    Validate whether the current invocation is supported.

    Dry-runs are intentionally permissive, because they do not mutate
    repository history.
    """

    if config.use_staged and not config.dry_run:
        raise UnsupportedOperationError(
            "splitting staged changes currently supports --dry-run only; "
            "re-run with --staged --dry-run"
        )

    if config.dry_run:
        return

    if git_diff.base_commit is None:
        raise UnsupportedOperationError(
            "splitting root commits is not supported yet; use --dry-run to inspect the plan"
        )

    if git_diff.parent_count > 1:
        raise UnsupportedOperationError("splitting merge commits is not supported; use --dry-run")

    special_paths = [_display_path(file) for file in diff.files
                     if file.modes - {"100644", "100755"}]
    if special_paths:
        raise UnsupportedOperationError(
            "submodule/symlink or unsupported file modes: " + ", ".join(special_paths))

    # Replaying overlapping namespace operations separately can create an
    # invalid intermediate tree (rename onto a deleted path, file/dir swaps).
    # Defer these composite transactions until the planner can group them.
    paths_by_file = [{path for path in (file.path_old, file.path_new) if path is not None}
                     for file in diff.files]
    for i, file in enumerate(diff.files):
        if not file.indivisible:
            continue
        for later in paths_by_file[i + 1:]:
            if any(a == b or a.startswith(b + "/") or b.startswith(a + "/")
                   for a in paths_by_file[i] for b in later):
                raise UnsupportedOperationError(
                    "overlapping file-operation paths are not supported yet; use --dry-run")

    binary_paths = _binary_file_paths(diff)
    rename_only_paths = _rename_only_paths(diff)
    mode_only_paths = _mode_only_paths(diff)

    if not (binary_paths or rename_only_paths or mode_only_paths):
        return

    details: List[str] = []
    if binary_paths:
        details.append(f"binary files: {', '.join(binary_paths)}")
    if rename_only_paths:
        details.append(f"rename-only changes: {', '.join(rename_only_paths)}")
    if mode_only_paths:
        details.append(f"mode-only changes: {', '.join(mode_only_paths)}")

    raise UnsupportedOperationError(
        "this commit contains unsupported diff features for non-dry-run splitting "
        f"({'; '.join(details)}). Use --dry-run for now."
    )


def _display_path(file: FileDiff) -> str:
    old_path = file.path_old or "unknown"
    new_path = file.path_new or "unknown"
    if old_path == new_path:
        return new_path
    return f"{old_path} -> {new_path}"


def _binary_file_paths(diff: Diff) -> List[str]:
    return [_display_path(file) for file in diff.files if file.is_binary]


def _rename_only_paths(diff: Diff) -> List[str]:
    return [
        _display_path(file)
        for file in diff.files
        if file.change_type == "rename" and not file.hunks and file.raw_patch is None
    ]


def _mode_only_paths(diff: Diff) -> List[str]:
    return [
        _display_path(file)
        for file in diff.files
        if file.change_type == "modify" and not file.is_binary and not file.hunks and file.raw_patch is None
    ]
