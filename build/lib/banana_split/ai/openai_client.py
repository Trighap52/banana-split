"""
OpenAI-based AI client for banana-split.

This is a placeholder implementation; the actual integration and prompt
design will be added once the core data flow is in place.
"""

from __future__ import annotations

from typing import List

from .interface import AIClient
from ..domain import AtomicChange, SuggestedCommit


class OpenAIClient(AIClient):
    """
    Placeholder AI client that currently returns no suggestions.
    """

    def propose_commits(self, atomic_changes: List[AtomicChange]) -> List[SuggestedCommit]:
        # In the initial scaffolding we simply return one commit per
        # atomic change with a generic title. This avoids depending on
        # external services while keeping the data flow realistic.
        suggested: List[SuggestedCommit] = []
        for change in atomic_changes:
            suggested.append(
                SuggestedCommit(
                    id=change.id,
                    title="Atomic change",
                    body=None,
                    atomic_change_ids=[change.id],
                    hunk_ids=list(change.hunk_ids),
                    estimated_risk=None,
                )
            )
        return suggested

