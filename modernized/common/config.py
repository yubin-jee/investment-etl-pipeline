"""Configuration loader for batch_config.ini.

Provides a single function to read the INI config file and return a
structured dictionary, replacing the legacy pattern of hardcoded paths.
"""

from __future__ import annotations

import configparser
from pathlib import Path
from typing import Any


def load_config(config_path: Path) -> dict[str, Any]:
    """Load configuration from the batch INI file.

    Args:
        config_path: Path to ``batch_config.ini``.

    Returns:
        Dictionary with top-level keys for each section:
        ``paths``, ``database``, ``email``, ``schedule``, ``tolerances``.
        Within ``paths``, values are converted to ``Path`` objects.

    Raises:
        FileNotFoundError: If the config file does not exist.
    """
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    parser = configparser.ConfigParser()
    parser.read(config_path)

    config: dict[str, Any] = {}

    # --- paths section ---
    if parser.has_section("paths"):
        config["paths"] = {
            key: Path(value) for key, value in parser.items("paths")
        }

    # --- database section ---
    if parser.has_section("database"):
        config["database"] = dict(parser.items("database"))

    # --- email section ---
    if parser.has_section("email"):
        config["email"] = dict(parser.items("email"))

    # --- schedule section ---
    if parser.has_section("schedule"):
        config["schedule"] = dict(parser.items("schedule"))

    # --- tolerances section ---
    if parser.has_section("tolerances"):
        raw = dict(parser.items("tolerances"))
        config["tolerances"] = {
            "recon_tolerance_usd": float(raw.get("recon_tolerance_usd", "1.00")),
            "price_stale_hours": int(raw.get("price_stale_hours", "18")),
            "max_trade_errors": int(raw.get("max_trade_errors", "50")),
        }

    return config
