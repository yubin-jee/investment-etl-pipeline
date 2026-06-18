"""Shared logging configuration for the Meridian Capital ETL scripts.

The legacy scripts wrote all user-facing output with ``print``. To preserve the
exact console behaviour while moving to the ``logging`` module, the handler is
configured to emit the bare message to ``stdout`` (no level/timestamp prefix).
"""

from __future__ import annotations

import logging
import sys

_CONFIGURED = False


def get_logger(name: str) -> logging.Logger:
    """Return a module logger that mirrors the legacy ``print`` output."""
    global _CONFIGURED
    if not _CONFIGURED:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter("%(message)s"))
        root = logging.getLogger()
        root.handlers.clear()
        root.addHandler(handler)
        root.setLevel(logging.INFO)
        _CONFIGURED = True
    return logging.getLogger(name)
