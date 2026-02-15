from typing import Optional

from banana_split.config import Config
from banana_split.domain import Diff, FileDiff
from banana_split.errors import UnsupportedOperationError
from banana_split.git_adapter import GitDiffResult
from banana_split.preflight import validate_runtime_support


def _config(*, dry_run: bool = False, use_staged: bool = False) -> Config:
    return Config(
        target=None,
        use_staged=use_staged,
        dry_run=dry_run,
        use_ai=False,
        verbosity=0,
    )


def _git_diff(*, base: Optional[str] = "base", target: Optional[str] = "target") -> GitDiffResult:
    return GitDiffResult(raw_diff="", base_commit=base, target_commit=target)


def _empty_diff() -> Diff:
    return Diff(base_commit=None, target_commit=None, files=[])


def test_validate_runtime_support_rejects_staged_non_dry_run():
    try:
        validate_runtime_support(_config(dry_run=False, use_staged=True), _git_diff(), _empty_diff())
    except UnsupportedOperationError as exc:
        assert "--staged --dry-run" in str(exc)
    else:
        raise AssertionError("expected UnsupportedOperationError to be raised")


def test_validate_runtime_support_rejects_root_commit_for_apply():
    try:
        validate_runtime_support(
            _config(dry_run=False, use_staged=False),
            _git_diff(base=None, target="deadbeef"),
            _empty_diff(),
        )
    except UnsupportedOperationError as exc:
        assert "root commits" in str(exc)
    else:
        raise AssertionError("expected UnsupportedOperationError to be raised")


def test_validate_runtime_support_rejects_binary_changes_for_apply():
    diff = Diff(
        base_commit="base",
        target_commit="target",
        files=[
            FileDiff(
                path_old="blob.bin",
                path_new="blob.bin",
                change_type="modify",
                is_binary=True,
                hunks=[],
            )
        ],
    )

    try:
        validate_runtime_support(_config(), _git_diff(), diff)
    except UnsupportedOperationError as exc:
        message = str(exc)
        assert "binary files" in message
        assert "blob.bin" in message
    else:
        raise AssertionError("expected UnsupportedOperationError to be raised")


def test_validate_runtime_support_rejects_rename_only_changes_for_apply():
    diff = Diff(
        base_commit="base",
        target_commit="target",
        files=[
            FileDiff(
                path_old="old.py",
                path_new="new.py",
                change_type="rename",
                is_binary=False,
                hunks=[],
            )
        ],
    )

    try:
        validate_runtime_support(_config(), _git_diff(), diff)
    except UnsupportedOperationError as exc:
        message = str(exc)
        assert "rename-only changes" in message
        assert "old.py -> new.py" in message
    else:
        raise AssertionError("expected UnsupportedOperationError to be raised")


def test_validate_runtime_support_rejects_mode_only_changes_for_apply():
    diff = Diff(
        base_commit="base",
        target_commit="target",
        files=[
            FileDiff(
                path_old="script.sh",
                path_new="script.sh",
                change_type="modify",
                is_binary=False,
                hunks=[],
            )
        ],
    )

    try:
        validate_runtime_support(_config(), _git_diff(), diff)
    except UnsupportedOperationError as exc:
        message = str(exc)
        assert "mode-only changes" in message
        assert "script.sh" in message
    else:
        raise AssertionError("expected UnsupportedOperationError to be raised")


def test_validate_runtime_support_allows_unsupported_features_in_dry_run():
    diff = Diff(
        base_commit=None,
        target_commit="target",
        files=[
            FileDiff(
                path_old="old.py",
                path_new="new.py",
                change_type="rename",
                is_binary=False,
                hunks=[],
            )
        ],
    )
    validate_runtime_support(
        _config(dry_run=True, use_staged=True),
        _git_diff(base=None, target=None),
        diff,
    )
