"""
Application of a banana-split plan to a git repository.

This module is responsible for turning a validated plan into either
real git commits or a dry-run description.
"""

from __future__ import annotations

import logging

from .config import Config
from .diff_parser import render_partial_diff
from .domain import Plan
from .errors import GitError
from .git_adapter import (
    apply_patch,
    create_branch,
    create_commit,
    delete_branch,
    checkout,
    ensure_repo_clean,
    get_current_ref,
    trees_equal,
)

LOG = logging.getLogger(__name__)


def apply_plan(plan: Plan, config: Config) -> None:
    """
    Apply the given plan according to the configuration.

    In dry-run mode this prints a summary only. In non-dry-run mode it
    creates a new branch starting from the diff's base commit and
    applies each suggested commit as a partial patch, ensuring that the
    final tree matches the original target commit.
    """

    if config.dry_run:
        LOG.info("Dry run: would apply %d commits", len(plan.suggested_commits))
        for commit in plan.suggested_commits:
            LOG.info(
                "  Commit %s: %s (%d hunks)",
                commit.id,
                commit.title,
                len(commit.hunk_ids),
            )
        return

    base = plan.diff.base_commit
    target = plan.diff.target_commit

    if not base or not target:
        raise GitError(
            "cannot apply plan without both base and target commits; "
            "this mode currently supports only splitting real commits"
        )

    ensure_repo_clean()
    original_ref = get_current_ref()

    branch_name = f"banana-split/split-{target[:7]}"
    LOG.info(
        "Creating new branch %s starting at base commit %s", branch_name, base
    )

    branch_created = False
    branch_checked_out = False
    try:
        # Create and check out the work branch. If the branch already
        # exists, this will raise and surface an error to the user so they
        # can clean it up or choose a different target.
        create_branch(branch_name, base)
        branch_created = True
        checkout(branch_name)
        branch_checked_out = True

        for suggested in plan.suggested_commits:
            if not suggested.hunk_ids:
                continue

            LOG.info("Applying suggested commit %s: %s", suggested.id, suggested.title)
            patch = render_partial_diff(plan.diff, suggested.hunk_ids)
            if not patch.strip():
                LOG.warning("Generated empty patch for commit %s; skipping", suggested.id)
                continue

            # Apply patch to the index only; the working tree will be
            # synchronized with HEAD when the operation completes.
            apply_patch(patch, index_only=True)

            message = suggested.title
            if suggested.body:
                message = f"{suggested.title}\n\n{suggested.body}"
            create_commit(message)

        # Verify that the final tree matches the original target commit.
        if not trees_equal(target, "HEAD"):
            raise GitError(
                "final tree does not match original commit after applying plan; "
                "this indicates a bug in patch generation"
            )
    except Exception:
        _rollback_partial_apply(
            original_ref=original_ref,
            branch_name=branch_name,
            branch_created=branch_created,
            branch_checked_out=branch_checked_out,
        )
        raise

    LOG.info(
        "Successfully applied plan on branch %s; final tree matches original commit %s",
        branch_name,
        target,
    )


def _rollback_partial_apply(
    *,
    original_ref: str,
    branch_name: str,
    branch_created: bool,
    branch_checked_out: bool,
) -> None:
    """
    Best-effort rollback when apply_plan fails mid-flight.
    """

    if branch_checked_out:
        try:
            checkout(original_ref)
        except GitError as exc:
            LOG.error(
                "Failed to return to original ref %s during rollback: %s",
                original_ref,
                exc,
            )

    if branch_created:
        try:
            delete_branch(branch_name, force=True)
        except GitError as exc:
            LOG.error("Failed to delete temporary branch %s: %s", branch_name, exc)
