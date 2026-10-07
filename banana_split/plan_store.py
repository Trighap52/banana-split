"""Versioned plans contain grouping choices, never executable patch contents."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

from .config import Config
from .domain import Plan, SuggestedCommit
from .errors import GitError, PlanValidationError
from .git_adapter import _run_git
from .planner import build_plan
from .validation import validate_plan

SCHEMA_VERSION = 1
_HASH = re.compile(r'(?:[0-9a-f]{40}|[0-9a-f]{64})\Z')


def _units(plan: Plan) -> list[dict]:
    return [{'id': unit.id, 'summary': unit.summary, 'hunk_ids': list(unit.hunk_ids)}
            for unit in plan.atomic_changes]


def _fingerprint(plan: Plan) -> str:
    patches = ''.join(file.raw_patch or '' for file in plan.diff.files)
    return hashlib.sha256(patches.encode('utf-8', 'surrogateescape')).hexdigest()


def unit_ids_for_commit(plan: Plan, commit: SuggestedCommit) -> list[str]:
    selected = set(commit.hunk_ids)
    result = []
    for unit in plan.atomic_changes:
        covered = selected.intersection(unit.hunk_ids)
        if covered and covered != set(unit.hunk_ids):
            raise PlanValidationError(f'atomic unit is split across commits: {unit.id}')
        if covered:
            result.append(unit.id)
    return result


def plan_document(plan: Plan) -> dict:
    if not plan.suggested_commits:
        raise PlanValidationError("target has no replayable changes to save")
    validate_plan(plan)
    base, target = plan.diff.base_commit, plan.diff.target_commit
    if base is None or target is None:
        raise PlanValidationError('only existing non-root commits can be saved as replayable plans')
    commits = [{'id': c.id, 'title': c.title, 'body': c.body,
                'unit_ids': unit_ids_for_commit(plan, c)} for c in plan.suggested_commits]
    return {'schema_version': SCHEMA_VERSION, 'base_commit': base, 'target_commit': target,
            'target_tree': _run_git(['rev-parse', f'{target}^{{tree}}']).stdout.strip(),
            'patch_sha256': _fingerprint(plan), 'units': _units(plan), 'commits': commits}


def default_plan_path(plan: Plan) -> Path:
    git_dir = Path(_run_git(['rev-parse', '--absolute-git-dir']).stdout.strip())
    return git_dir / 'banana-split' / 'plans' / f'{plan.diff.target_commit}.json'


def _check_output_path(path: Path) -> None:
    """Do not let a plan artifact overwrite source or arbitrary Git metadata."""
    resolved = path.resolve()
    root = Path(_run_git(['rev-parse', '--show-toplevel']).stdout.strip()).resolve()
    git_dir = Path(_run_git(['rev-parse', '--absolute-git-dir']).stdout.strip()).resolve()
    common = Path(_run_git(['rev-parse', '--git-common-dir']).stdout.strip()).resolve()
    for metadata in (git_dir, common):
        if resolved == metadata or metadata in resolved.parents:
            managed = metadata / 'banana-split' / 'plans'
            if managed not in resolved.parents:
                raise PlanValidationError('plan output may only use banana-split/plans inside Git metadata')
            return
    if root in resolved.parents:
        relative = str(resolved.relative_to(root))
        try:
            tracked = _run_git(['ls-files', '--error-unmatch', '--', relative], cwd=str(root)).stdout
        except GitError:
            tracked = ''
        if tracked:
            raise PlanValidationError('plan output must not overwrite a tracked repository file')


def save_plan(plan: Plan, path: Path | str) -> Path:
    path = Path(path).absolute()
    _check_output_path(path)
    payload = json.dumps(plan_document(plan), indent=2) + '\n'
    path.parent.mkdir(parents=True, exist_ok=True)
    scratch = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         prefix='.banana-split-', delete=False) as stream:
            scratch = Path(stream.name)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(scratch, path)
    finally:
        if scratch is not None:
            scratch.unlink(missing_ok=True)
    return path


def _keys(value, expected: set[str], label: str) -> None:
    if not isinstance(value, dict) or set(value) != expected:
        raise PlanValidationError(f'{label} has invalid fields')


def load_plan(path: Path | str) -> Plan:
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise PlanValidationError(f'duplicate JSON field: {key}')
            result[key] = value
        return result

    document = json.loads(Path(path).read_text(encoding='utf-8'), object_pairs_hook=unique_object)
    _keys(document, {'schema_version', 'base_commit', 'target_commit', 'target_tree',
                     'patch_sha256', 'units', 'commits'}, 'plan')
    if type(document['schema_version']) is not int or document['schema_version'] != SCHEMA_VERSION:
        raise PlanValidationError('unsupported plan schema version; regenerate the plan')
    for field in ('base_commit', 'target_commit', 'target_tree'):
        if not isinstance(document[field], str) or not _HASH.fullmatch(document[field]):
            raise PlanValidationError(f'{field} must be an immutable full object ID')
    # Reconstruct all code, metadata and units from Git, never from JSON patches.
    plan = build_plan(Config(target=document['target_commit']))
    actual = plan_document(plan)
    for field in ('base_commit', 'target_commit', 'target_tree', 'patch_sha256', 'units'):
        if document[field] != actual[field]:
            raise PlanValidationError(f'plan {field} does not match this repository; regenerate the plan')
    proposals = document['commits']
    if not isinstance(proposals, list) or not proposals:
        raise PlanValidationError('plan must contain a non-empty list of commits')
    units = {unit.id: unit for unit in plan.atomic_changes}
    order = {h.id: i for i, h in enumerate(h for file in plan.diff.files for h in file.hunks)}
    assigned = []
    commits = []
    for proposal in proposals:
        _keys(proposal, {'id', 'title', 'body', 'unit_ids'}, 'commit')
        if not isinstance(proposal['id'], str) or not proposal['id'].strip():
            raise PlanValidationError('commit ID must be a non-empty string')
        if not isinstance(proposal['title'], str):
            raise PlanValidationError('commit title must be a string')
        if proposal['body'] is not None and not isinstance(proposal['body'], str):
            raise PlanValidationError('commit body must be a string or null')
        ids = proposal['unit_ids']
        if not isinstance(ids, list) or not ids or any(not isinstance(uid, str) or uid not in units for uid in ids):
            raise PlanValidationError('commit unit_ids must reference known atomic units')
        assigned.extend(ids)
        hunks = sorted((hid for uid in ids for hid in units[uid].hunk_ids), key=order.__getitem__)
        commits.append(SuggestedCommit(proposal['id'], proposal['title'], proposal['body'], list(ids), hunks))
    if len(assigned) != len(set(assigned)) or set(assigned) != set(units):
        raise PlanValidationError('plan must assign every atomic unit exactly once')
    plan.suggested_commits = commits
    validate_plan(plan)
    return plan
