"""Shared invariants for generated, imported and edited split plans."""

from __future__ import annotations

from .analysis.semantic_atomizer import dependency_pairs
from .domain import Plan
from .errors import PlanValidationError


def validate_plan(plan: Plan) -> None:
    """
    Validate core invariants while preserving suggested commit order.

    Invariants:
      - every hunk in the diff appears in exactly one suggested commit;
      - no suggested commit references unknown hunks;
      - for each file, the sequence of hunks across commits preserves
        the original per-file order.
    """

    diff = plan.diff
    suggested_commits = plan.suggested_commits

    # Map each hunk id to its file path and a global order index.
    hunk_order: dict[str, int] = {}
    hunk_file: dict[str, str] = {}
    all_hunk_ids: list[str] = []
    order_counter = 0

    for file in diff.files:
        path = file.path_new or file.path_old or ""
        for hunk in file.hunks:
            all_hunk_ids.append(hunk.id)
            hunk_order[hunk.id] = order_counter
            hunk_file[hunk.id] = path
            order_counter += 1

    # Ensure all referenced hunks exist and that coverage is exact.
    assigned_ids: list[str] = []
    for commit in suggested_commits:
        for hid in commit.hunk_ids:
            if hid not in hunk_order:
                raise PlanValidationError(f"plan references unknown hunk id {hid}")
            assigned_ids.append(hid)

    if set(assigned_ids) != set(all_hunk_ids):
        missing = set(all_hunk_ids) - set(assigned_ids)
        extra = set(assigned_ids) - set(all_hunk_ids)
        raise PlanValidationError(
            f"plan does not cover hunks exactly once (missing={missing}, extra={extra})"
        )

    if len(assigned_ids) != len(set(assigned_ids)):
        raise PlanValidationError("plan assigns at least one hunk to multiple commits")

    commit_ids = [commit.id for commit in suggested_commits]
    if len(commit_ids) != len(set(commit_ids)):
        raise PlanValidationError("duplicate suggested commit IDs")
    for commit in suggested_commits:
        if not commit.hunk_ids:
            raise PlanValidationError("suggested commits must not be empty")
        if not commit.title.strip() or any(c in commit.title for c in "\n\r\x00"):
            raise PlanValidationError("commit title must be a non-empty single line")
        if commit.body is not None and "\x00" in commit.body:
            raise PlanValidationError("commit body must not contain NUL")
        try:
            commit.title.encode("utf-8", "surrogateescape")
            if commit.body is not None:
                commit.body.encode("utf-8", "surrogateescape")
        except UnicodeError:
            raise PlanValidationError("commit message contains invalid Unicode") from None

    owners = {hid: index for index, commit in enumerate(suggested_commits)
              for hid in commit.hunk_ids}
    for source, dependent in dependency_pairs(diff):
        if owners[source] > owners[dependent]:
            raise PlanValidationError(f"plan violates dependency: {source} must precede {dependent}")

    # File operations (rename/mode/add/delete) must be selected in one commit.
    for file in diff.files:
        if file.indivisible:
            operation_owners = [commit for commit in suggested_commits
                                if any(h.id in commit.hunk_ids for h in file.hunks)]
            if len(operation_owners) != 1:
                raise PlanValidationError(f"file operation must remain indivisible: {file.path_new or file.path_old}")

    # Verify per-file order is preserved across commits.
    for file in diff.files:
        path = file.path_new or file.path_old or ""
        file_hunk_ids = [h.id for h in file.hunks]
        if not file_hunk_ids:
            continue

        sequence: list[int] = []
        for commit in plan.suggested_commits:
            for hid in commit.hunk_ids:
                if hunk_file.get(hid) == path:
                    sequence.append(hunk_order[hid])

        expected = [hunk_order[hid] for hid in file_hunk_ids]
        if sequence != expected:
            raise PlanValidationError(
                f"plan reorders hunks for file {path}; expected {expected}, got {sequence}"
            )
