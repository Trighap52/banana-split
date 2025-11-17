"""
Configuration model for banana-split.

The CLI constructs a Config instance and passes it down into the core
orchestration logic so behavior can be adjusted without relying on
global state.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class Config:
    """
    Top-level configuration for a banana-split run.

    This will grow over time as more features are implemented.
    """

    target: Optional[str] = None
    use_staged: bool = False
    dry_run: bool = False
    use_ai: bool = False
    verbosity: int = 0

