"""
Abstract interface for AI-assisted planning in banana-split.

This module defines the protocol that concrete AI clients must
implement. Keeping this separate from any specific provider makes it
easy to plug in different backends or to disable AI entirely.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List

from ..domain import AtomicChange, SuggestedCommit


class AIClient(ABC):
    """
    Abstract interface for AI interactions.
    """

    @abstractmethod
    def propose_commits(self, atomic_changes: List[AtomicChange]) -> List[SuggestedCommit]:
        """
        Given a list of atomic changes, return a list of proposed
        commits that group those atomic changes into coherent units.

        Implementations are responsible for enforcing or repairing
        invariants so that each hunk appears in exactly one suggested
        commit.
        """


