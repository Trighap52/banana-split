"""
Semantic atomization for diff hunks.

This module builds richer atomic changes than a pure file-based split by
grouping hunks around symbols and ordering groups with lightweight
dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from ..domain import AtomicChange, Diff, DiffHunk
from .language_intel import detect_language


@dataclass
class _SemanticNode:
    """
    Internal semantic unit used before conversion to AtomicChange.
    """

    id: str
    file_path: str
    symbol: Optional[str]
    hunk_ids: List[str]
    tags: Set[str]
    summary: Optional[str]
    first_order: int


def atomize_semantically(diff: Diff) -> List[AtomicChange]:
    """
    Group hunks into semantic atomic changes with dependency-aware order.

    Strategy:
      - group by file + symbol where available,
      - preserve intra-file ordering dependencies,
      - link source symbols before matching test symbols, and
      - topologically order units using those dependencies.
    """

    hunk_order = _build_hunk_order(diff)
    nodes, by_file, by_symbol, by_module = _build_nodes(diff, hunk_order)
    if not nodes:
        return []

    edges = _build_dependencies(nodes, by_file, by_symbol, by_module)
    ordered_nodes = _topological_sort(nodes, edges)

    return [
        AtomicChange(
            id=node.id,
            hunk_ids=list(node.hunk_ids),
            tags=set(node.tags),
            summary=node.summary,
        )
        for node in ordered_nodes
    ]


def _build_hunk_order(diff: Diff) -> Dict[str, int]:
    order: Dict[str, int] = {}
    i = 0
    for file in diff.files:
        for hunk in file.hunks:
            order[hunk.id] = i
            i += 1
    return order


def _build_nodes(
    diff: Diff,
    hunk_order: Dict[str, int],
) -> Tuple[
    List[_SemanticNode],
    Dict[str, List[_SemanticNode]],
    Dict[str, List[_SemanticNode]],
    Dict[str, List[_SemanticNode]],
]:
    nodes: List[_SemanticNode] = []
    by_file: Dict[str, List[_SemanticNode]] = {}
    by_symbol: Dict[str, List[_SemanticNode]] = {}
    by_module: Dict[str, List[_SemanticNode]] = {}

    for file in diff.files:
        if not file.hunks:
            continue

        path = file.path_new or file.path_old or ""
        if not path:
            continue

        tags = _base_tags_for_path(path)
        groups = _group_hunks_by_symbol(file.hunks)
        file_nodes: List[_SemanticNode] = []

        for idx, (symbol, hunks) in enumerate(groups):
            if not hunks:
                continue

            hunk_ids = [h.id for h in hunks]
            node_tags = set(tags)
            node_tags.add(f"path:{path}")
            if symbol:
                node_tags.add(f"symbol:{_normalize_symbol(symbol)}")

            module_key = _module_key(path)
            if module_key:
                node_tags.add(f"module:{module_key}")

            summary = f"Changes in {path}"
            if symbol:
                summary = f"Changes in {path} ({symbol})"

            first_order = min(hunk_order[hid] for hid in hunk_ids)
            node = _SemanticNode(
                id=f"{path}::ac{idx}",
                file_path=path,
                symbol=symbol,
                hunk_ids=hunk_ids,
                tags=node_tags,
                summary=summary,
                first_order=first_order,
            )
            nodes.append(node)
            file_nodes.append(node)

            normalized_symbol = _normalize_symbol(symbol) if symbol else None
            if normalized_symbol:
                by_symbol.setdefault(normalized_symbol, []).append(node)

            if module_key:
                by_module.setdefault(module_key, []).append(node)

        by_file[path] = file_nodes

    return nodes, by_file, by_symbol, by_module


def _group_hunks_by_symbol(hunks: List[DiffHunk]) -> List[Tuple[Optional[str], List[DiffHunk]]]:
    groups: Dict[Optional[str], List[DiffHunk]] = {}
    order: List[Optional[str]] = []

    for hunk in hunks:
        symbol: Optional[str] = None
        meta_symbol = hunk.meta.get("symbol")
        if isinstance(meta_symbol, str) and meta_symbol.strip():
            symbol = meta_symbol.strip()

        if symbol not in groups:
            groups[symbol] = []
            order.append(symbol)
        groups[symbol].append(hunk)

    return [(key, groups[key]) for key in order]


def _build_dependencies(
    nodes: List[_SemanticNode],
    by_file: Dict[str, List[_SemanticNode]],
    by_symbol: Dict[str, List[_SemanticNode]],
    by_module: Dict[str, List[_SemanticNode]],
) -> Dict[str, Set[str]]:
    node_by_id = {node.id: node for node in nodes}
    edges: Dict[str, Set[str]] = {node.id: set() for node in nodes}

    # Intra-file ordering dependencies.
    for file_nodes in by_file.values():
        for idx in range(len(file_nodes) - 1):
            src = file_nodes[idx].id
            dst = file_nodes[idx + 1].id
            edges[src].add(dst)

    # Source -> test dependencies for matching symbols/modules.
    for node in nodes:
        if "test" not in node.tags:
            continue

        # Prefer symbol-based linkage.
        linked_sources: Set[str] = set()
        if node.symbol:
            symbol_key = _normalize_symbol(node.symbol)
            for candidate in by_symbol.get(symbol_key, []):
                if candidate.id == node.id:
                    continue
                if "test" in candidate.tags:
                    continue
                linked_sources.add(candidate.id)

        # If symbol signal is missing, fall back to module name linkage.
        if not linked_sources:
            module_key = _module_key(node.file_path)
            if module_key:
                for candidate in by_module.get(module_key, []):
                    if candidate.id == node.id:
                        continue
                    if "test" in candidate.tags:
                        continue
                    linked_sources.add(candidate.id)

        for source_id in linked_sources:
            if source_id in node_by_id:
                edges[source_id].add(node.id)

    return edges


def _topological_sort(
    nodes: List[_SemanticNode],
    edges: Dict[str, Set[str]],
) -> List[_SemanticNode]:
    node_by_id = {node.id: node for node in nodes}
    indegree: Dict[str, int] = {node.id: 0 for node in nodes}

    for src, dsts in edges.items():
        if src not in indegree:
            continue
        for dst in dsts:
            if dst in indegree:
                indegree[dst] += 1

    ready = sorted(
        [nid for nid, deg in indegree.items() if deg == 0],
        key=lambda nid: node_by_id[nid].first_order,
    )
    ordered_ids: List[str] = []

    while ready:
        nid = ready.pop(0)
        ordered_ids.append(nid)
        for dst in sorted(
            edges.get(nid, set()),
            key=lambda x: node_by_id[x].first_order if x in node_by_id else 0,
        ):
            if dst not in indegree:
                continue
            indegree[dst] -= 1
            if indegree[dst] == 0:
                ready.append(dst)
        ready.sort(key=lambda x: node_by_id[x].first_order)

    if len(ordered_ids) != len(nodes):
        # Fall back to the stable original order if dependency graph has cycles.
        return sorted(nodes, key=lambda n: n.first_order)

    return [node_by_id[nid] for nid in ordered_ids]


def _base_tags_for_path(path: str) -> Set[str]:
    tags: Set[str] = set()
    language = detect_language(path)
    if language:
        tags.add(language)
    if _is_test_path(path):
        tags.add("test")
    return tags


def _is_test_path(path: str) -> bool:
    lower = path.lower()
    name = Path(path).name.lower()
    if "/tests/" in f"/{lower}/":
        return True
    if name.startswith("test_") or name.endswith("_test.py") or name.endswith(".spec.ts"):
        return True
    return "test" in lower


def _normalize_symbol(symbol: Optional[str]) -> str:
    if not symbol:
        return ""
    return " ".join(symbol.strip().split()).lower()


def _module_key(path: str) -> Optional[str]:
    name = Path(path).stem
    if not name:
        return None
    lower = name.lower()
    if lower.startswith("test_"):
        lower = lower[len("test_") :]
    if lower.endswith("_test"):
        lower = lower[: -len("_test")]
    return lower or None

