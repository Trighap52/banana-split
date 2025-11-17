"""
Logging helpers for banana-split.

At this stage we only provide simple configuration based on a verbosity
level. More advanced structured logging can be added later if needed.
"""

from __future__ import annotations

import logging


def configure_logging(verbosity: int) -> None:
    """
    Configure the root logger based on a verbosity count.

    verbosity == 0 -> WARNING
    verbosity == 1 -> INFO
    verbosity >= 2 -> DEBUG
    """

    if verbosity <= 0:
        level = logging.WARNING
    elif verbosity == 1:
        level = logging.INFO
    else:
        level = logging.DEBUG

    logging.basicConfig(
        level=level,
        format="%(levelname)s %(name)s: %(message)s",
    )

