# v1 delivery roadmap

Tracking epic: [#23](https://github.com/Trighap52/banana-split/issues/23).

## Product contract

Split one existing, non-merge commit into a reviewed sequence of commits on a
new branch. The output must reproduce the exact target tree, including file
contents, names and modes. The caller's current branch, index and working files
must remain unchanged. Unsupported inputs must fail before replay starts.

A useful split groups one logical change with its implementation, callers and
regression tests. Smaller file/symbol groups are candidate units, not proof of
atomicity. Prefer fewer coherent commits when the relationships are uncertain.
Intermediate commits are only described as validated when a configured check
has passed for each one.

## Ordered milestones

| Priority | Milestone | Acceptance gate |
| --- | --- | --- |
| P0 | [#24 Isolated execution](https://github.com/Trighap52/banana-split/issues/24) | Success, failure and cancellation preserve caller HEAD, index bytes and working files; publish only verified history; visible CLI output |
| P0 | [#25 Faithful replay](https://github.com/Trighap52/banana-split/issues/25) | Supported operations preserve bytes and metadata; exact tree IDs match; unsupported shapes fail before mutation |
| P1 | [#26 Explicit workflow and review](https://github.com/Trighap52/banana-split/issues/26) | Inspect/export/edit a plan bound to immutable base/target IDs; explicitly apply it; validate every edit and again before replay |
| P1 | [#27 Coherent planning](https://github.com/Trighap52/banana-split/issues/27) | Independently labeled cross-file fixtures produce coherent groups and useful titles; optional per-commit validation works |
| P1 | [#28 Honest evaluation](https://github.com/Trighap52/banana-split/issues/28) | All-case success and caller preservation are gated independently; deterministic offline fixtures provide the baseline |
| P2 | [#29 Release readiness](https://github.com/Trighap52/banana-split/issues/29) | Supported runtimes pass CI; wheel/sdist install cleanly; documented CLI workflow works from a fresh installation |

Ship each milestone through focused PRs. Test failure paths with real Git
repositories, not only mocked adapter functions. Add regressions alongside the
behavior they protect. Keep real-repository benchmarks supplemental to the
repeatable offline suite.

## Initial supported scope

- One existing commit with exactly one parent.
- Ordinary text modifications with Python-aware grouping and conservative
  fallback for other languages.
- Common file operations only after faithful replay is implemented. Initially
  keep additions, deletions, renames and mode changes indivisible.
- Inspectable plans and user correction of groups/titles before application.
- Optional user-provided checks for each intermediate commit in isolation.

Staged application, commit ranges, merge/root commits, broad language
intelligence and AI grouping are deferred. Binary and submodule changes should
be explicitly rejected until they have a tested replay contract. The current AI
CLI flag is a stub and must be removed or clearly identified before v1.

## Release gates

1. All supported local fixtures reproduce the exact target tree object ID.
2. Success, replay failure and cancellation preserve the caller's state.
3. Unsupported shapes are identified before creating replay state.
4. Edited plans assign every supported unit exactly once and respect required
   ordering/dependencies; invalid plans never apply.
5. Evaluation reports count planning failures in end-to-end success and expose
   zero-evidence quality metrics rather than presenting them as evidence.
6. A fresh package installation completes the documented inspect/review/apply
   workflow on every supported runtime/platform.

## Known limitations to resolve

The existing parser drops newline markers and file metadata. Local inspection
also reproduced ordinary file-addition failures and deletions rendered as empty
files. These belong to #25. A final tree check can catch replay defects, but the
v1 support matrix must reject unsupported inputs earlier.

SIGKILL and power loss cannot run Python cleanup. Document recovery for orphaned
temporary worktrees. Respect user hooks and report their failures; do not claim
intermediate correctness solely from final-tree equality.

## Backlog reset

The previous v0.3 epic and issues #1–#11 were closed as superseded. Existing
implementation and discussion remain available. Dependency PRs #21 and #22
were closed during the reset; reassess their changes in #29, including Python
compatibility, rather than treating their closure as a decision to ignore
maintenance.
