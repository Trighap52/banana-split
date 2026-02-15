"""
Corpus-driven evaluation harness for banana-split.

This module benchmarks planner/apply quality across a set of real
repositories and commits.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, TextIO

from ..apply import apply_plan
from ..config import Config
from ..domain import DiffHunk, Plan
from ..planner import build_plan


@dataclass
class EvalCase:
    """
    One evaluation case in the corpus.
    """

    name: str
    repo_url: str
    target: str = "HEAD"
    branch: Optional[str] = None
    clone_depth: int = 200


def load_eval_corpus(corpus_path: str) -> List[EvalCase]:
    """
    Load and validate evaluation cases from a JSON corpus.

    Supported formats:
      - {"cases": [...]} object
      - [...] top-level list
    """

    raw = json.loads(Path(corpus_path).read_text())
    if isinstance(raw, dict):
        raw_cases = raw.get("cases")
    else:
        raw_cases = raw

    if not isinstance(raw_cases, list):
        raise ValueError("evaluation corpus must be a JSON list or an object with a 'cases' list")

    cases: List[EvalCase] = []
    for i, item in enumerate(raw_cases, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"case #{i} must be an object")

        repo_url = item.get("repo_url")
        if not isinstance(repo_url, str) or not repo_url.strip():
            raise ValueError(f"case #{i} requires non-empty string field 'repo_url'")

        name = item.get("name")
        if not isinstance(name, str) or not name.strip():
            name = f"case-{i}"

        target = item.get("target", "HEAD")
        if not isinstance(target, str) or not target.strip():
            raise ValueError(f"case #{i} field 'target' must be a non-empty string when provided")

        branch = item.get("branch")
        if branch is not None and (not isinstance(branch, str) or not branch.strip()):
            raise ValueError(f"case #{i} field 'branch' must be a non-empty string when provided")

        depth = item.get("clone_depth", 200)
        if not isinstance(depth, int) or depth <= 0:
            raise ValueError(f"case #{i} field 'clone_depth' must be a positive integer")

        cases.append(
            EvalCase(
                name=name.strip(),
                repo_url=repo_url.strip(),
                target=target.strip(),
                branch=branch.strip() if isinstance(branch, str) else None,
                clone_depth=depth,
            )
        )

    return cases


def run_evaluation(
    *,
    corpus_path: str,
    use_ai: bool,
    verbosity: int,
) -> Dict[str, Any]:
    """
    Execute all corpus cases and return a structured report.
    """

    cases = load_eval_corpus(corpus_path)
    case_reports: List[Dict[str, Any]] = []

    plan_build_failures = 0
    apply_failures = 0
    successful_cases = 0

    total_suggested_commits = 0
    total_hunks_in_suggested_commits = 0
    total_files_in_suggested_commits = 0
    single_file_commit_count = 0
    single_symbol_commit_count = 0
    total_semantic_cohesion_score = 0.0
    planned_case_count = 0

    for case in cases:
        case_report: Dict[str, Any] = {
            "name": case.name,
            "repo_url": case.repo_url,
            "target": case.target,
            "branch": case.branch,
        }

        try:
            with tempfile.TemporaryDirectory(prefix="banana-split-eval-") as tmpdir:
                repo_dir = Path(tmpdir) / "repo"
                _clone_repo(case, repo_dir)
                _configure_git_identity(repo_dir)

                with _pushd(repo_dir):
                    config = Config(
                        target=case.target,
                        use_staged=False,
                        dry_run=False,
                        use_ai=use_ai,
                        verbosity=verbosity,
                    )

                    plan = build_plan(config)
                    metrics = _plan_metrics(plan)
                    case_report["plan_metrics"] = metrics
                    planned_case_count += 1
                    total_suggested_commits += metrics["suggested_commit_count"]
                    total_hunks_in_suggested_commits += metrics["total_hunks_in_suggested_commits"]
                    total_files_in_suggested_commits += metrics["total_files_in_suggested_commits"]
                    single_file_commit_count += metrics["single_file_commit_count"]
                    single_symbol_commit_count += metrics["single_symbol_commit_count"]
                    total_semantic_cohesion_score += metrics["semantic_cohesion_score_sum"]

                    apply_plan(plan, config)

                case_report["status"] = "success"
                case_report["tree_equal"] = True
                successful_cases += 1
        except Exception as exc:  # noqa: BLE001
            error = str(exc)
            if "plan_metrics" in case_report:
                case_report["status"] = "apply_failed"
                apply_failures += 1
            else:
                case_report["status"] = "plan_build_failed"
                plan_build_failures += 1
            case_report["tree_equal"] = False
            case_report["error"] = error

        case_reports.append(case_report)

    apply_attempted_cases = len(cases) - plan_build_failures
    summary = {
        "total_cases": len(cases),
        "planned_case_count": planned_case_count,
        "plan_build_failures": plan_build_failures,
        "apply_attempted_cases": apply_attempted_cases,
        "apply_failures": apply_failures,
        "successful_cases": successful_cases,
        "tree_equal_success_rate": _ratio(successful_cases, apply_attempted_cases),
        "apply_failure_rate": _ratio(apply_failures, apply_attempted_cases),
        "avg_suggested_commits_per_planned_case": _ratio(
            total_suggested_commits,
            planned_case_count,
        ),
        "avg_hunks_per_suggested_commit": _ratio(
            total_hunks_in_suggested_commits,
            total_suggested_commits,
        ),
        "avg_files_per_suggested_commit": _ratio(
            total_files_in_suggested_commits,
            total_suggested_commits,
        ),
        "single_file_commit_ratio": _ratio(
            single_file_commit_count,
            total_suggested_commits,
        ),
        "single_symbol_commit_ratio": _ratio(
            single_symbol_commit_count,
            total_suggested_commits,
        ),
        "semantic_cohesion_score": _ratio(
            total_semantic_cohesion_score,
            total_suggested_commits,
        ),
    }

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "corpus_path": str(Path(corpus_path).resolve()),
        "config": {
            "use_ai": use_ai,
        },
        "summary": summary,
        "cases": case_reports,
    }


def write_evaluation_report(report: Dict[str, Any], output_path: str) -> None:
    """
    Persist a report as formatted JSON.
    """

    path = Path(output_path)
    if path.parent and not path.parent.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")


def print_evaluation_summary(report: Dict[str, Any], out: Optional[TextIO] = None) -> None:
    """
    Print a concise human-readable report summary.
    """

    stream = out or os.sys.stdout
    summary = report["summary"]
    lines = [
        f"Evaluation corpus: {report['corpus_path']}",
        f"Cases: {summary['total_cases']}",
        (
            "Status: "
            f"{summary['successful_cases']} success, "
            f"{summary['apply_failures']} apply failures, "
            f"{summary['plan_build_failures']} plan failures"
        ),
        f"Tree-equal success rate: {summary['tree_equal_success_rate']:.3f}",
        f"Apply failure rate: {summary['apply_failure_rate']:.3f}",
        (
            "Size: "
            f"{summary['avg_suggested_commits_per_planned_case']:.3f} commits/case, "
            f"{summary['avg_hunks_per_suggested_commit']:.3f} hunks/commit, "
            f"{summary['avg_files_per_suggested_commit']:.3f} files/commit"
        ),
        (
            "Cohesion: "
            f"{summary['single_file_commit_ratio']:.3f} single-file ratio, "
            f"{summary['single_symbol_commit_ratio']:.3f} single-symbol ratio, "
            f"{summary['semantic_cohesion_score']:.3f} score"
        ),
    ]
    stream.write("\n".join(lines) + "\n")


def _clone_repo(case: EvalCase, dest: Path) -> None:
    cmd = ["git", "clone", "--depth", str(case.clone_depth)]
    if case.branch:
        cmd.extend(["--branch", case.branch])
    cmd.extend([case.repo_url, str(dest)])
    _run_subprocess(cmd, cwd=None)


def _configure_git_identity(repo_dir: Path) -> None:
    _run_subprocess(["git", "config", "user.name", "banana-split-eval"], cwd=repo_dir)
    _run_subprocess(
        ["git", "config", "user.email", "banana-split-eval@example.com"],
        cwd=repo_dir,
    )


def _run_subprocess(cmd: List[str], cwd: Optional[Path]) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd is not None else None,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or "").strip() or (completed.stdout or "").strip()
        raise RuntimeError(f"command failed ({' '.join(cmd)}): {detail}")
    return completed


@contextmanager
def _pushd(path: Path) -> Iterator[None]:
    original = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(original)


def _ratio(numerator: float, denominator: float) -> float:
    if denominator == 0:
        return 0.0
    return float(numerator) / float(denominator)


def _plan_metrics(plan: Plan) -> Dict[str, Any]:
    hunk_map: Dict[str, DiffHunk] = {}
    for file in plan.diff.files:
        for hunk in file.hunks:
            hunk_map[hunk.id] = hunk

    suggested_count = len(plan.suggested_commits)
    total_hunks = 0
    total_files = 0
    single_file_commits = 0
    single_symbol_commits = 0
    cohesion_sum = 0.0

    for commit in plan.suggested_commits:
        hunks = [hunk_map[hid] for hid in commit.hunk_ids if hid in hunk_map]
        total_hunks += len(hunks)

        unique_files = {h.file_path for h in hunks}
        unique_symbols = {
            h.meta.get("symbol")
            for h in hunks
            if isinstance(h.meta.get("symbol"), str) and h.meta.get("symbol")
        }
        total_files += len(unique_files)

        if len(unique_files) <= 1:
            single_file_commits += 1
        if len(unique_symbols) <= 1:
            single_symbol_commits += 1

        cohesion = 0.0
        if len(unique_files) <= 1:
            cohesion += 0.5
        if len(unique_symbols) <= 1:
            cohesion += 0.5
        cohesion_sum += cohesion

    return {
        "suggested_commit_count": suggested_count,
        "total_hunks_in_suggested_commits": total_hunks,
        "total_files_in_suggested_commits": total_files,
        "single_file_commit_count": single_file_commits,
        "single_symbol_commit_count": single_symbol_commits,
        "semantic_cohesion_score_sum": cohesion_sum,
    }
