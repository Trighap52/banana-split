"""Real Git coverage for saved-plan trust boundaries and review transactions."""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from banana_split import cli
from banana_split.config import Config
from banana_split.errors import PlanValidationError
from banana_split.plan_editor import edit_plan, inspect_commit
from banana_split.plan_store import default_plan_path, load_plan, plan_document, save_plan
from banana_split.planner import build_plan

PROJECT = Path(__file__).resolve().parents[1]


def git(repo, *args):
    return subprocess.run(['git', *args], cwd=repo, check=True, capture_output=True).stdout


@pytest.fixture
def repo(tmp_path, monkeypatch):
    path = tmp_path / 'repo'
    path.mkdir()
    git(path, 'init')
    git(path, 'config', 'user.name', 'Plan Test')
    git(path, 'config', 'user.email', 'plan@example.com')
    (path / 'tests').mkdir()
    service = 'def first():\n    return 1\n' + '\n' * 20 + 'def second():\n    return 2\n'
    tests = 'from service import first, second\n\ndef test_first():\n    assert first() == 1\n'
    (path / 'service.py').write_text(service)
    (path / 'tests' / 'test_service.py').write_text(tests)
    (path / 'notes.txt').write_text('old note\n')
    git(path, 'add', '.')
    git(path, 'commit', '-m', 'base')
    (path / 'service.py').write_text(service.replace('return 1', 'return 11').replace('return 2', 'return 22'))
    (path / 'tests' / 'test_service.py').write_text(tests.replace('== 1', '== 11'))
    (path / 'notes.txt').write_text('new note\n')
    git(path, 'commit', '-am', 'target')
    monkeypatch.chdir(path)
    return path


def invoke(repo, *args, check=True):
    env = dict(os.environ, PYTHONPATH=str(PROJECT))
    result = subprocess.run([sys.executable, '-m', 'banana_split.cli', *map(str, args)],
                            cwd=repo, env=env, text=True, capture_output=True)
    if check:
        assert result.returncode == 0, result.stderr
    return result


def state(repo):
    return (git(repo, 'rev-parse', 'HEAD'), (repo / '.git' / 'index').read_bytes(),
            {str(p.relative_to(repo)): p.read_bytes() for p in repo.rglob('*')
             if p.is_file() and '.git' not in p.relative_to(repo).parts},
            git(repo, 'worktree', 'list', '--porcelain'),
            git(repo, 'for-each-ref', '--format=%(refname):%(objectname)', 'refs/heads'))


def test_explicit_plan_review_apply_round_trip(repo, tmp_path):
    before = state(repo)
    target = git(repo, 'rev-parse', 'HEAD').decode().strip()
    result = invoke(repo, 'plan')
    assert 'Saved plan:' in result.stdout
    path = default_plan_path(build_plan(Config()))
    assert path.is_file()
    assert state(repo) == before
    document = json.loads(path.read_text())
    assert document['target_commit'] == target
    assert len(document['commits']) == 4
    assert 'raw_patch' not in path.read_text()
    result = invoke(repo, 'review', path, '--show', '2')
    assert 'diff --git a/service.py' in result.stdout
    assert '+    return 11' in result.stdout
    assert path.read_text() == json.dumps(document, indent=2) + '\n'
    invoke(repo, 'review', path, '--merge', '2', '3')
    invoke(repo, 'review', path, '--rename', '2', 'Update both functions')
    # Move an entire test unit into the implementation commit. Empty source
    # commits disappear; all units remain covered once.
    invoke(repo, 'review', path, '--move', 'tests/test_service.py::ac0', '2')
    invoke(repo, 'review', path, '--order', '2,1')
    approved = load_plan(path)
    assert len(approved.suggested_commits) == 2
    assert approved.suggested_commits[0].title == 'Update both functions'
    assert state(repo) == before
    result = invoke(repo, 'apply', path)
    assert 'Created banana-split/' in result.stdout
    output = f'banana-split/split-{target[:7]}'
    assert git(repo, 'rev-parse', output + '^{tree}') == git(repo, 'rev-parse', target + '^{tree}')
    assert git(repo, 'show', '-s', '--format=%s', output + '^').strip() == b'Update both functions'
    after = state(repo)
    assert after[:4] == before[:4]  # only the output ref changes


def test_bare_command_is_read_only_in_noninteractive_use(repo):
    before = state(repo)
    result = invoke(repo)
    assert 'Inspection only' in result.stdout
    assert state(repo) == before


@pytest.mark.parametrize('command', ['plan', 'review', 'apply'])
def test_dry_run_never_writes_or_prompts(repo, command, monkeypatch):
    plan = build_plan(Config())
    path = save_plan(plan, default_plan_path(plan))
    payload = path.read_bytes()
    before = state(repo)
    monkeypatch.setattr('banana_split.workflow.sys.stdin.isatty', lambda: True)
    monkeypatch.setattr('builtins.input', lambda prompt: pytest.fail('dry-run must not prompt'))
    arguments = [command, '--dry-run']
    if command != 'plan':
        arguments.insert(1, str(path))
    if command == 'review':
        arguments.extend(['--merge', '2', '3'])
    assert cli.main(arguments) == 0
    assert path.read_bytes() == payload
    assert state(repo) == before


