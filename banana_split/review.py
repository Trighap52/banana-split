"""
User-facing review of a banana-split plan.

The initial implementation is deliberately simple: it prints a summary
of the proposed commits and returns the plan unchanged. Interactive
editing will be added later.
"""

from __future__ import annotations

import sys

from .domain import Plan

def review_plan(plan: Plan, *, interactive: bool = True) -> Plan:
    """
    Present a summary of the plan to the user and allow for edits.

    The initial interactive flow is intentionally lightweight: it
    prints a summary, then optionally allows the user to rename commit
    titles. More advanced editing will be added later.
    """

    print(f"Plan contains {len(plan.suggested_commits)} suggested commits")
    for idx, commit in enumerate(plan.suggested_commits, start=1):
        print(f"  [{idx}] {commit.title} ({len(commit.hunk_ids)} hunks) id={commit.id}")

    if not interactive or not sys.stdin.isatty():
        # Non-interactive environment: return the plan as-is.
        return plan

    try:
        answer = input("Do you want to rename any commit titles? [y/N] ").strip().lower()
    except EOFError:
        raise KeyboardInterrupt from None

    if answer not in {"y", "yes"}:
        return plan

    for idx, commit in enumerate(plan.suggested_commits, start=1):
        prompt = f"New title for commit [{idx}] (current: {commit.title!r}, press Enter to keep): "
        try:
            new_title = input(prompt)
        except EOFError:
            raise KeyboardInterrupt from None
        if new_title.strip():
            commit.title = new_title.strip()

    return plan

