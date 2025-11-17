"""
Unified diff parsing for banana-split.

The parser converts a raw unified diff string into domain objects
defined in banana_split.domain.

The implementation is intentionally conservative: it focuses on the
unified diff format produced by git (e.g. `git diff`, `git show`) and
ignores metadata that is not needed for splitting (such as modes and
indexes). The goal is to faithfully capture file paths, hunks, and line
contents without ever altering the underlying source code.
"""

from __future__ import annotations

import re
from typing import Iterable, List, Optional, Sequence, Set, Tuple

from .domain import Diff, DiffHunk, DiffLine, FileDiff
from .analysis.language_intel import detect_language, extract_symbol_name_from_hunk_header


_HUNK_HEADER_RE = re.compile(
    r"^@@ -(?P<old_start>\d+)(?:,(?P<old_count>\d+))?"
    r" \+(?P<new_start>\d+)(?:,(?P<new_count>\d+))?"
    r" @@"
)


def parse_unified_diff(raw_diff: str) -> Diff:
    """
    Parse a unified diff into a Diff object.

    The returned Diff does not currently populate base_commit or
    target_commit; these can be supplied by the caller based on the git
    command used to obtain the diff.
    """

    lines = raw_diff.splitlines()
    files: List[FileDiff] = []

    if not lines:
        return Diff(base_commit=None, target_commit=None, files=files)

    i = 0
    # Skip any preamble (e.g. commit headers) until the first file diff.
    while i < len(lines) and not lines[i].startswith("diff --git "):
        i += 1

    while i < len(lines):
        if not lines[i].startswith("diff --git "):
            i += 1
            continue

        file_diff, i = _parse_single_file_diff(lines, i)
        if file_diff is not None:
            files.append(file_diff)

    return Diff(base_commit=None, target_commit=None, files=files)


def _parse_single_file_diff(
    lines: Sequence[str],
    start_index: int,
) -> Tuple[Optional[FileDiff], int]:
    """
    Parse a single `diff --git` section starting at start_index.

    Returns a tuple of (FileDiff | None, next_index).
    """

    i = start_index
    header_line = lines[i]
    i += 1

    # Example: "diff --git a/path b/path"
    parts = header_line.split()
    if len(parts) < 4:
        # Malformed; skip to next diff.
        while i < len(lines) and not lines[i].startswith("diff --git "):
            i += 1
        return None, i

    path_old = parts[-2]
    path_new = parts[-1]

    if path_old.startswith("a/"):
        path_old = path_old[2:]
    if path_new.startswith("b/"):
        path_new = path_new[2:]

    change_type: str = "modify"
    is_binary = False
    explicit_rename_from: Optional[str] = None
    explicit_rename_to: Optional[str] = None

    # Consume metadata lines until we hit file headers ("---"/"+++") or
    # another diff section.
    while i < len(lines):
        line = lines[i]

        if line.startswith("diff --git "):
            # No content for this file; return what we have.
            return (
                FileDiff(
                    path_old=path_old,
                    path_new=path_new,
                    change_type=change_type,  # type: ignore[arg-type]
                    is_binary=is_binary,
                    hunks=[],
                ),
                i,
            )

        if line.startswith("new file mode "):
            change_type = "add"
        elif line.startswith("deleted file mode "):
            change_type = "delete"
        elif line.startswith("rename from "):
            explicit_rename_from = line[len("rename from ") :].strip()
            change_type = "rename"
        elif line.startswith("rename to "):
            explicit_rename_to = line[len("rename to ") :].strip()
            change_type = "rename"
        elif line.startswith("Binary files ") and " differ" in line:
            is_binary = True
        elif line.startswith("GIT binary patch"):
            is_binary = True
        elif line.startswith("--- "):
            # Start of textual diff for this file.
            break

        i += 1

    # Finalize paths based on rename metadata if present.
    if explicit_rename_from is not None:
        path_old = explicit_rename_from
    if explicit_rename_to is not None:
        path_new = explicit_rename_to

    # Binary files may or may not have textual hunks. For now, we treat
    # them as opaque and skip any patch body.
    if is_binary:
        while i < len(lines) and not lines[i].startswith("diff --git "):
            i += 1
        return (
            FileDiff(
                path_old=path_old,
                path_new=path_new,
                change_type=change_type,  # type: ignore[arg-type]
                is_binary=True,
                hunks=[],
            ),
            i,
        )

    # Parse file header lines: --- and +++
    old_path_line: Optional[str] = None
    new_path_line: Optional[str] = None

    if i < len(lines) and lines[i].startswith("--- "):
        old_path_line = lines[i][4:].strip()
        i += 1
    if i < len(lines) and lines[i].startswith("+++ "):
        new_path_line = lines[i][4:].strip()
        i += 1

    # Use /dev/null markers to refine change_type and paths.
    if old_path_line == "/dev/null":
        change_type = "add"
        path_old = None  # type: ignore[assignment]
    elif old_path_line and old_path_line.startswith("a/"):
        path_old = old_path_line[2:]
    elif old_path_line:
        path_old = old_path_line

    if new_path_line == "/dev/null":
        change_type = "delete"
        path_new = None  # type: ignore[assignment]
    elif new_path_line and new_path_line.startswith("b/"):
        path_new = new_path_line[2:]
    elif new_path_line:
        path_new = new_path_line

    hunks: List[DiffHunk] = []
    hunk_index = 0

    # Determine language once per file if we have a usable path.
    language = detect_language(path_new or path_old or "") if (path_new or path_old) else None

    # Parse hunks until the next diff header or EOF.
    while i < len(lines) and not lines[i].startswith("diff --git "):
        if lines[i].startswith("@@"):
            hunk, i = _parse_hunk(
                lines=lines,
                start_index=i,
                file_path=path_new or path_old or "",
                hunk_index=hunk_index,
                language=language,
            )
            hunks.append(hunk)
            hunk_index += 1
        else:
            i += 1

    return (
        FileDiff(
            path_old=path_old,
            path_new=path_new,
            change_type=change_type,  # type: ignore[arg-type]
            is_binary=is_binary,
            hunks=hunks,
        ),
        i,
    )


