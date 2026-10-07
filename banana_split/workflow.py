"""Explicit, non-interactive plan/apply commands and editable plan review."""

from __future__ import annotations

import argparse
import json
import shlex
import sys
from pathlib import Path

from .apply import apply_plan
from .config import Config
from .errors import PlanValidationError
from .logging_utils import configure_logging
from .plan_editor import edit_plan, inspect_commit
from .plan_store import default_plan_path, load_plan, plan_document, save_plan, unit_ids_for_commit
from .planner import build_plan


def command_parser(command: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=f'banana-split {command}')
    parser.add_argument('-v', '--verbose', action='count', default=0)
    parser.add_argument('--dry-run', action='store_true', help='Inspect only; write no files or Git refs.')
    if command == 'plan':
        parser.add_argument('target', nargs='?', default='HEAD', help='One existing non-merge commit.')
        parser.add_argument('--overwrite', action='store_true', help='Replace an existing plan artifact.')
        output = parser.add_mutually_exclusive_group()
        output.add_argument('-o', '--output', help='Plan JSON path (default: managed Git metadata directory).')
        output.add_argument('--json', action='store_true', help='Print JSON to stdout without saving.')
    else:
        parser.add_argument('plan_file', help='Versioned JSON plan.')
        if command == 'review':
            actions = parser.add_mutually_exclusive_group()
            actions.add_argument('--rename', nargs=2, metavar=('COMMIT', 'TITLE'))
            actions.add_argument('--merge', nargs=2, metavar=('FIRST', 'SECOND'))
            actions.add_argument('--move', nargs=2, metavar=('UNIT_ID', 'DESTINATION'))
            actions.add_argument('--split', nargs=2, metavar=('COMMIT', 'UNIT_ID'))
            actions.add_argument('--order', metavar='1,2,...')
            actions.add_argument('--show', metavar='COMMIT', help='Print a commit patch without saving.')
            parser.add_argument('-o', '--output', help='Save to a new plan file instead of updating the input.')
    return parser


def _summary(plan) -> None:
    print(f'Target: {plan.diff.target_commit} (base {plan.diff.base_commit})')
    print(f'Plan contains {len(plan.suggested_commits)} suggested commits')
    units = {unit.id: unit for unit in plan.atomic_changes}
    for index, commit in enumerate(plan.suggested_commits, start=1):
        print(f'  [{index}] {commit.title} ({len(commit.hunk_ids)} hunks)')
        if commit.body:
            print('    ' + commit.body.replace('\n', '\n    '))
        for uid in unit_ids_for_commit(plan, commit):
            print(f'    unit {uid}: {units[uid].summary or "Change unit"}')


def _interactive_review(plan):
    print('Actions: show N, rename N TITLE, merge N N, move UNIT N, split N UNIT, order 1,2,..., save, quit')
    while True:
        try:
            tokens = shlex.split(input('review> '))
        except EOFError:
            raise KeyboardInterrupt from None
        except ValueError as exc:
            print(f'Invalid input: {exc}', file=sys.stderr)
            continue
        if not tokens:
            continue
        if tokens == ['save']:
            return plan
        if tokens == ['quit']:
            return None
        try:
            if tokens[0] == 'show' and len(tokens) == 2:
                print(inspect_commit(plan, tokens[1]), end='')
            else:
                plan = edit_plan(plan, tokens[0], tokens[1:])
                _summary(plan)
        except PlanValidationError as exc:
            print(f'Edit rejected: {exc}', file=sys.stderr)


def run_workflow(command: str, argv: list[str]) -> None:
    parser = command_parser(command)
    args = parser.parse_args(argv)
    configure_logging(args.verbose)
    if command == 'plan':
        plan = build_plan(Config(target=args.target, verbosity=args.verbose))
        if args.json:
            print(json.dumps(plan_document(plan), indent=2))
            return
        _summary(plan)
        if args.dry_run:
            print('Dry run: no plan file or Git refs written.')
        else:
            path = Path(args.output or default_plan_path(plan))
            if path.exists() and not args.overwrite:
                raise PlanValidationError("plan already exists; use review or --overwrite to replace it")
            path = save_plan(plan, path)
            print(f'Saved plan: {path}')
            print(f'Review: banana-split review {shlex.quote(str(path))}')
            print(f'Apply: banana-split apply {shlex.quote(str(path))}')
        return

    plan = load_plan(args.plan_file)
    if command == 'apply':
        _summary(plan)
        apply_plan(plan, Config(dry_run=args.dry_run, verbosity=args.verbose))
        return

    action = next((name for name in ('rename', 'merge', 'move', 'split', 'order') if getattr(args, name)), None)
    if args.show is not None:
        if args.output:
            parser.error('--show cannot be combined with --output')
        print(inspect_commit(plan, args.show), end='')
        return
    if action:
        arguments = getattr(args, action)
        plan = edit_plan(plan, action, [arguments] if isinstance(arguments, str) else arguments)
    _summary(plan)
    should_save = bool(action or args.output)
    # Dry runs and piped inspection never prompt. Cancellation never writes.
    if not action and not args.output and not args.dry_run and sys.stdin.isatty():
        plan = _interactive_review(plan)
        if plan is None:
            print('Review cancelled; plan file unchanged.')
            return
        should_save = True
    if args.dry_run:
        print('Dry run: edits were validated; plan file unchanged.')
    elif should_save:
        print(f'Saved plan: {save_plan(plan, args.output or args.plan_file)}')
