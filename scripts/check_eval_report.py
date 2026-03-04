#!/usr/bin/env python3
"""
Validate evaluation report thresholds and print actionable failures.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _as_float(value: Any, field: str) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    raise ValueError(f"report summary field '{field}' must be numeric, got {type(value).__name__}")


def _as_int(value: Any, field: str) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    raise ValueError(f"report summary field '{field}' must be an integer, got {type(value).__name__}")


def _collect_failing_cases(report: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    cases = report.get("cases", [])
    if not isinstance(cases, list):
        return failures

    for case in cases:
        if not isinstance(case, dict):
            continue
        if case.get("tree_equal") is True:
            continue

        name = str(case.get("name", "<unnamed-case>"))
        status = str(case.get("status", "unknown"))
        error = case.get("error")
        if isinstance(error, str) and error.strip():
            failures.append(f"{name} ({status}): {error.strip()}")
        else:
            failures.append(f"{name} ({status})")

    return failures


def _load_report(path: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text())
    if not isinstance(raw, dict):
        raise ValueError("report must be a JSON object")
    return raw


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Enforce evaluation report quality gates."
    )
    parser.add_argument(
        "report",
        nargs="?",
        default="artifacts/eval-report.json",
        help="Path to report JSON (default: artifacts/eval-report.json)",
    )
    parser.add_argument(
        "--min-tree-equal",
        type=float,
        default=1.0,
        help="Minimum tree_equal_success_rate required (default: 1.0)",
    )
    parser.add_argument(
        "--min-dependency-order",
        type=float,
        default=None,
        help=(
            "Optional minimum dependency_order_satisfaction required. "
            "When omitted, this gate is disabled."
        ),
    )
    args = parser.parse_args()

    report_path = Path(args.report).resolve()
    if not report_path.exists():
        raise SystemExit(f"report does not exist: {report_path}")

    try:
        report = _load_report(report_path)
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(f"invalid report JSON: {exc}") from exc

    summary = report.get("summary")
    if not isinstance(summary, dict):
        raise SystemExit("report is missing 'summary' object")

    try:
        tree_equal = _as_float(summary.get("tree_equal_success_rate"), "tree_equal_success_rate")
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(str(exc)) from exc

    dependency_order: float | None = None
    if "dependency_order_satisfaction" in summary:
        try:
            dependency_order = _as_float(
                summary.get("dependency_order_satisfaction"),
                "dependency_order_satisfaction",
            )
        except Exception as exc:  # noqa: BLE001
            raise SystemExit(str(exc)) from exc

    expected_pairs: int | None = None
    satisfied_pairs: int | None = None
    if "expected_dependency_pairs" in summary:
        try:
            expected_pairs = _as_int(summary.get("expected_dependency_pairs"), "expected_dependency_pairs")
        except Exception as exc:  # noqa: BLE001
            raise SystemExit(str(exc)) from exc
    if "satisfied_dependency_pairs" in summary:
        try:
            satisfied_pairs = _as_int(
                summary.get("satisfied_dependency_pairs"),
                "satisfied_dependency_pairs",
            )
        except Exception as exc:  # noqa: BLE001
            raise SystemExit(str(exc)) from exc

    print(f"Eval report: {report_path}")
    print(f"tree_equal_success_rate={tree_equal:.3f} (required >= {args.min_tree_equal:.3f})")
    if expected_pairs is not None and satisfied_pairs is not None:
        print(f"dependency_pairs={satisfied_pairs}/{expected_pairs}")
    if args.min_dependency_order is not None:
        if dependency_order is None:
            raise SystemExit(
                "report summary does not include dependency_order_satisfaction "
                "but --min-dependency-order was requested"
            )
        print(
            "dependency_order_satisfaction="
            f"{dependency_order:.3f} (required >= {args.min_dependency_order:.3f})"
        )
    elif dependency_order is not None:
        print(f"dependency_order_satisfaction={dependency_order:.3f}")

    failures: list[str] = []

    if tree_equal < args.min_tree_equal:
        failures.append(
            "tree_equal_success_rate below threshold "
            f"({tree_equal:.3f} < {args.min_tree_equal:.3f})"
        )
        case_failures = _collect_failing_cases(report)
        if case_failures:
            print("Failing cases:")
            for detail in case_failures:
                print(f"- {detail}")

    if args.min_dependency_order is not None and dependency_order is not None:
        if dependency_order < args.min_dependency_order:
            failures.append(
                "dependency_order_satisfaction below threshold "
                f"({dependency_order:.3f} < {args.min_dependency_order:.3f})"
            )

    if failures:
        print("Quality gates failed:")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print("Quality gates passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
