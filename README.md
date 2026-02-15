<img src="logo.svg" alt="banana-split logo" width="72">

# banana-split

banana-split analyzes a large commit in a git repository and proposes a
sequence of smaller, atomic commits that together reproduce the original
change **without modifying any lines of code**. It only replays the
original diff in smaller chunks as new commits.

The goal is to turn “oops, huge commit” into a clean, understandable
history while keeping the final tree exactly identical to the original
commit.

## Status

This is an early prototype, but already supports:

- Parsing git diffs into structured files / hunks / lines.
- Grouping hunks into “atomic changes” per file and per symbol (function).
- Building a plan of suggested commits.
- Simple interactive review (rename commit titles).
- Replaying the original commit as multiple commits on a new branch,
  verifying the final tree matches the original.
- Preflight safety checks for unsupported diff shapes before mutating
  history.

AI integration is stubbed out (the interface exists, but no real model
call yet).

## Installation

banana-split is managed via [`uv`](https://github.com/astral-sh/uv).

Clone this repository, then from the project root:

```bash
uv sync
```

This will create a virtual environment and install development
dependencies (such as `pytest`).

To run the CLI without installing it globally:

```bash
uv run banana-split --help
```

You can also install it in editable mode with plain pip if you prefer:

```bash
pip install -e .
banana-split --help
```

## Basic usage

> Always run banana-split on a branch you are comfortable rewriting.
> The tool itself creates a new branch for the split commits, but it is
> good practice to work on throwaway branches while experimenting.

### Split a specific commit

From inside a git repository:

```bash
uv run banana-split <commit-sha>
```

banana-split will:

- Inspect the diff between `<commit-sha>` and its parent.
- Propose a series of smaller commits.
- Ask if you want to rename commit titles.
- Create a new branch called:
  - `banana-split/split-<short-sha>`
- Replay the original diff as multiple commits on that branch.
- Verify that the final tree matches `<commit-sha>` exactly.

Your original branch and commit remain unchanged.

### Dry-run (no git changes)

To see what banana-split would do without touching history:

```bash
uv run banana-split <commit-sha> --dry-run -v
```

This prints a summary of the proposed commits and their hunks instead of
creating any branches or commits.

### Split staged changes (experimental)

You can also run banana-split on staged changes:

```bash
uv run banana-split --staged --dry-run
```

In this mode, banana-split uses the diff between `HEAD` and the index.
Applying splits back to the repo is not supported yet for staged
changes; banana-split will require `--dry-run` in this mode.

### Current non-dry-run limits

When creating split commits, banana-split currently rejects:

- root commits (commits without a parent),
- commits containing binary file changes,
- rename-only changes (file moved/renamed without text hunks), and
- mode-only changes (permission bit updates without text hunks).

Use `--dry-run` to inspect plans for these cases.

## Design overview

The main modules are:

- `banana_split.cli` – command-line entry point.
- `banana_split.domain` – core data structures for diffs and plans.
- `banana_split.git_adapter` – integration with git to obtain and apply diffs.
- `banana_split.diff_parser` – parse unified diffs into structured objects.
- `banana_split.analysis` – static heuristics and language-aware helpers.
- `banana_split.ai` – AI-assisted reasoning for commit boundaries.
- `banana_split.planner` – orchestrates analysis and plan construction.
- `banana_split.review` – user-facing review and editing of plans.
- `banana_split.apply` – applies a plan as actual git commits or a dry run.

Key ideas:

- Diff parsing is separate from git calls, so you can test on raw diff
  strings.
- Heuristics group hunks by file and by symbol (e.g., one commit per
  function) before any AI involvement.
- A `Plan` object describes the mapping from hunks to suggested commits
  and is validated to ensure:
  - every hunk appears in exactly one commit, and
  - per-file hunk order is preserved.
- Applying a plan:
  - creates a new branch from the base commit,
  - replays partial patches using `git apply --cached`, and
  - checks the final tree against the original commit.

## Development

Run the test suite with:

```bash
uv run pytest
```

There is also an optional “real repo” integration test. To run it:

```bash
BANANA_SPLIT_REAL_REPO_URL=https://github.com/psf/requests.git \
uv run pytest tests/test_real_repo_integration.py
```

This will clone the specified repository into a temporary directory and
run banana-split against its `HEAD` commit.
