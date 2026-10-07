<img src="logo.svg" alt="banana-split logo" width="72">

# banana-split

[![CI](https://github.com/Trighap52/banana-split/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/Trighap52/banana-split/actions/workflows/ci.yml)
[![Eval](https://github.com/Trighap52/banana-split/actions/workflows/eval.yml/badge.svg?branch=main)](https://github.com/Trighap52/banana-split/actions/workflows/eval.yml)

banana-split analyzes a large commit in a git repository and proposes a
sequence of smaller, atomic commits that together reproduce the original
change **without modifying any lines of code**. It only replays the
original diff in smaller chunks as new commits.

The goal is to turn “oops, huge commit” into a clean, understandable
history while keeping the final tree exactly identical to the original
commit.

## Status

This is an early prototype, but already supports:

- Parsing Git diffs into structured files / hunks / lines while retaining
  original patch bodies, newline markers, paths, and file metadata.
- Grouping hunks into “atomic changes” per file and per symbol (function).
- AST-based Python symbol extraction with fallback to hunk-header symbols.
- Semantic atomization with lightweight dependency ordering (for example,
  source-before-test when signals match).
- Import-based source-to-test dependency linking for Python changes.
- Building a plan of suggested commits.
- Versioned plans with immutable commit/tree binding and validated import.
- Structural review: inspect patches, rename, merge, split, move units, and
  reorder commits when coverage and dependency constraints allow.
- Replaying the original commit as multiple commits on a new branch,
  verifying the final tree matches the original.
- Whole-file replay for additions, deletions, empty files, renames, and
  permission changes, including operations with text edits.
- Lossless replay of CRLF and non-UTF-8 text contents.
- Preflight safety checks for unsupported diff shapes before replay starts.

AI integration is stubbed out (the interface exists, but no real model
call yet).

The v1 delivery roadmap is tracked in [issue #23](https://github.com/Trighap52/banana-split/issues/23).

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

> Run from a clean repository. Split commits are built in an isolated temporary
> worktree, then published on a new branch after verification. Your current
> branch, index, and working files remain unchanged.

### Plan, review, then apply

From inside a Git repository:

```bash
uv run banana-split plan <commit-sha>
```

This analyzes one supported commit, displays its change units, and saves a
versioned JSON plan under the current worktree's managed Git metadata directory:
`<git-dir>/banana-split/plans/<full-sha>.json`. It prints the full plan path and
the commands to review and apply it. The default location keeps the repository
clean. Use `--output /tmp/split-plan.json` for a portable plan outside the repo,
or `--json` to print JSON without saving. Existing exports are preserved unless
you explicitly use `plan --overwrite`; review edits intentionally update their
input artifact. Commits with no changes cannot be exported as replayable plans.

Use the printed path as `PLAN` in these examples:

```bash
uv run banana-split review PLAN
uv run banana-split review PLAN --show 1
uv run banana-split review PLAN --rename 1 "Fix request parsing"
uv run banana-split review PLAN --merge 1 2
uv run banana-split review PLAN --move 'service.py::ac0' 2
uv run banana-split review PLAN --split 1 'service.py::ac0'
uv run banana-split review PLAN --order 2,1,3
uv run banana-split apply PLAN
```

Commit numbers are one-based. Unit IDs are printed by `plan` and `review`.
Each flag performs one edit; use separate invocations to make several edits.
Edits update the plan file atomically, or use `--output PATH` to save a copy.
Moving the last unit out of a commit removes that empty commit. Splitting
extracts one complete unit into a new commit immediately after its source.
Merge keeps the earlier commit's title and combines its bodies.

On a terminal, `review PLAN` provides the same actions as commands:
`show`, `rename`, `merge`, `move`, `split`, and `order`. Type `save` to write
approved edits or `quit` to discard them. Ctrl+C or EOF also discards unsaved
edits. Without a terminal, plain `review PLAN` only displays the plan.

Invalid edits are rejected without changing the plan. Every unit must appear
exactly once; per-file hunk order, file-operation boundaries, and inferred
source/test dependencies must remain valid. Dependent changes may share a
commit. These are static constraints, not proof that intermediate commits pass
tests; configurable per-commit checks are tracked in the next milestone.

Saved plans contain grouping and commit messages, not patch text. On import,
banana-split reconstructs changes from Git and verifies the immutable base,
target, target tree, original patch fingerprint, and unit definitions. Moving
`HEAD` after planning does not retarget a saved plan. Plans can be transferred
to a clone containing the same objects. Unavailable objects or altered or
incompatible definitions fail before replay. Regenerate a plan if its fingerprint or
unit definitions change after a tool upgrade or diff-configuration change.
Plan output cannot overwrite tracked source files or arbitrary Git metadata.
Custom plans inside the repository should be ignored by Git; apply still
requires a clean repository.

`apply PLAN` intentionally writes commits without prompting. It revalidates the
plan, replays in a detached temporary worktree, compares the exact final tree,
and publishes `banana-split/split-<short-sha>` only after cleanup. Your current
checkout, index, and working files remain unchanged. Existing output branches
are never overwritten. Replay failure or Ctrl+C cleans up without publishing a
branch; cleanup failures report the recovery path.

### Read-only inspection and dry runs

```bash
uv run banana-split <commit-sha>
uv run banana-split plan <commit-sha> --dry-run
uv run banana-split review PLAN --merge 1 2 --dry-run
uv run banana-split apply PLAN --dry-run
```

The bare command now inspects only. Dry runs never prompt or save a file or Git
ref. The legacy one-step workflow remains available explicitly:

```bash
uv run banana-split <commit-sha> --apply
```

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
- merge commits (commits with more than one parent),
- commits containing binary file changes, and
- submodule, symlink, or other non-regular-file changes, and
- overlapping paths across separate file operations (for example, replacing
  a directory with a file).

Use `--dry-run` to inspect these cases. Binary changes remain opaque and do
not produce replayable units.

Supported regular-file operations include additions/deletions (including empty
files), renames with or without edits, and executable permission changes. These
operations remain indivisible during planning and review. Ordinary text hunks
retain their exact bodies; replay adjusts their ranges for earlier split
commits. Git external diff tools, text conversion, color, and custom prefixes
are disabled when obtaining machine-readable patches.

## Evaluation harness

To benchmark split quality over multiple repositories/commits, run:

```bash
make eval EVAL_CORPUS=examples/eval_corpus.sample.json
```

For a faster smoke check against one case, use:

```bash
make eval-sample
```

The repository includes:

- `examples/eval_corpus.sample.json` for quick smoke tests.
- `examples/eval_corpus_v1.json` for a curated 20-case Python corpus
  focused on source/test dependency-sensitive commits.

Run the curated corpus with:

```bash
make eval EVAL_CORPUS=examples/eval_corpus_v1.json
```

This executes each corpus case in a fresh temporary clone and reports:

- end-to-end tree-equal success rate over all cases (including clone/planning failures),
- conditional tree-equal success rate over cases that reached apply,
- apply failure rate,
- average suggested commit size (commits/case, hunks/commit, files/commit),
- cohesion proxies (single-file ratio, single-symbol ratio, cohesion score),
- dependency-order satisfaction (source-before-test pairs satisfied).

Use `--eval-output <path>` to write the full JSON report and
`--eval-fail-on-case-failure` for CI-style non-zero exits when cases
fail.

By default `make eval` writes `artifacts/eval-report.json`. Override
with `EVAL_OUTPUT=<path>`.

Corpus entries support:

- `name` (optional display name),
- `repo_url` (clone URL),
- `target` (commit-ish, default `HEAD`),
- `branch` (optional branch for clone), and
- `clone_depth` (optional positive integer, default `200`).

The selected target and its parent are fetched separately at depth two, so
pinned commits remain usable after they leave the initial branch clone window.
Reports record the resolved target SHA. Commit expressions such as `HEAD~5`
must resolve within the initial clone; increase `clone_depth` when needed.

Curated corpus entries may also include descriptive metadata fields such
as `rationale`; unknown fields are ignored by the loader.

Validate corpus quality constraints with:

```bash
make validate-eval-corpus EVAL_CORPUS=examples/eval_corpus_v1.json
```

To enforce report quality gates locally (tree equality and dependency
ordering threshold):

```bash
uv run python scripts/check_eval_report.py artifacts/eval-report.json \
  --min-tree-equal 1.0 \
  --min-dependency-order 0.80
```

CI integration:

- `.github/workflows/eval.yml` runs the curated corpus benchmark on pull requests.
- It uploads `artifacts/eval-report.json` as a build artifact.
- It enforces hard gates:
  - `tree_equal_success_rate >= 1.0` over all corpus cases
  - `dependency_order_satisfaction >= 0.80`
- Gate output includes successful vs total cases and `satisfied_dependency_pairs`
  vs `expected_dependency_pairs`. It checks case results directly so older reports
  with inflated conditional rates cannot pass. A dependency gate requires
  non-zero evaluated pairs.

## Design overview

The main modules are:

- `banana_split.cli` – command-line entry point.
- `banana_split.domain` – core data structures for diffs and plans.
- `banana_split.git_adapter` – integration with git to obtain and apply diffs.
- `banana_split.diff_parser` – parse unified diffs into structured objects.
- `banana_split.analysis` – static heuristics and language-aware helpers.
- `banana_split.ai` – AI-assisted reasoning for commit boundaries.
- `banana_split.planner` – orchestrates analysis and plan construction.
- `banana_split.workflow` – explicit plan/review/apply commands.
- `banana_split.plan_store` – versioned manifests and authoritative Git rebuild.
- `banana_split.plan_editor` – transactional structural review edits.
- `banana_split.validation` – shared coverage/order/dependency invariants.
- `banana_split.review` – human-readable plan summaries and legacy review.
- `banana_split.apply` – applies a plan as actual git commits or a dry run.
- `banana_split.eval` – corpus-driven benchmarking and quality metrics.

Key ideas:

- Diff parsing is separate from git calls, so you can test on raw diff
  strings.
- Heuristics group hunks by symbol and apply lightweight dependency
  ordering before any AI involvement.
- A `Plan` object describes the mapping from hunks to suggested commits
  and is validated to ensure:
  - every hunk appears in exactly one commit, and
  - per-file hunk order is preserved.
- The planner preserves suggested commit order so semantic sequencing
  (for example source-before-test) is retained when valid.
- Applying a plan:
  - revalidates the reviewed plan,
  - replays partial patches using `git apply --index` in a detached worktree,
  - compares the final tree object ID with the original commit, and
  - removes the worktree before publishing the output branch.

## Development

Run the test suite with:

```bash
uv run pytest
```

or:

```bash
make test
```

There is also an optional “real repo” integration test. To run it:

```bash
BANANA_SPLIT_REAL_REPO_URL=https://github.com/psf/requests.git \
uv run pytest tests/test_real_repo_integration.py
```

This will clone the specified repository into a temporary directory and
run banana-split against its `HEAD` commit.

## Open source

- License: `MIT` (see `LICENSE`)
- Contributing guide: `CONTRIBUTING.md`
- Code of conduct: `CODE_OF_CONDUCT.md`
- Security policy: `SECURITY.md`
- Support guide: `SUPPORT.md`
- Changelog: `CHANGELOG.md`