@pytest.mark.parametrize('mutate', [
    lambda d: d.update(schema_version=2),
    lambda d: d.update(schema_version=True),
    lambda d: d.update(base_commit='HEAD^'),
    lambda d: d.update(target_commit='HEAD'),
    lambda d: d.update(target_tree='0' * 40),
    lambda d: d.update(patch_sha256='0' * 64),
    lambda d: d.update(units=[]),
    lambda d: d.update(raw_patch='malicious patch'),
    lambda d: d['commits'].pop(),
    lambda d: d['commits'][0]['unit_ids'].append(d['commits'][1]['unit_ids'][0]),
    lambda d: d['commits'][0].update(unit_ids=['unknown']),
    lambda d: d['commits'][0].update(title=''),
    lambda d: d['commits'][0].update(title='invalid\nmultiline'),
    lambda d: d['commits'][0].update(body='bad\x00body'),
    lambda d: d['commits'][0].update(id=d['commits'][1]['id']),
    lambda d: d['commits'].reverse(),
])
def test_tampered_plans_cannot_apply(repo, tmp_path, mutate):
    document = plan_document(build_plan(Config()))
    mutate(document)
    path = tmp_path / 'bad-plan.json'
    path.write_text(json.dumps(document))
    before = state(repo)
    result = invoke(repo, 'apply', path, check=False)
    assert result.returncode == 1
    assert state(repo) == before


def test_saved_target_does_not_follow_moved_head(repo, tmp_path):
    original = build_plan(Config())
    path = save_plan(original, tmp_path / 'plan.json')
    (repo / 'notes.txt').write_text('later unrelated change\n')
    git(repo, 'commit', '-am', 'later')
    before = state(repo)
    loaded = load_plan(path)
    assert loaded.diff.target_commit == original.diff.target_commit
    invoke(repo, 'apply', path)
    output = f'banana-split/split-{original.diff.target_commit[:7]}'
    assert git(repo, 'rev-parse', output + '^{tree}') == git(repo, 'rev-parse', original.diff.target_commit + '^{tree}')
    assert state(repo)[:4] == before[:4]


def test_plan_from_another_repository_is_rejected(repo, tmp_path, monkeypatch):
    path = save_plan(build_plan(Config()), tmp_path / 'plan.json')
    other = tmp_path / 'other'
    other.mkdir()
    git(other, 'init')
    result = invoke(other, 'apply', path, check=False)
    assert result.returncode == 1
    assert not list((other / '.git' / 'worktrees').glob('*'))


@pytest.mark.parametrize('filename', ['service.py', '.git/config', '.git/index'])
def test_plan_output_cannot_overwrite_code_or_git_metadata(repo, filename):
    target = repo / filename
    before = target.read_bytes()
    with pytest.raises(PlanValidationError):
        save_plan(build_plan(Config()), target)
    assert target.read_bytes() == before


def test_duplicate_json_fields_are_rejected(repo, tmp_path):
    path = tmp_path / 'plan.json'
    payload = json.dumps(plan_document(build_plan(Config())))
    path.write_text(payload[:-1] + ',"commits":[]}')
    with pytest.raises(PlanValidationError, match='duplicate JSON field'):
        load_plan(path)


def test_failed_structural_edit_is_transactional(repo):
    plan = build_plan(Config())
    before = plan_document(plan)
    with pytest.raises(PlanValidationError, match='dependency'):
        edit_plan(plan, 'order', ['4,1,2,3'])
    assert plan_document(plan) == before
    with pytest.raises(PlanValidationError):
        edit_plan(plan, 'rename', ['1', 'bad\nmessage'])
    assert plan_document(plan) == before


def test_split_merged_commit_preserves_coverage(repo):
    plan = build_plan(Config())
    merged = edit_plan(plan, 'merge', ['2', '3'])
    split = edit_plan(merged, 'split', ['2', 'service.py::ac1'])
    assert len(split.suggested_commits) == 4
    assert len(merged.suggested_commits) == 3
    assert sum(len(c.hunk_ids) for c in split.suggested_commits) == sum(len(f.hunks) for f in plan.diff.files)
    patch = inspect_commit(split, '3')
    assert '+    return 22' in patch
    assert '+    return 11' not in patch


