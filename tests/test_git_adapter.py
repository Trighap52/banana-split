import subprocess

from banana_split.errors import GitError
from banana_split.git_adapter import _run_git, ensure_repo_clean


def test_run_git_includes_stderr_details_on_failure(monkeypatch):
    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=["git", "status"],
            returncode=128,
            stdout="",
            stderr="fatal: not a git repository",
        )

    monkeypatch.setattr("banana_split.git_adapter.subprocess.run", fake_run)

    try:
        _run_git(["status"])
    except GitError as exc:
        message = str(exc)
        assert "git status" in message
        assert "fatal: not a git repository" in message
    else:
        raise AssertionError("expected GitError to be raised")


def test_ensure_repo_clean_reports_dirty_entries(monkeypatch):
    class FakeCompleted:
        def __init__(self, stdout: str):
            self.stdout = stdout

    monkeypatch.setattr(
        "banana_split.git_adapter._run_git",
        lambda args, cwd=None, input_text=None: FakeCompleted(" M foo.py\n?? tmp.txt\n"),
    )

    try:
        ensure_repo_clean()
    except GitError as exc:
        message = str(exc)
        assert "repository has uncommitted changes" in message
        assert "foo.py" in message
    else:
        raise AssertionError("expected GitError to be raised")
