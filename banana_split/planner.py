"""
High-level orchestration for banana-split.

The planner is responsible for:
  - obtaining a diff from git,
  - parsing it into domain objects,
  - grouping hunks into atomic changes,
  - optionally invoking AI to propose commit groupings, and
  - validating and returning a complete plan.
"""

from __future__ import annotations

import logging

from .config import Config
from .domain import Plan
from .analysis.heuristics import group_hunks
from .ai.openai_client import OpenAIClient
from .diff_parser import parse_unified_diff
from .errors import PlanValidationError
from .git_adapter import GitDiffResult, get_diff_for_commit, get_diff_for_staged
from .preflight import validate_runtime_support
from .review import review_plan
from .apply import apply_plan

LOG = logging.getLogger(__name__)


def build_plan(config: Config) -> Plan:
    """
    Build an initial split plan for the requested target.

    For now this function uses minimal logic and will be expanded as the
    rest of the system is implemented.
    """

    git_diff = _obtain_git_diff(config)
    diff = parse_unified_diff(git_diff.raw_diff)
    diff.base_commit = git_diff.base_commit
    diff.target_commit = git_diff.target_commit
    validate_runtime_support(config, git_diff, diff)

    atomic_changes = group_hunks(diff)

    if config.use_ai:
        ai_client = OpenAIClient()
        suggested_commits = ai_client.propose_commits(atomic_changes)
    else:
        # Simple default: one commit per atomic change.
        from .domain import SuggestedCommit  # local import to avoid cycles

        suggested_commits = [
            SuggestedCommit(
                id=change.id,
                title="Atomic change",
                body=None,
                atomic_change_ids=[change.id],
                hunk_ids=list(change.hunk_ids),
                estimated_risk=None,
            )
            for change in atomic_changes
        ]

    plan = Plan(
        diff=diff,
        atomic_changes=atomic_changes,
        suggested_commits=suggested_commits,
        invariants_checked=False,
    )

    _validate_and_order_plan(plan)
    plan.invariants_checked = True
    return plan


def _obtain_git_diff(config: Config) -> GitDiffResult:
    """
    Obtain a unified diff string based on the CLI configuration.
    """

    if config.use_staged:
        LOG.info("Using staged changes as diff source")
        return get_diff_for_staged()

    target = config.target or "HEAD"
    LOG.info("Using commit %s as diff source", target)
    return get_diff_for_commit(target)


def _validate_and_order_plan(plan: Plan) -> None:
    """
    Validate core invariants and ensure commits follow diff hunk order.

    Invariants:
      - every hunk in the diff appears in exactly one suggested commit;
      - no suggested commit references unknown hunks;
      - for each file, the sequence of hunks across commits preserves
        the original per-file order.
    """

    diff = plan.diff
    suggested_commits = plan.suggested_commits

    # Map each hunk id to its file path and a global order index.
    hunk_order: dict[str, int] = {}
    hunk_file: dict[str, str] = {}
    all_hunk_ids: list[str] = []
    order_counter = 0

    for file in diff.files:
        path = file.path_new or file.path_old or ""
        for hunk in file.hunks:
            all_hunk_ids.append(hunk.id)
            hunk_order[hunk.id] = order_counter
            hunk_file[hunk.id] = path
            order_counter += 1

    # Ensure all referenced hunks exist and that coverage is exact.
    assigned_ids: list[str] = []
    for commit in suggested_commits:
        for hid in commit.hunk_ids:
            if hid not in hunk_order:
                raise PlanValidationError(f"plan references unknown hunk id {hid}")
            assigned_ids.append(hid)

    if set(assigned_ids) != set(all_hunk_ids):
        missing = set(all_hunk_ids) - set(assigned_ids)
        extra = set(assigned_ids) - set(all_hunk_ids)
        raise PlanValidationError(
            f"plan does not cover hunks exactly once (missing={missing}, extra={extra})"
        )

    if len(assigned_ids) != len(set(assigned_ids)):
        raise PlanValidationError("plan assigns at least one hunk to multiple commits")

    # Order commits by the earliest hunk they contain to respect diff order.
    plan.suggested_commits = sorted(
        suggested_commits,
        key=lambda c: min(hunk_order[hid] for hid in c.hunk_ids),
    )

    # Verify per-file order is preserved across commits.
    for file in diff.files:
        path = file.path_new or file.path_old or ""
        file_hunk_ids = [h.id for h in file.hunks]
        if not file_hunk_ids:
            continue

        sequence: list[int] = []
        for commit in plan.suggested_commits:
            for hid in commit.hunk_ids:
                if hunk_file.get(hid) == path:
                    sequence.append(hunk_order[hid])

        expected = [hunk_order[hid] for hid in file_hunk_ids]
        if sequence != expected:
            raise PlanValidationError(
                f"plan reorders hunks for file {path}; expected {expected}, got {sequence}"
            )


def run_split(config: Config) -> None:
    """
    Entry point for the main CLI command.

    Builds a plan, offers the user a chance to review it, and then
    either applies it as actual commits or prints a dry-run summary.
    """

    LOG.debug("Starting banana-split with config: %s", config)

    plan = build_plan(config)
    reviewed_plan = review_plan(plan)

    apply_plan(reviewed_plan, config)