@pytest.mark.parametrize('stop', ['quit', KeyboardInterrupt(), EOFError()])
def test_interactive_cancellation_leaves_plan_file_unchanged(repo, monkeypatch, stop):
    path = save_plan(build_plan(Config()), default_plan_path(build_plan(Config())))
    before = path.read_bytes()
    commands = iter(['rename 1 Changed title', stop])
    monkeypatch.setattr('banana_split.workflow.sys.stdin.isatty', lambda: True)

    def respond(prompt):
        answer = next(commands)
        if isinstance(answer, BaseException):
            raise answer
        return answer

    monkeypatch.setattr('builtins.input', respond)
    assert cli.main(['review', str(path)]) == (0 if stop == 'quit' else 130)
    assert path.read_bytes() == before


def test_interactive_review_rejects_invalid_edit_then_can_save(repo, monkeypatch, capsys):
    plan = build_plan(Config())
    path = save_plan(plan, default_plan_path(plan))
    commands = iter(['order 4,1,2,3', 'rename 1 Documentation change', 'save'])
    monkeypatch.setattr('banana_split.workflow.sys.stdin.isatty', lambda: True)
    monkeypatch.setattr('builtins.input', lambda prompt: next(commands))
    assert cli.main(['review', str(path)]) == 0
    assert 'Edit rejected' in capsys.readouterr().err
    assert load_plan(path).suggested_commits[0].title == 'Documentation change'


def test_replanning_does_not_silently_overwrite_reviewed_artifact(repo):
    invoke(repo, 'plan')
    path = default_plan_path(build_plan(Config()))
    invoke(repo, 'review', path, '--rename', '1', 'Reviewed title')
    before = path.read_bytes()
    result = invoke(repo, 'plan', check=False)
    assert result.returncode == 1
    assert 'overwrite' in result.stderr
    assert path.read_bytes() == before
    invoke(repo, 'plan', '--overwrite')
    assert load_plan(path).suggested_commits[0].title == 'Atomic change'


def test_empty_commit_does_not_export_or_publish_a_plan(repo):
    git(repo, 'commit', '--allow-empty', '-m', 'empty')
    before = state(repo)
    result = invoke(repo, 'plan', check=False)
    assert result.returncode == 1
    assert 'no replayable changes' in result.stderr
    result = invoke(repo, '--apply', check=False)
    assert result.returncode == 1
    assert 'no replayable changes' in result.stderr
    assert state(repo) == before
    assert not default_plan_path(build_plan(Config())).exists()


def test_invalid_unicode_commit_message_fails_before_replay(repo, tmp_path):
    document = plan_document(build_plan(Config()))
    document['commits'][0]['title'] = '\ud800'
    path = tmp_path / 'bad-unicode.json'
    path.write_text(json.dumps(document))
    before = state(repo)
    result = invoke(repo, 'apply', path, check=False)
    assert result.returncode == 1
    assert 'invalid Unicode' in result.stderr
    assert state(repo) == before


def test_portable_plan_applies_in_clone_with_same_objects(repo, tmp_path):
    plan = build_plan(Config())
    path = save_plan(plan, tmp_path / 'portable.json')
    clone = tmp_path / 'clone'
    git(repo, 'clone', str(repo), str(clone))
    git(clone, 'config', 'user.name', 'Clone Test')
    git(clone, 'config', 'user.email', 'clone@example.com')
    before = state(clone)
    invoke(clone, 'apply', path)
    output = f'banana-split/split-{plan.diff.target_commit[:7]}'
    assert git(clone, 'rev-parse', output + '^{tree}') == git(repo, 'rev-parse', 'HEAD^{tree}')
    assert state(clone)[:4] == before[:4]


def test_managed_plan_storage_and_apply_in_linked_worktree(repo, tmp_path, monkeypatch):
    linked = tmp_path / 'linked'
    git(repo, 'worktree', 'add', '--detach', str(linked), 'HEAD')
    git_dir = Path(git(linked, 'rev-parse', '--absolute-git-dir').decode().strip())
    index = git_dir / 'index'
    before = (index.read_bytes(), git(linked, 'rev-parse', 'HEAD'),
              git(linked, 'worktree', 'list', '--porcelain'))
    monkeypatch.chdir(linked)
    plan = build_plan(Config())
    path = default_plan_path(plan)
    assert git_dir in path.parents
    assert cli.main(['plan']) == 0
    assert path.is_file()
    assert cli.main(['apply', str(path)]) == 0
    assert (index.read_bytes(), git(linked, 'rev-parse', 'HEAD'),
            git(linked, 'worktree', 'list', '--porcelain')) == before
    assert git(linked, '--no-optional-locks', 'status', '--porcelain') == b''


def test_bare_inspection_can_report_opaque_binary_changes(repo):
    (repo / 'blob.bin').write_bytes(b'\x00\x01')
    git(repo, 'add', 'blob.bin')
    git(repo, 'commit', '-m', 'binary')
    before = state(repo)
    result = invoke(repo, '--dry-run')
    assert 'Binary change:' in result.stdout
    assert 'cannot apply' in result.stdout
    assert state(repo) == before
