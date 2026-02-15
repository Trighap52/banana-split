"""
Custom exception types used across banana-split.

Defining explicit error classes makes it easier for the CLI and higher
layers to distinguish between user-facing failures and unexpected bugs.
"""

from __future__ import annotations


class BananaSplitError(Exception):
    """Base class for all banana-split specific errors."""


class GitError(BananaSplitError):
    """Raised when git operations fail."""


class DiffParseError(BananaSplitError):
    """Raised when parsing a diff fails."""


class PlanValidationError(BananaSplitError):
    """Raised when a generated plan violates core invariants."""


class UnsupportedOperationError(BananaSplitError):
    """Raised when a requested workflow is not yet supported safely."""

