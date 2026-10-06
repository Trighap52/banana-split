"""Offline real-Git fixtures for byte- and metadata-faithful replay."""

import subprocess
from pathlib import Path

import pytest

from banana_split.apply import apply_plan
from banana_split.config import Config
from banana_split.diff_parser import parse_unified_diff, render_partial_diff
from banana_split.errors import DiffParseError, PlanValidationError, UnsupportedOperationError
from banana_split.git_adapter import get_diff_for_commit
from banana_split.planner import build_plan, _validate_and_order_plan


def git(repo, *args, input_bytes=None):
    return subprocess.run(["git", *args], cwd=repo, check=True,
                          input=input_bytes, capture_output=True).stdout


@pytest.fixture
def repo(tmp_path, monkeypatch):
    path = tmp_path / 'repo'
    path.mkdir()
    git(path, 'init')
    git(path, 'config', 'user.name', 'Replay Test')
    git(path, 'config', 'user.email', 'replay@example.com')
    git(path, 'config', 'core.autocrlf', 'false')
    git(path, 'config', 'core.filemode', 'true')
    (path / 'ordinary.py').write_text('def first():\n    return 1\n' + '\n' * 20 + 'def second():\n    return 2\n')
    (path / 'rename.txt').write_text(''.join(f'line {i}\n' for i in range(50)))
    git(path, 'add', '.')
    git(path, 'commit', '-m', 'base')
    monkeypatch.chdir(path)
    return path


def commit(repo):
    git(repo, 'add', '--all')
    git(repo, 'commit', '-m', 'target')
    return git(repo, 'rev-parse', 'HEAD').decode().strip()


def verify(repo, target, *, expected_commits=None):
    plan = build_plan(Config(target=target))
    if expected_commits is not None:
        assert len(plan.suggested_commits) == expected_commits
    # Inspection must not write caller state; application must preserve it too.
    before = (repo / '.git' / 'index').read_bytes()
    head = git(repo, 'rev-parse', 'HEAD')
    files = {str(p.relative_to(repo)): p.read_bytes() for p in repo.rglob('*')
             if p.is_file() and '.git' not in p.relative_to(repo).parts}
    apply_plan(plan, Config(target=target))
    output = f'banana-split/split-{target[:7]}'
    assert git(repo, 'rev-parse', output + '^{tree}') == git(repo, 'rev-parse', target + '^{tree}')
    assert git(repo, 'rev-parse', 'HEAD') == head
    assert (repo / '.git' / 'index').read_bytes() == before
    assert {str(p.relative_to(repo)): p.read_bytes() for p in repo.rglob('*')
            if p.is_file() and '.git' not in p.relative_to(repo).parts} == files
    assert git(repo, 'status', '--porcelain') == b''
    assert len(git(repo, 'worktree', 'list', '--porcelain').split(b'worktree ')) == 2
    return plan, output


@pytest.mark.parametrize('operation', ['add', 'empty-add', 'executable-add', 'delete', 'empty-delete',
                                       'rename', 'rename-edit', 'mode', 'mode-edit'])
def test_file_operations_remain_indivisible(repo, operation):
    if operation == 'empty-delete':
        (repo / 'empty.txt').touch()
        commit(repo)
    if operation in ('add', 'empty-add', 'executable-add'):
        path = repo / 'new.txt'
        path.write_bytes(b'' if operation == 'empty-add' else b'new content\n')
        if operation == 'executable-add':
            path.chmod(0o755)
    elif operation in ('delete', 'empty-delete'):
        (repo / ('empty.txt' if operation == 'empty-delete' else 'ordinary.py')).unlink()
    elif operation.startswith('rename'):
        (repo / 'rename.txt').rename(repo / 'renamed.txt')
        if operation == 'rename-edit':
            path = repo / 'renamed.txt'
            path.write_text(path.read_text().replace('line 20\n', 'changed line 20\n'))
    else:
        path = repo / 'ordinary.py'
        path.chmod(0o755)
        if operation == 'mode-edit':
            path.write_text(path.read_text().replace('return 1', 'return 11').replace('return 2', 'return 22'))
    target = commit(repo)
    plan, _ = verify(repo, target, expected_commits=1)
    assert plan.diff.files[0].indivisible
    if operation == 'mode-edit':
        # An edited plan must not split content from the permission change.
        original = plan.suggested_commits[0]
        from banana_split.domain import SuggestedCommit
        assert len(original.hunk_ids) == 2
        plan.suggested_commits = [
            SuggestedCommit('a', 'first', None, [], original.hunk_ids[:1]),
            SuggestedCommit('b', 'second', None, [], original.hunk_ids[1:])]
        with pytest.raises(PlanValidationError, match='indivisible'):
            _validate_and_order_plan(plan)
        with pytest.raises(PlanValidationError, match='indivisible'):
            render_partial_diff(plan.diff, original.hunk_ids[:1])


@pytest.mark.parametrize('old,new', [
    (b'old', b'new'), (b'old\n', b'new'), (b'old', b'new\n'),
    (b'old\r\nkeep\r\n', b'new\r\nkeep\r\n'),
    (b'old\x0btext\n', b'new\x0btext\n'),
    (b'old\xff\n', b'new\xfe\n'),
])
def test_exact_source_bytes(repo, old, new):
    path = repo / 'bytes.py'
    path.write_bytes(old)
    commit(repo)
    path.write_bytes(new)
    target = commit(repo)
    _, output = verify(repo, target)
    assert git(repo, 'show', output + ':bytes.py') == new


