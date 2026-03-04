"""
Lightweight language-aware helpers for banana-split.

These utilities provide best-effort detection of programming languages
and symbols so that heuristics can group related hunks more effectively.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Iterable, Optional

from ..domain import DiffHunk


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


@dataclass
class _PythonSymbolSpan:
    symbol: str
    start_lineno: int
    end_lineno: int
    depth: int
    order: int


def extract_python_symbol_for_hunk(hunk: DiffHunk, source: str, *, side: str) -> Optional[str]:
    """
    Infer a Python symbol for a hunk by mapping hunk line numbers to AST spans.

    side:
      - "new": map using line numbers on the new side of the diff
      - "old": map using line numbers on the original side of the diff
    """

    if side not in {"new", "old"}:
        raise ValueError(f"invalid side {side!r}; expected 'new' or 'old'")

    if side == "new":
        changed = _collect_line_numbers(hunk, use_new=True, changed_line_type="+")
        fallback = _collect_line_numbers(hunk, use_new=True, changed_line_type=" ")
    else:
        changed = _collect_line_numbers(hunk, use_new=False, changed_line_type="-")
        fallback = _collect_line_numbers(hunk, use_new=False, changed_line_type=" ")

    candidate_lines = changed or fallback
    return extract_python_symbol_for_lines(source, candidate_lines)


def extract_python_symbol_for_lines(source: str, line_numbers: Iterable[int]) -> Optional[str]:
    """
    Infer the most likely Python symbol (function/method scope) for line numbers.

    Returns a normalized string such as:
      - "def foo"
      - "def Service.handle"
      - "def outer.inner"
    """

    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return None

    spans = _collect_python_symbol_spans(tree)
    if not spans:
        return None

    votes: dict[str, tuple[int, int, int]] = {}
    # value tuple = (hits, max_depth, best_order)
    for lineno in line_numbers:
        if not isinstance(lineno, int) or lineno <= 0:
            continue

        containing = [span for span in spans if span.start_lineno <= lineno <= span.end_lineno]
        if not containing:
            continue

        # Prefer the deepest symbol (for nested scopes).
        best = max(containing, key=lambda span: (span.depth, -span.order))
        prior = votes.get(best.symbol)
        if prior is None:
            votes[best.symbol] = (1, best.depth, best.order)
        else:
            votes[best.symbol] = (prior[0] + 1, max(prior[1], best.depth), min(prior[2], best.order))

    if not votes:
        return None

    # Most votes first, then deeper symbols, then stable declaration order.
    best_symbol = max(
        votes.items(),
        key=lambda item: (item[1][0], item[1][1], -item[1][2]),
    )[0]
    return best_symbol


def extract_python_import_modules(source: str) -> set[str]:
    """
    Extract normalized module references imported by Python source.

    Examples:
      - `import pkg.service as svc` -> {"pkg.service"}
      - `from pkg import service` -> {"pkg", "pkg.service"}
      - `from pkg.service import run` -> {"pkg.service", "pkg.service.run"}
    """

    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return set()

    modules: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                normalized = _normalize_module_name(alias.name)
                if normalized:
                    modules.add(normalized)
            continue

        if isinstance(node, ast.ImportFrom):
            # Relative imports (`from .foo import bar`) are omitted because
            # resolving them reliably requires package context.
            if node.level and node.level > 0:
                continue

            base = _normalize_module_name(node.module)
            if not base:
                continue
            modules.add(base)

            for alias in node.names:
                if alias.name == "*":
                    continue
                child = _normalize_module_name(f"{base}.{alias.name}")
                if child:
                    modules.add(child)

    return modules


def _collect_python_symbol_spans(tree: ast.AST) -> list[_PythonSymbolSpan]:
    spans: list[_PythonSymbolSpan] = []
    order_counter = 0

    def visit(
        node: ast.AST,
        *,
        class_stack: list[str],
        func_stack: list[str],
    ) -> None:
        nonlocal order_counter

        if isinstance(node, ast.ClassDef):
            next_class_stack = class_stack + [node.name]
            for child in node.body:
                visit(child, class_stack=next_class_stack, func_stack=func_stack)
            return

        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            start_lineno = _node_start_lineno(node)
            end_lineno = _node_end_lineno(node)
            if end_lineno < start_lineno:
                end_lineno = start_lineno

            if class_stack:
                qualname = ".".join([*class_stack, *func_stack, node.name])
            else:
                qualname = ".".join([*func_stack, node.name])

            symbol = f"def {qualname}"
            depth = len(class_stack) + len(func_stack) + 1
            spans.append(
                _PythonSymbolSpan(
                    symbol=symbol,
                    start_lineno=start_lineno,
                    end_lineno=end_lineno,
                    depth=depth,
                    order=order_counter,
                )
            )
            order_counter += 1

            next_func_stack = func_stack + [node.name]
            for child in node.body:
                visit(child, class_stack=class_stack, func_stack=next_func_stack)
            return

        for child in ast.iter_child_nodes(node):
            visit(child, class_stack=class_stack, func_stack=func_stack)

    visit(tree, class_stack=[], func_stack=[])
    return spans


def _node_start_lineno(node: ast.AST) -> int:
    lineno = getattr(node, "lineno", 1)
    decorators = getattr(node, "decorator_list", [])
    if isinstance(decorators, list):
        for decorator in decorators:
            deco_lineno = getattr(decorator, "lineno", None)
            if isinstance(deco_lineno, int):
                lineno = min(lineno, deco_lineno)
    return lineno


def _node_end_lineno(node: ast.AST) -> int:
    end_lineno = getattr(node, "end_lineno", None)
    if isinstance(end_lineno, int):
        return end_lineno
    lineno = getattr(node, "lineno", 1)
    return lineno


def _collect_line_numbers(hunk: DiffHunk, *, use_new: bool, changed_line_type: str) -> list[int]:
    numbers: list[int] = []
    for line in hunk.lines:
        if line.line_type != changed_line_type:
            continue
        lineno = line.new_lineno if use_new else line.original_lineno
        if isinstance(lineno, int) and lineno > 0:
            numbers.append(lineno)
    return numbers


def _normalize_module_name(name: Optional[str]) -> Optional[str]:
    if not isinstance(name, str):
        return None

    normalized = ".".join(part.strip() for part in name.split(".") if part.strip())
    return normalized or None
