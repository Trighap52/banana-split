"""
Static heuristics for grouping diff hunks into atomic changes.

The functions here operate purely on the domain models and do not
interact with git or external services.
"""

from __future__ import annotations

from typing import List

from ..domain import AtomicChange, Diff
from .language_intel import detect_language


def group_hunks(diff: Diff) -> List[AtomicChange]:
    """
    Group diff hunks into initial atomic changes using simple heuristics.

    The initial implementation groups hunks by file. This is a simple
    but practical starting point that keeps changes from different
    files separate while still allowing more advanced splitting later.
    """

    atomic_changes: List[AtomicChange] = []

    for file in diff.files:
        if not file.hunks:
            continue

        path = file.path_new or file.path_old or ""

        tags = set()
        language = detect_language(path) if path else None
        if language:
            tags.add(language)

        # Very lightweight test detection based on file path.
        lower = path.lower()
        if "test" in lower or "/tests/" in lower:
            tags.add("test")

        # Group hunks by symbol name when available. This allows us to
        # create multiple atomic changes within a single file, each
        # corresponding to a function or method, while keeping hunks
        # ordered.
        groups: dict[str | None, list[str]] = {}
        order: list[str | None] = []

        for hunk in file.hunks:
            symbol = None
            meta_symbol = hunk.meta.get("symbol") if hasattr(hunk, "meta") else None
            if isinstance(meta_symbol, str) and meta_symbol:
                symbol = meta_symbol

            if symbol not in groups:
                groups[symbol] = []
                order.append(symbol)
            groups[symbol].append(hunk.id)

        # If there is only a single symbol (or no symbol information),
        # keep the simple "one atomic change per file" behavior.
        if len(order) == 1:
            hunk_ids = [h.id for h in file.hunks]
            atomic_changes.append(
                AtomicChange(
                    id=f"{path}::ac0" if path else "ac0",
                    hunk_ids=hunk_ids,
                    tags=set(tags),
                    summary=f"Changes in {path}" if path else None,
                )
            )
            continue

        # Otherwise, create one atomic change per symbol group, plus a
        # possible "misc" group for hunks without symbol information.
        ac_index = 0
        for symbol in order:
            symbol_hunk_ids = groups[symbol]
            if not symbol_hunk_ids:
                continue

            summary = f"Changes in {path}"
            if symbol:
                summary = f"Changes in {path} ({symbol})"

            atomic_changes.append(
                AtomicChange(
                    id=f"{path}::ac{ac_index}" if path else f"ac{ac_index}",
                    hunk_ids=symbol_hunk_ids,
                    tags=set(tags),
                    summary=summary,
                )
            )
            ac_index += 1

    return atomic_changes
