"""
Static heuristics for grouping diff hunks into atomic changes.

The functions here operate purely on the domain models and do not
interact with git or external services.
"""

from __future__ import annotations

from typing import List

from ..domain import AtomicChange, Diff
from .semantic_atomizer import atomize_semantically


def group_hunks(diff: Diff) -> List[AtomicChange]:
    """
    Group diff hunks into initial atomic changes using simple heuristics.

    The current implementation delegates to the semantic atomizer,
    which groups by symbol/file and applies lightweight dependency
    ordering (for example source-before-test when possible).
    """

    return atomize_semantically(diff)
