"""Configuration loader backed by ``config/batch_config.ini``.

The legacy scripts hardcoded Windows network-drive paths and never read the
INI file that already existed in the repo. This loader actually parses it and
exposes a normalized dict, so every option reads its paths/DB settings from one
place.
"""

from __future__ import annotations

import configparser
from pathlib import Path
from typing import Any


def load_config(config_path: Path) -> dict[str, Any]:
    """Load ``batch_config.ini`` into a normalized dict.

    Args:
        config_path: Path to the ``batch_config.ini`` file.

    Returns:
        A dict with the keys the pipeline cares about::

            {
                "trade_input": str,
                "holdings_input": str,
                "pricing_input": str,
                "report_output": str,
                "log_output": str,
                "database": {"server": str, "name": str},
                "tolerances": {"recon_tolerance_usd": float, ...},
            }

    Raises:
        FileNotFoundError: If ``config_path`` does not exist.
    """
    config_path = Path(config_path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    parser = configparser.ConfigParser()
    parser.read(config_path)

    paths = parser["paths"] if parser.has_section("paths") else {}
    database = parser["database"] if parser.has_section("database") else {}
    tolerances = (
        parser["tolerances"] if parser.has_section("tolerances") else {}
    )

    def _to_float(value: str | None, default: float) -> float:
        try:
            return float(value) if value is not None else default
        except (TypeError, ValueError):
            return default

    return {
        "trade_input": paths.get("trade_input", ""),
        "holdings_input": paths.get("holdings_input", ""),
        "pricing_input": paths.get("pricing_input", ""),
        "report_output": paths.get("report_output", ""),
        "log_output": paths.get("log_output", ""),
        "database": {
            "server": database.get("server", ""),
            "name": database.get("database", ""),
        },
        "tolerances": {
            "recon_tolerance_usd": _to_float(
                tolerances.get("recon_tolerance_usd"), 1.00
            ),
            "price_stale_hours": _to_float(
                tolerances.get("price_stale_hours"), 18
            ),
            "max_trade_errors": _to_float(
                tolerances.get("max_trade_errors"), 50
            ),
        },
    }