def _parse_hunk(
    lines: Sequence[str],
    start_index: int,
    file_path: str,
    hunk_index: int,
    language: Optional[str],
) -> Tuple[DiffHunk, int]:
    """
    Parse a single hunk starting at `start_index`.
    """

    header = lines[start_index]
    i = start_index + 1

    old_start, new_start = _parse_hunk_header_ranges(header)
    original_lineno: Optional[int] = old_start
    new_lineno: Optional[int] = new_start

    diff_lines: List[DiffLine] = []

    while i < len(lines):
        line = lines[i]

        if line.startswith("diff --git ") or line.startswith("@@"):
            break

        if line.startswith("\\ No newline at end of file"):
            # This line modifies the semantics of the previous line but
            # does not itself represent a source line, so we ignore it
            # in the structural representation.
            i += 1
            continue

        if not line:
            # Empty line inside a hunk is treated as context.
            line_type = " "
            content = ""
        else:
            first_char = line[0]
            if first_char in ("+", "-", " "):
                line_type = first_char
                content = line[1:]
            else:
                # Unexpected leading character; treat as context to avoid
                # corrupting the patch.
                line_type = " "
                content = line

        diff_lines.append(
            DiffLine(
                line_type=line_type,  # type: ignore[arg-type]
                content=content,
                original_lineno=original_lineno,
                new_lineno=new_lineno,
            )
        )

        if line_type in (" ", "-") and original_lineno is not None:
            original_lineno += 1
        if line_type in (" ", "+") and new_lineno is not None:
            new_lineno += 1

        i += 1

    hunk_id = f"{file_path}::h{hunk_index}"

    meta: dict[str, object] = {}
    if language:
        meta["language"] = language

    symbol_name = extract_symbol_name_from_hunk_header(header)
    if symbol_name:
        meta["symbol"] = symbol_name

    return DiffHunk(
        id=hunk_id,
        file_path=file_path,
        header=header,
        lines=diff_lines,
        meta=meta,
    ), i


def _parse_hunk_header_ranges(header: str) -> Tuple[Optional[int], Optional[int]]:
    """
    Extract the old and new starting line numbers from a hunk header.
    """

    match = _HUNK_HEADER_RE.match(header)
    if not match:
        return None, None

    old_start = int(match.group("old_start"))
    new_start = int(match.group("new_start"))
    return old_start, new_start


def render_partial_diff(diff: Diff, hunk_ids: Iterable[str]) -> str:
    """
    Render a new unified diff containing only the hunks with the given ids.

    This function does not attempt to recompute hunk ranges; instead it
    reuses the original hunk headers and contents. Git's patch
    application logic is generally tolerant of minor line-number
    mismatches when sufficient context is present, which is acceptable
    for the initial implementation.
    """

    include_ids: Set[str] = set(hunk_ids)
    if not include_ids:
        return ""

    output: List[str] = []

    for file in diff.files:
        selected_hunks = [h for h in file.hunks if h.id in include_ids]
        if not selected_hunks:
            continue

        path_old = file.path_old or file.path_new or "unknown"
        path_new = file.path_new or file.path_old or "unknown"

        output.append(f"diff --git a/{path_old} b/{path_new}")

        # Minimal file headers; mode and index lines are omitted because
        # they are not required for `git apply`.
        if file.change_type == "add":
            old_label = "/dev/null"
            new_label = f"b/{path_new}"
        elif file.change_type == "delete":
            old_label = f"a/{path_old}"
            new_label = "/dev/null"
        else:
            old_label = f"a/{path_old}"
            new_label = f"b/{path_new}"

        output.append(f"--- {old_label}")
        output.append(f"+++ {new_label}")

        for hunk in selected_hunks:
            output.append(hunk.header)
            for line in hunk.lines:
                output.append(f"{line.line_type}{line.content}")

    if not output:
        return ""

    # Ensure diff ends with a newline, as expected by most tools.
    return "\n".join(output) + "\n"
