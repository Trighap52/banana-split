# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog, and this project follows Semantic
Versioning when stable releases begin.

## [Unreleased]

### Added

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
