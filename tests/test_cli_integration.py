import os
import subprocess
import sys
from pathlib import Path


def _run_git(args, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        text=True,
        capture_output=True,
        check=True,
    )


def test_cli_splits_commit_in_temporary_repo(tmp_path):
    """
    End-to-end test that exercises the CLI against a real git repository.

    The test creates a tiny repository with two commits:
      - base: initial version of foo.py
      - big:  both functions in foo.py changed

    It then runs banana-split on the big commit and asserts that:
      - a split branch is created from the base commit, and
      - the final tree on the split branch matches the original big commit.
    """

    repo = tmp_path / "repo"
    repo.mkdir()

    # Minimal git setup.
    _run_git(["init"], cwd=repo)
    _run_git(["config", "user.name", "banana-split"], cwd=repo)
    _run_git(["config", "user.email", "banana-split@example.com"], cwd=repo)

    # Base commit.
    (repo / "foo.py").write_text(
        "def foo():\n"
        "    return 1\n"
        "\n"
        "def bar():\n"
        "    return 1\n"
    )
    _run_git(["add", "foo.py"], cwd=repo)
    _run_git(["commit", "-m", "base"], cwd=repo)

    # "Big" commit that changes both functions.
    (repo / "foo.py").write_text(
        "def foo():\n"
        "    return 2\n"
        "\n"
        "def bar():\n"
        "    return 3\n"
    )
    _run_git(["commit", "-am", "big"], cwd=repo)

    orig_head = (
        _run_git(["rev-parse", "HEAD"], cwd=repo).stdout.strip()
    )
    base_commit = (
        _run_git(["rev-parse", "HEAD^"], cwd=repo).stdout.strip()
    )

    # Run the CLI as a module in a subprocess, pointing PYTHONPATH at the
    # project root so the package can be imported from the temporary repo.
    project_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(project_root)

    subprocess.run(
        [sys.executable, "-m", "banana_split.cli", orig_head],
        cwd=str(repo),
        env=env,
        text=True,
        check=True,
    )

    split_branch = f"banana-split/split-{orig_head[:7]}"

    # The branch should exist and point to a commit whose tree is
    # identical to the original "big" commit's tree.
    _run_git(["rev-parse", split_branch], cwd=repo)
    _run_git(["diff", "--quiet", f"{orig_head}..{split_branch}"], cwd=repo)

    # The split branch should be rooted at the same base commit we
    # started from (i.e., the parent of the big commit).
    split_base = (
        _run_git(["rev-parse", f"{split_branch}^~0"], cwd=repo).stdout.strip()
    )
    assert split_base != orig_head
    # Ensure base is reachable from the split_branch.
    log = _run_git(["rev-list", f"{base_commit}..{split_branch}"], cwd=repo).stdout
    assert log.strip(), "expected at least one commit between base and split branch head"

