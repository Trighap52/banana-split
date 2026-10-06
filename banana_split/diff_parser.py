"""Parse Git patches for analysis while retaining exact replay text."""

from __future__ import annotations

import re
from typing import Iterable, List, Optional

from .analysis.language_intel import detect_language, extract_symbol_name_from_hunk_header
from .domain import Diff, DiffHunk, DiffLine, FileDiff
from .errors import DiffParseError, PlanValidationError

_HUNK_HEADER_RE = re.compile(
    r"^@@ -(?P<old_start>\d+)(?:,(?P<old_count>\d+))?"
    r" \+(?P<new_start>\d+)(?:,(?P<new_count>\d+))? @@(?P<tail>.*)$"
)
_QUOTED = r'"(?:[^"\\]|\\.)*"'


def _decode_path(value: str, *, prefix: bool = False) -> Optional[str]:
    # Git terminates an unquoted ---/+++ path containing spaces with a tab.
    value = value.removesuffix("\t")
    if value == "/dev/null":
        return None
    if value.startswith('"'):
        if not value.endswith('"'):
            raise DiffParseError("unterminated quoted Git path")
        data = bytearray()
        body = value[1:-1]
        i = 0
        escapes = {'a': 7, 'b': 8, 't': 9, 'n': 10, 'v': 11, 'f': 12, 'r': 13, '"': 34, '\\': 92}
        while i < len(body):
            if body[i] != '\\':
                data.extend(body[i].encode('utf-8', 'surrogateescape'))
                i += 1
            else:
                i += 1
                octal = re.match(r'[0-7]{3}', body[i:])
                if octal:
                    data.append(int(octal.group(), 8))
                    i += 3
                elif i < len(body) and body[i] in escapes:
                    data.append(escapes[body[i]])
                    i += 1
                else:
                    raise DiffParseError("invalid escape in quoted Git path")
        value = data.decode('utf-8', 'surrogateescape')
    if prefix and value.startswith(('a/', 'b/')):
        value = value[2:]
    return value


def _header_paths(header: str) -> tuple[Optional[str], Optional[str]]:
    text = header[len('diff --git '):]
    # The normal unquoted case has identical names, including spaces.
    same = re.fullmatch(r'a/(.*) b/\1', text)
    if same:
        return same.group(1), same.group(1)
    quoted = re.fullmatch(f'({_QUOTED}|a/.*?) ({_QUOTED}|b/.*)', text)
    if not quoted:
        raise DiffParseError(f"invalid Git diff header: {header}")
    return _decode_path(quoted.group(1), prefix=True), _decode_path(quoted.group(2), prefix=True)


def parse_unified_diff(raw_diff: str) -> Diff:
    # Only LF is a patch delimiter: CR, vertical tabs and arbitrary bytes belong
    # to source lines and must survive replay unchanged.
    lines = raw_diff.split('\n')
    if lines and lines[-1] == '':
        lines.pop()
    starts = [i for i, line in enumerate(lines) if line.startswith('diff --git ')]
    files = []
    for start, end in zip(starts, [*starts[1:], len(lines)]):
        files.append(_parse_file(lines[start:end]))
    if raw_diff.strip() and not files:
        raise DiffParseError("input contains no Git file diff sections")
    return Diff(base_commit=None, target_commit=None, files=files)


def _parse_file(lines: List[str]) -> FileDiff:
    old, new = _header_paths(lines[0])
    change = 'modify'
    modes = set()
    binary = False
    indivisible = False
    hunk_start = next((i for i, line in enumerate(lines) if line.startswith('@@')), len(lines))
    for line in lines[1:hunk_start]:
        if line.startswith('new file mode '):
            old, change, indivisible = None, 'add', True
            modes.add(line.split()[-1])
        elif line.startswith('deleted file mode '):
            new, change, indivisible = None, 'delete', True
            modes.add(line.split()[-1])
        elif line.startswith(('old mode ', 'new mode ')):
            indivisible = True
            modes.add(line.split()[-1])
        elif line.startswith('index '):
            parts = line.split()
            if len(parts) == 3:
                modes.add(parts[-1])
        elif line.startswith('rename from '):
            old, change, indivisible = _decode_path(line[len('rename from '):]), 'rename', True
        elif line.startswith('rename to '):
            new, change, indivisible = _decode_path(line[len('rename to '):]), 'rename', True
        elif line.startswith('--- '):
            old = _decode_path(line[4:], prefix=True)
            if old is None:
                change, indivisible = 'add', True
        elif line.startswith('+++ '):
            new = _decode_path(line[4:], prefix=True)
            if new is None:
                change, indivisible = 'delete', True
        elif line.startswith(('Binary files ', 'GIT binary patch')):
            binary, indivisible = True, True
        elif line.startswith(('copy from ', 'copy to ')):
            raise DiffParseError("copy patches are unsupported; use Git's default rename detection")

    path = new if new is not None else old
    if path is None:
        raise DiffParseError("file diff has no path")
    hunks = []
    i = hunk_start
    while i < len(lines):
        if not lines[i].startswith('@@ '):
            raise DiffParseError(f"unexpected patch line in {path}: {lines[i]!r}")
        end = next((j for j in range(i + 1, len(lines)) if lines[j].startswith('@@')), len(lines))
        hunks.append(_parse_hunk(lines[i:end], path, len(hunks)))
        i = end
    raw = '\n'.join(lines) + '\n'
    # Metadata-only operations need a selectable unit too. They are represented
    # as an opaque whole-file hunk; analysis must not infer a source symbol.
    if not hunks and not binary:
        indivisible = True
        hunks = [DiffHunk(f'{path}::h0', path, '', [], {'file_operation': True}, raw_patch='')]
    return FileDiff(old, new, change, binary, hunks,
                    raw_header='\n'.join(lines[:hunk_start]) + '\n',
                    raw_patch=raw, indivisible=indivisible, modes=modes)


