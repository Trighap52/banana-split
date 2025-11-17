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

