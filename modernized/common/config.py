"""Configuration loader for batch_config.ini.

Reads the INI-format config file and provides a typed dict
of paths, database settings, and operational parameters.
"""

from __future__ import annotations

import configparser
from pathlib import Path
from typing import Any


def load_config(config_path: Path) -> dict[str, Any]:
    """Load configuration from a batch_config.ini file.

    Args:
        config_path: Path to the INI configuration file.

    Returns:
        Dict with keys: trade_input, holdings_input, pricing_input,
        clients_input, compliance_input, report_output, log_output,
        db_server, db_name, recon_tolerance, price_stale_hours,
        max_trade_errors, schedule.

    Raises:
        FileNotFoundError: If the config file does not exist.
    """
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    parser = configparser.ConfigParser()
    parser.read(config_path)

    config: dict[str, Any] = {}

    # Paths
    if parser.has_section("paths"):
        config["trade_input"] = parser.get("paths", "trade_input", fallback="")
        config["holdings_input"] = parser.get("paths", "holdings_input", fallback="")
        config["pricing_input"] = parser.get("paths", "pricing_input", fallback="")
        config["clients_input"] = parser.get("paths", "clients_input", fallback="")
        config["compliance_input"] = parser.get("paths", "compliance_input", fallback="")
        config["report_output"] = parser.get("paths", "report_output", fallback="")
        config["log_output"] = parser.get("paths", "log_output", fallback="")

    # Database
    if parser.has_section("database"):
        config["db_server"] = parser.get("database", "server", fallback="")
        config["db_name"] = parser.get("database", "database", fallback="")

    # Tolerances
    if parser.has_section("tolerances"):
        config["recon_tolerance"] = parser.getfloat(
            "tolerances", "recon_tolerance_usd", fallback=1.00,
        )
        config["price_stale_hours"] = parser.getint(
            "tolerances", "price_stale_hours", fallback=18,
        )
        config["max_trade_errors"] = parser.getint(
            "tolerances", "max_trade_errors", fallback=50,
        )

    # Schedule
    if parser.has_section("schedule"):
        config["schedule"] = dict(parser.items("schedule"))

    return config
