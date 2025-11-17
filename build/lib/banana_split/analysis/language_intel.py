"""
Lightweight language-aware helpers for banana-split.

These utilities provide best-effort detection of programming languages
and symbols so that heuristics can group related hunks more effectively.
"""

from __future__ import annotations

from typing import Optional


def detect_language(path: str) -> Optional[str]:
    """
    Guess the language for a file path based on its extension.
    """

    lower = path.lower()
    if lower.endswith(".py"):
        return "python"
    if lower.endswith(".js") or lower.endswith(".mjs") or lower.endswith(".cjs"):
        return "javascript"
    if lower.endswith(".ts") or lower.endswith(".tsx"):
        return "typescript"
    if lower.endswith(".go"):
        return "go"
    if lower.endswith(".java"):
        return "java"
    if lower.endswith(".rb"):
        return "ruby"
    if lower.endswith(".rs"):
        return "rust"

    return None


def extract_symbol_name_from_hunk_header(header: str) -> Optional[str]:
    """
    Attempt to extract a symbol name (e.g., function or method) from a
    diff hunk header.

    Many diff producers include the symbol name after the hunk ranges,
    but this is not guaranteed. The full implementation will likely
    use more sophisticated parsing.
    """

    # Placeholder: rely on the trailing text after the final '@@'.
    parts = header.split("@@")
    if len(parts) < 3:
        return None
    tail = parts[-1].strip()
    return tail or None