def _parse_hunk(lines: List[str], path: str, index: int) -> DiffHunk:
    match = _HUNK_HEADER_RE.fullmatch(lines[0])
    if not match:
        raise DiffParseError(f"invalid hunk header in {path}: {lines[0]}")
    old = int(match['old_start'])
    new = int(match['new_start'])
    old_count = int(match['old_count'] or '1')
    new_count = int(match['new_count'] or '1')
    consumed_old = consumed_new = 0
    parsed = []
    for line in lines[1:]:
        if line == '\\ No newline at end of file':
            if not parsed:
                raise DiffParseError(f"newline marker without a preceding line in {path}")
            continue
        if not line or line[0] not in ' +-':
            raise DiffParseError(f"invalid hunk line in {path}: {line!r}")
        kind = line[0]
        parsed.append(DiffLine(kind, line[1:], old if kind != '+' else None,
                               new if kind != '-' else None))
        if kind in ' -':
            consumed_old += 1
            old += 1
        if kind in ' +':
            consumed_new += 1
            new += 1
    if (consumed_old, consumed_new) != (old_count, new_count):
        raise DiffParseError(f"hunk line counts do not match header in {path}")
    meta = {}
    language = detect_language(path)
    if language:
        meta['language'] = language
    symbol = extract_symbol_name_from_hunk_header(lines[0])
    if symbol:
        meta['symbol'] = symbol
    return DiffHunk(f'{path}::h{index}', path, lines[0], parsed, meta,
                    raw_patch='\n'.join(lines) + '\n')


def render_partial_diff(diff: Diff, hunk_ids: Iterable[str], *, applied_hunk_ids: Iterable[str] = ()) -> str:
    """Replay exact hunk bodies with ranges adjusted for previously applied units."""
    selected = set(hunk_ids)
    applied = set(applied_hunk_ids)
    output = []
    for file in diff.files:
        hunks = [h for h in file.hunks if h.id in selected]
        if not hunks:
            continue
        if file.indivisible:
            if {h.id for h in hunks} != {h.id for h in file.hunks}:
                raise PlanValidationError(f"file operation must remain indivisible: {file.path_new or file.path_old}")
            if file.raw_patch is None:
                raise PlanValidationError("file operation is missing its original patch")
            output.append(file.raw_patch)
            continue
        if file.raw_header is None:
            # Hand-built domain fixtures remain usable for ordinary modifications.
            path_old = file.path_old or file.path_new
            path_new = file.path_new or file.path_old
            header = f'diff --git a/{path_old} b/{path_new}\n--- a/{path_old}\n+++ b/{path_new}\n'
        else:
            # Original blob hashes describe the complete diff, not partial trees.
            header = ''.join(line + '\n' for line in file.raw_header.split('\n')[:-1]
                             if not line.startswith('index '))
        output.append(header)
        applied_offset = selected_offset = 0
        for hunk in file.hunks:
            match = _HUNK_HEADER_RE.fullmatch(hunk.header)
            if not match:
                raise PlanValidationError(f"invalid replay hunk header: {hunk.id}")
            old_count = int(match['old_count'] or '1')
            new_count = int(match['new_count'] or '1')
            if hunk.id in selected:
                old_start = int(match['old_start']) + applied_offset
                new_start = old_start + selected_offset
                if old_count == 0:
                    new_start += 1
                if new_count == 0:
                    new_start -= 1
                adjusted = f'@@ -{old_start},{old_count} +{new_start},{new_count} @@{match["tail"]}\n'
                body = hunk.raw_patch.split('\n', 1)[1] if hunk.raw_patch is not None else ''.join(
                    f'{line.line_type}{line.content}\n' for line in hunk.lines)
                output.append(adjusted + body)
            if hunk.id in applied:
                applied_offset += new_count - old_count
            if hunk.id in selected:
                selected_offset += new_count - old_count
    return ''.join(output)
