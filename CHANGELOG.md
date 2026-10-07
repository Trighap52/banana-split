# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog, and this project follows Semantic
Versioning when stable releases begin.

## [Unreleased]

### Added

- Explicit plan/review/apply commands with versioned JSON grouping manifests,
  immutable Git object binding, patch fingerprints, and authoritative import.
- Structural review actions for patch inspection, renaming, merging, splitting,
  moving units and valid reordering, with atomic saves and cancellation.
- Shared validation of exact coverage, inferred dependencies and commit messages
  before edits are saved or plans are applied.
- Managed plan storage inside Git metadata, with protections against overwriting
  tracked source files and unrelated Git metadata.

- Evaluation harness with corpus-driven metrics.
- Semantic atomizer with lightweight dependency ordering.
- Open source project community and governance baseline files.
- Curated `examples/eval_corpus_v1.json` with 20 dependency-sensitive Python commits.
- `scripts/validate_eval_corpus.py` to validate corpus quality constraints.
- `Makefile` targets for local benchmark runs (`make eval`) and corpus validation.
- GitHub Actions eval workflow with report artifact upload, tree-equality gate,
  and dependency-order threshold gate (`>= 0.80`).
- `scripts/check_eval_report.py` for enforcing eval quality thresholds and
  reporting satisfied vs expected dependency pairs.
- AST-based Python symbol extraction for hunks, including methods, nested
  scopes, and decorator-aware line mapping with safe fallback behavior.
- GitHub Actions status badges (`CI`, `Eval`) in README.
- Import-based Python source-to-test dependency linking integrated into
  semantic ordering, including support for direct imports, from-imports,
  aliased imports, and package paths.

### Fixed

- Preserve exact patch bodies, CRLF, non-UTF-8 contents, missing-final-newline
  markers, quoted paths, and file-operation metadata during replay.
- Replay additions, deletions, empty files, renames, and permission changes
  as indivisible units, including operations with text edits.
- Adjust later hunk ranges to account for previously applied split commits.
- Reject merge, binary, submodule, and symlink changes before replay, and
  compute root-commit previews against the empty tree.
- Obtain machine-readable Git patches independently of local diff display
  settings, external diff tools, and text conversion.

- Fetch pinned evaluation targets and their parents independently of the initial
  branch clone depth, and record resolved commit IDs in reports.
- Count clone/planning failures in tree-equality success rates and validate case
  results directly in the report gate; reject non-finite metrics and missing
  dependency evidence.

### Changed

- The bare CLI command is now read-only. Use `apply PLAN` or the legacy explicit
  `--apply` flag to create commits.