@pytest.mark.parametrize('name', ['space name.py', 'quote"name.py', 'tab\tname.py', 'line\nname.py',
                                 'émoji-🍌.py', 'trailing .py ', 'name b/ambiguous.py'])
def test_git_quoted_and_unquoted_paths(repo, name):
    path = repo / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('value = 1\n')
    commit(repo)
    path.write_text('value = 2\n')
    target = commit(repo)
    plan, output = verify(repo, target)
    assert plan.diff.files[0].path_new == name
    assert git(repo, 'show', output + ':' + name) == b'value = 2\n'


@pytest.mark.parametrize('delta', ['insert', 'delete'])
def test_multiple_commits_adjust_later_hunk_ranges(repo, delta):
    path = repo / 'ordinary.py'
    source = path.read_text()
    if delta == 'insert':
        source = source.replace('    return 1', '    value = 11\n    return value')
    else:
        source = source.replace('def first():\n    return 1\n', '')
    path.write_text(source.replace('return 2', 'return 22'))
    target = commit(repo)
    plan, output = verify(repo, target, expected_commits=2)
    commits = git(repo, 'rev-list', '--reverse', f'{plan.diff.base_commit}..{output}').decode().splitlines()
    first = git(repo, 'show', commits[0] + ':ordinary.py')
    assert b'return 2\n' in first
    assert b'return 22\n' not in first


def test_diff_configuration_cannot_change_machine_patch(repo, monkeypatch):
    git(repo, 'config', 'color.ui', 'always')
    git(repo, 'config', 'diff.noprefix', 'true')
    git(repo, 'config', 'diff.mnemonicprefix', 'true')
    git(repo, 'config', 'diff.relative', 'true')
    git(repo, 'config', 'diff.external', 'false')
    (repo / 'ordinary.py').write_text('changed = True\n')
    target = commit(repo)
    child = repo / 'subdir'
    child.mkdir()
    monkeypatch.chdir(child)
    plan, _ = verify(repo, target)
    assert plan.diff.files[0].path_new == 'ordinary.py'


@pytest.mark.parametrize('shape', ['binary', 'symlink', 'submodule', 'merge', 'root'])
def test_unsupported_shapes_fail_before_worktree_creation(repo, shape, monkeypatch):
    import banana_split.apply as apply_module
    if shape == 'binary':
        (repo / 'binary.bin').write_bytes(b'\x00\x01')
        target = commit(repo)
    elif shape == 'symlink':
        (repo / 'link').symlink_to('ordinary.py')
        target = commit(repo)
    elif shape == 'submodule':
        head = git(repo, 'rev-parse', 'HEAD').decode().strip()
        git(repo, 'update-index', '--add', '--cacheinfo', f'160000,{head},module')
        git(repo, 'commit', '-m', 'gitlink')
        target = git(repo, 'rev-parse', 'HEAD').decode().strip()
    elif shape == 'merge':
        parent = git(repo, 'rev-parse', 'HEAD').decode().strip()
        (repo / 'ordinary.py').write_text('changed = True\n')
        other = commit(repo)
        tree = git(repo, 'rev-parse', 'HEAD^{tree}').decode().strip()
        target = git(repo, 'commit-tree', tree, '-p', parent, '-p', other, input_bytes=b'merge\n').decode().strip()
    else:
        target = git(repo, 'rev-list', '--max-parents=0', 'HEAD').decode().strip()
    before = git(repo, 'worktree', 'list', '--porcelain')
    monkeypatch.setattr(apply_module.tempfile, 'mkdtemp', lambda **kwargs: pytest.fail('must reject before replay'))
    with pytest.raises(UnsupportedOperationError):
        apply_plan(build_plan(Config(target=target)), Config(target=target))
    assert git(repo, 'worktree', 'list', '--porcelain') == before
    if shape == 'root':
        preview = build_plan(Config(target=target, dry_run=True))
        assert preview.diff.files  # root preview must diff against the empty tree


def test_invalid_hunk_counts_are_rejected():
    with pytest.raises(DiffParseError, match='line counts'):
        parse_unified_diff('diff --git a/f b/f\n--- a/f\n+++ b/f\n@@ -1,2 +1 @@\n-old\n+new\n')


def test_review_can_merge_multiple_shifted_hunks_into_one_patch(repo):
    from banana_split.domain import SuggestedCommit
    path = repo / 'ordinary.py'
    path.write_text(path.read_text().replace('    return 1', '    value = 11\n    return value')
                    .replace('return 2', 'return 22'))
    target = commit(repo)
    plan = build_plan(Config(target=target))
    assert len(plan.suggested_commits) == 2
    plan.suggested_commits = [SuggestedCommit(
        'merged', 'Both functions', None,
        [a.id for a in plan.atomic_changes],
        [h.id for file in plan.diff.files for h in file.hunks])]
    apply_plan(plan, Config(target=target))
    assert git(repo, 'rev-parse', f'banana-split/split-{target[:7]}^{{tree}}') == git(repo, 'rev-parse', 'HEAD^{tree}')


def test_conflicting_file_operation_paths_fail_before_replay(repo, monkeypatch):
    import banana_split.apply as apply_module
    (repo / 'folder').mkdir()
    (repo / 'folder' / 'nested.txt').write_text('nested\n')
    commit(repo)
    (repo / 'folder' / 'nested.txt').unlink()
    (repo / 'folder').rmdir()
    (repo / 'folder').write_text('now a file\n')
    target = commit(repo)
    monkeypatch.setattr(apply_module.tempfile, 'mkdtemp', lambda **kwargs: pytest.fail('must reject before replay'))
    with pytest.raises(UnsupportedOperationError, match='overlapping file-operation paths'):
        build_plan(Config(target=target))
