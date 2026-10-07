"""Review operations return a validated copy; invalid edits leave the input intact."""

from __future__ import annotations

from copy import deepcopy
import uuid

from .domain import Plan, SuggestedCommit
from .errors import PlanValidationError
from .plan_store import unit_ids_for_commit
from .validation import validate_plan
from .diff_parser import render_partial_diff


def _commit(plan: Plan, number: str | int) -> SuggestedCommit:
    try:
        index = int(number) - 1
    except (ValueError, TypeError):
        raise PlanValidationError('commit number must be an integer') from None
    if index < 0 or index >= len(plan.suggested_commits):
        raise PlanValidationError('commit number is out of range')
    return plan.suggested_commits[index]


def _sync(plan: Plan) -> None:
    order = {h.id: i for i, h in enumerate(h for file in plan.diff.files for h in file.hunks)}
    for commit in plan.suggested_commits:
        commit.hunk_ids.sort(key=order.__getitem__)
        commit.atomic_change_ids = unit_ids_for_commit(plan, commit)
    validate_plan(plan)


def edit_plan(plan: Plan, action: str, arguments: list[str]) -> Plan:
    candidate = deepcopy(plan)
    if action == 'rename' and len(arguments) >= 2:
        _commit(candidate, arguments[0]).title = ' '.join(arguments[1:])
    elif action == 'merge' and len(arguments) == 2:
        first, second = (_commit(candidate, n) for n in arguments)
        if first is second:
            raise PlanValidationError('choose two different commits to merge')
        earlier, later = sorted((first, second), key=candidate.suggested_commits.index)
        earlier.hunk_ids.extend(later.hunk_ids)
        earlier.body = '\n\n'.join(body for body in (earlier.body, later.body) if body) or None
        candidate.suggested_commits.remove(later)
    elif action == 'move' and len(arguments) == 2:
        units = {unit.id: unit for unit in candidate.atomic_changes}
        uid, number = arguments
        if uid not in units:
            raise PlanValidationError(f'unknown atomic unit: {uid}')
        source = next(c for c in candidate.suggested_commits if uid in unit_ids_for_commit(candidate, c))
        target = _commit(candidate, number)
        if source is target:
            raise PlanValidationError('unit is already in that commit')
        hunks = units[uid].hunk_ids
        source.hunk_ids = [hid for hid in source.hunk_ids if hid not in hunks]
        target.hunk_ids.extend(hunks)
        if not source.hunk_ids:
            candidate.suggested_commits.remove(source)
    elif action == 'split' and len(arguments) == 2:
        source = _commit(candidate, arguments[0])
        uid = arguments[1]
        ids = unit_ids_for_commit(candidate, source)
        if uid not in ids or len(ids) < 2:
            raise PlanValidationError('split requires a unit from a commit containing multiple units')
        unit = next(unit for unit in candidate.atomic_changes if unit.id == uid)
        source.hunk_ids = [hid for hid in source.hunk_ids if hid not in unit.hunk_ids]
        new = SuggestedCommit('review-' + uuid.uuid4().hex, 'Split change', None, [uid], list(unit.hunk_ids))
        candidate.suggested_commits.insert(candidate.suggested_commits.index(source) + 1, new)
    elif action == 'order' and len(arguments) >= 1:
        tokens = ','.join(arguments).split(',')
        commits = [_commit(candidate, token) for token in tokens]
        if len(commits) != len(candidate.suggested_commits) or len({c.id for c in commits}) != len(commits):
            raise PlanValidationError('order must list every commit number exactly once')
        candidate.suggested_commits = commits
    else:
        raise PlanValidationError('invalid review action or arguments')
    _sync(candidate)
    return candidate


def inspect_commit(plan: Plan, number: str | int) -> str:
    commit = _commit(plan, number)
    index = plan.suggested_commits.index(commit)
    applied = [hid for previous in plan.suggested_commits[:index] for hid in previous.hunk_ids]
    return render_partial_diff(plan.diff, commit.hunk_ids, applied_hunk_ids=applied)
