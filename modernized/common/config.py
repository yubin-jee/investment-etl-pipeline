"""Configuration loader for batch_config.ini.

Replaces the hardcoded Windows paths scattered throughout the legacy
scripts with a centralized, configurable loader.
"""

from __future__ import annotations

import configparser
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Default config path relative to the repository root
DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "batch_config.ini"


def load_config(config_path: Path | None = None) -> dict[str, Any]:
    """Read batch_config.ini and return a flat configuration dictionary.

    Args:
        config_path: Path to the INI file. Defaults to
            ``<repo_root>/config/batch_config.ini``.

    Returns:
        Dictionary with keys:
            - ``trade_input``, ``holdings_input``, ``pricing_input``,
              ``clients_input``, ``compliance_input``, ``report_output``,
              ``log_output`` — directory paths (as strings)
            - ``db_server``, ``db_database`` — database connection info
            - ``recon_tolerance_usd`` — float tolerance for recon breaks
            - ``max_trade_errors`` — int threshold for aborting a run

    Raises:
        FileNotFoundError: If the config file does not exist.
    """
    if config_path is None:
        config_path = DEFAULT_CONFIG_PATH

    config_path = Path(config_path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    logger.info("Loading config from %s", config_path)

    parser = configparser.ConfigParser()
    parser.read(config_path)

    config: dict[str, Any] = {}

    # Paths
    if parser.has_section("paths"):
        for key in [
            "trade_input",
            "holdings_input",
            "pricing_input",
            "clients_input",
            "compliance_input",
            "report_output",
            "log_output",
        ]:
            config[key] = parser.get("paths", key, fallback="")

    # Database
    if parser.has_section("database"):
        config["db_server"] = parser.get("database", "server", fallback="")
        config["db_database"] = parser.get("database", "database", fallback="")

    # Tolerances
    if parser.has_section("tolerances"):
        config["recon_tolerance_usd"] = parser.getfloat(
            "tolerances", "recon_tolerance_usd", fallback=1.0
        )
        config["max_trade_errors"] = parser.getint(
            "tolerances", "max_trade_errors", fallback=50
        )

    return config
