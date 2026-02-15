"""
Command-line interface for banana-split.

This module is responsible for argument parsing and delegating to the
high-level orchestration in the planner module.
"""

from __future__ import annotations

import argparse
import sys
from typing import List, Optional

from .config import Config
from .eval.harness import (
    print_evaluation_summary,
    run_evaluation,
    write_evaluation_report,
)
from .logging_utils import configure_logging
from .planner import run_split


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="banana-split",
        description=(
            "Analyze a large git commit and propose a sequence of smaller, "
            "atomic commits without changing code contents."
        ),
    )

    parser.add_argument(
        "target",
        nargs="?",
        help="Commit-ish or range to split (default: HEAD).",
    )
    parser.add_argument(
        "--staged",
        action="store_true",
        help="Use staged changes instead of a specific commit.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the proposed split plan without writing any commits.",
    )
    parser.add_argument(
        "--ai",
        dest="use_ai",
        action="store_true",
        help="Enable AI-assisted reasoning when proposing commit boundaries.",
    )
    parser.add_argument(
        "--no-ai",
        dest="use_ai",
        action="store_false",
        help="Disable AI-assisted reasoning (heuristics only).",
    )
    parser.set_defaults(use_ai=False)

    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="Increase verbosity (can be specified multiple times).",
    )
    parser.add_argument(
        "--eval-corpus",
        help=(
            "Run benchmark evaluation using a JSON corpus file instead of "
            "splitting a single commit."
        ),
    )
    parser.add_argument(
        "--eval-output",
        help="Write evaluation report JSON to this path.",
    )
    parser.add_argument(
        "--eval-fail-on-case-failure",
        action="store_true",
        help="Return a non-zero exit code if any evaluation case fails.",
    )

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    config = Config(
        target=args.target,
        use_staged=args.staged,
        dry_run=args.dry_run,
        use_ai=args.use_ai,
        verbosity=args.verbose,
    )

    configure_logging(verbosity=config.verbosity)

    try:
        if args.eval_corpus:
            if args.target:
                parser.error("--eval-corpus cannot be combined with a target argument")
            if args.staged:
                parser.error("--eval-corpus cannot be combined with --staged")

            report = run_evaluation(
                corpus_path=args.eval_corpus,
                use_ai=config.use_ai,
                verbosity=config.verbosity,
            )
            print_evaluation_summary(report)

            if args.eval_output:
                write_evaluation_report(report, args.eval_output)

            summary = report["summary"]
            if args.eval_fail_on_case_failure and (
                summary["successful_cases"] != summary["total_cases"]
            ):
                return 2
            return 0

        run_split(config)
    except KeyboardInterrupt:
        # Graceful shutdown on Ctrl+C
        return 130
    except Exception as exc:  # noqa: BLE001
        # In early scaffolding, keep error handling simple and explicit.
        # Later, this will be narrowed to custom error types.
        print(f"banana-split: error: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":  # pragma: no cover - manual invocation
    raise SystemExit(main())
