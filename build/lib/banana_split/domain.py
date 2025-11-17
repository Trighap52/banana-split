"""
Core domain models for banana-split.

These dataclasses describe diffs, hunks, atomic changes, and commit
plans. They intentionally avoid any direct git or AI dependencies so
they can be reused by different parts of the system.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Optional, Set, List


@dataclass
class DiffLine:
    """
    A single line within a diff hunk.

    The line_type indicates whether this is an addition, deletion, or
    context line. Line numbers are optional and may be populated by the
    diff parser.
    """

    line_type: Literal["+", "-", " "]
    content: str
    original_lineno: Optional[int] = None
    new_lineno: Optional[int] = None


@dataclass
class DiffHunk:
    """
    A contiguous block of changes in a single file.
    """

    id: str
    file_path: str
    header: str
    lines: List[DiffLine]
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class FileDiff:
    """
    All hunks associated with a single file in a diff.
    """

    path_old: Optional[str]
    path_new: Optional[str]
    change_type: Literal["add", "modify", "delete", "rename"]
    is_binary: bool
    hunks: List[DiffHunk] = field(default_factory=list)


@dataclass
class Diff:
    """
    A parsed representation of a git diff between two commits or trees.
    """

    base_commit: Optional[str]
    target_commit: Optional[str]
    files: List[FileDiff] = field(default_factory=list)


@dataclass
class AtomicChange:
    """
    A small, coherent unit of change made up of one or more hunks.
    """

    id: str
    hunk_ids: List[str]
    tags: Set[str] = field(default_factory=set)
    summary: Optional[str] = None


@dataclass
class SuggestedCommit:
    """
    A proposed commit, consisting of one or more atomic changes.
    """

    id: str
    title: str
    body: Optional[str]
    atomic_change_ids: List[str]
    hunk_ids: List[str]
    estimated_risk: Optional[Literal["low", "medium", "high"]] = None


@dataclass
class Plan:
    """
    The full plan to split a diff into multiple commits.
    """

    diff: Diff
    atomic_changes: List[AtomicChange] = field(default_factory=list)
    suggested_commits: List[SuggestedCommit] = field(default_factory=list)
    invariants_checked: bool = False

