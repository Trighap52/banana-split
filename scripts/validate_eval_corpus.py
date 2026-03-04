#!/usr/bin/env python3
"""
Validate an evaluation corpus against v1 quality constraints.

Checks:
- at least 20 cases,
- each case has repo_url, branch, target, rationale,
- at least 70% of cases change both source and test Python files,
- at least 5 cases have test-first source/test diff order,
- each target commit exists in the declared repository branch.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tempfile
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class CaseMetrics:
    name: str
    source_test_python: bool
    test_first: bool


def _run_git(args: list[str], *, cwd: Path) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        stderr = proc.stderr.strip()
        raise RuntimeError(f"git {' '.join(args)} failed: {stderr}")
    return proc.stdout


def _is_python(path: str) -> bool:
    return path.lower().endswith(".py")


def _is_test_path(path: str) -> bool:
    lower = path.lower()
    base = lower.split("/")[-1]
    return (
        "/tests/" in f"/{lower}/"
        or lower.startswith("tests/")
        or (base.startswith("test_") and base.endswith(".py"))
        or base.endswith("_test.py")
    )


def _load_cases(corpus_path: Path) -> list[dict[str, Any]]:
    raw = json.loads(corpus_path.read_text())
    if isinstance(raw, dict):
        cases = raw.get("cases")
    else:
        cases = raw

    if not isinstance(cases, list):
        raise ValueError("corpus must be a JSON list or an object with a 'cases' list")
    return cases


def _validate_case_schema(case: dict[str, Any], index: int) -> None:
    required = ["name", "repo_url", "branch", "target", "rationale"]
    for key in required:
        value = case.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"case #{index} missing required string field '{key}'")

    clone_depth = case.get("clone_depth", 200)
    if not isinstance(clone_depth, int) or clone_depth <= 0:
        raise ValueError(f"case #{index} field 'clone_depth' must be a positive integer")


def _clone_repos(cases: list[dict[str, Any]], workspace: Path) -> dict[tuple[str, str], Path]:
    grouped: dict[tuple[str, str], int] = defaultdict(int)
    for case in cases:
        key = (case["repo_url"].strip(), case["branch"].strip())
        depth = int(case.get("clone_depth", 200))
        grouped[key] = max(grouped[key], depth)

    repos: dict[tuple[str, str], Path] = {}
    for idx, ((repo_url, branch), depth) in enumerate(grouped.items(), start=1):
        repo_name = repo_url.rstrip("/").split("/")[-1]
        if repo_name.endswith(".git"):
            repo_name = repo_name[:-4]
        target_dir = workspace / f"{idx:02d}-{repo_name}-{branch.replace('/', '_')}"
        _run_git(
            [
                "clone",
                "--filter=blob:none",
                "--depth",
                str(depth),
                "--branch",
                branch,
                repo_url,
                str(target_dir),
            ],
            cwd=workspace,
        )
        repos[(repo_url, branch)] = target_dir
    return repos


def _case_metrics(case: dict[str, Any], repo_dir: Path) -> CaseMetrics:
    target = case["target"].strip()
    _run_git(["cat-file", "-e", f"{target}^{{commit}}"], cwd=repo_dir)

    files_output = _run_git(["show", "--name-only", "--pretty=format:", target], cwd=repo_dir)
    files = [line.strip() for line in files_output.splitlines() if line.strip()]

    py_files = [path for path in files if _is_python(path)]
    test_py = [path for path in py_files if _is_test_path(path)]
    src_py = [path for path in py_files if not _is_test_path(path)]

    has_source_test = bool(test_py and src_py)
    test_first = False
    if has_source_test:
        first_test_index = min(files.index(path) for path in test_py)
        first_src_index = min(files.index(path) for path in src_py)
        test_first = first_test_index < first_src_index

    return CaseMetrics(
        name=case["name"].strip(),
        source_test_python=has_source_test,
        test_first=test_first,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate eval corpus quality constraints.")
    parser.add_argument(
        "corpus",
        nargs="?",
        default="examples/eval_corpus_v1.json",
        help="Path to corpus JSON (default: examples/eval_corpus_v1.json)",
    )
    parser.add_argument("--min-cases", type=int, default=20)
    parser.add_argument("--min-source-test-ratio", type=float, default=0.70)
    parser.add_argument("--min-test-first-cases", type=int, default=5)
    args = parser.parse_args()

    if shutil.which("git") is None:
        raise SystemExit("git is required")

    corpus_path = Path(args.corpus).resolve()
    if not corpus_path.exists():
        raise SystemExit(f"corpus does not exist: {corpus_path}")

    try:
        cases = _load_cases(corpus_path)
        for i, case in enumerate(cases, start=1):
            if not isinstance(case, dict):
                raise ValueError(f"case #{i} must be a JSON object")
            _validate_case_schema(case, i)
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(f"schema validation failed: {exc}") from exc

    if len(cases) < args.min_cases:
        raise SystemExit(f"expected at least {args.min_cases} cases, found {len(cases)}")

    with tempfile.TemporaryDirectory(prefix="banana-split-corpus-validate-") as tmpdir:
        tmp_path = Path(tmpdir)
        try:
            repos = _clone_repos(cases, tmp_path)
        except Exception as exc:  # noqa: BLE001
            raise SystemExit(f"repository clone failed: {exc}") from exc

        metrics: list[CaseMetrics] = []
        for case in cases:
            key = (case["repo_url"].strip(), case["branch"].strip())
            try:
                case_result = _case_metrics(case, repos[key])
            except Exception as exc:  # noqa: BLE001
                raise SystemExit(f"case '{case['name']}' validation failed: {exc}") from exc
            metrics.append(case_result)

    source_test_count = sum(1 for metric in metrics if metric.source_test_python)
    test_first_count = sum(1 for metric in metrics if metric.test_first)
    source_test_ratio = source_test_count / len(metrics)

    print(f"Corpus: {corpus_path}")
    print(f"Cases: {len(metrics)}")
    print(f"Source+test Python cases: {source_test_count}/{len(metrics)} ({source_test_ratio:.3f})")
    print(f"Test-first cases: {test_first_count}")

    failures: list[str] = []
    if source_test_ratio < args.min_source_test_ratio:
        failures.append(
            "source+test ratio too low "
            f"({source_test_ratio:.3f} < {args.min_source_test_ratio:.3f})"
        )
    if test_first_count < args.min_test_first_cases:
        failures.append(
            f"test-first case count too low ({test_first_count} < {args.min_test_first_cases})"
        )

    if failures:
        print("Validation failed:")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print("Validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
