import os
import subprocess
import sys
from pathlib import Path

import pytest


pytestmark = pytest.mark.skipif(
    os.environ.get("BANANA_SPLIT_REAL_REPO_URL") is None,
    reason="BANANA_SPLIT_REAL_REPO_URL not set; real-repo integration test is disabled",
)


def _run_git(args, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        text=True,
        capture_output=True,
        check=True,
    )


def test_cli_on_real_repo(tmp_path):
    """
    Optional end-to-end test that exercises banana-split on a real repository.

    To enable it, set BANANA_SPLIT_REAL_REPO_URL to a git clone URL, e.g.:

        BANANA_SPLIT_REAL_REPO_URL=https://github.com/psf/requests.git \
        uv run pytest tests/test_real_repo_integration.py

    The test clones the repository into a temporary directory, runs
    banana-split on HEAD, and verifies that the resulting split branch
    has the same tree as the original commit.
    """

    repo_url = os.environ["BANANA_SPLIT_REAL_REPO_URL"]
    workdir = tmp_path / "repo"

    subprocess.run(
        ["git", "clone", "--depth", "50", repo_url, str(workdir)],
        text=True,
        capture_output=True,
        check=True,
    )

    # Ensure commits created by banana-split have an identity.
    _run_git(["config", "user.name", "banana-split"], cwd=workdir)
    _run_git(["config", "user.email", "banana-split@example.com"], cwd=workdir)

    orig_head = _run_git(["rev-parse", "HEAD"], cwd=workdir).stdout.strip()

    project_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(project_root)

    subprocess.run(
        [sys.executable, "-m", "banana_split.cli", orig_head],
        cwd=str(workdir),
        env=env,
        text=True,
        check=True,
    )

    split_branch = f"banana-split/split-{orig_head[:7]}"

    # The branch should exist and its tree should match the original.
    _run_git(["rev-parse", split_branch], cwd=workdir)
    _run_git(["diff", "--quiet", f"{orig_head}..{split_branch}"], cwd=workdir)

